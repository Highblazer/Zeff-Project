"""
Binary Rogue Agent Core Engine
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
import uuid

from python.models import get_model
from python.helpers import print_style
from python.helpers.history import History
from python.helpers.context import get_context_data

# Maximum recursion depth for tool calls to prevent infinite loops
MAX_TOOL_DEPTH = 10

# Tool call delimiters — must be unambiguous markers, NOT common characters like {
TOOL_CALL_MARKERS = ["<tool_call>", "[TOOL_CALL]"]
TOOL_CALL_PATTERN = re.compile(
    r'<tool_call>\s*(\{.*?\})\s*</tool_call>',
    re.DOTALL
)


@dataclass
class AgentConfig:
    """Agent configuration"""
    name: str
    model: str = "minimax"
    temperature: float = 0.7
    max_tokens: int = 8192
    system_prompt: str = ""
    tools: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    memory_enabled: bool = True
    extensions: list[str] = field(default_factory=list)


class Agent:
    """Main agent class"""

    def __init__(self, config: AgentConfig):
        self.config = config
        self.id = str(uuid.uuid4())[:8]
        self.name = config.name

        # Initialize model
        self.model = get_model(config.model)

        # Initialize components
        self.history = History(self)
        self.tools_mgr = None
        self.skills_mgr = None
        self.memory = None
        self.extensions = None

        # State
        self.running = False
        self.paused = False

    async def init(self):
        """Initialize agent subsystems"""
        # Load skills
        from python.helpers.skills import SkillsManager
        self.skills_mgr = SkillsManager()

        # Load tools
        from python.helpers.tools import ToolsManager
        self.tools_mgr = ToolsManager(self)

        # Load memory
        if self.config.memory_enabled:
            from python.helpers.memory import MemoryManager
            self.memory = MemoryManager(self.name)

        # Load extensions
        from python.helpers.extensions import ExtensionsManager
        self.extensions = ExtensionsManager(self)

        print_style.PrintStyle(
            font_color="#00ff00",
            padding=True
        ).print(f"Agent '{self.name}' initialized")

    async def think(self, user_message: str, _depth: int = 0) -> str:
        """Main agent loop - think and respond.

        Args:
            user_message: The user's input message.
            _depth: Internal recursion counter (do not set manually).
        """
        if _depth >= MAX_TOOL_DEPTH:
            return "Error: Maximum tool call depth exceeded. Stopping to prevent infinite loop."

        self.running = True

        try:
            # Call extensions: monologue_start
            if self.extensions:
                await self.extensions.call("monologue_start")

            # Build messages
            messages = await self.build_messages(user_message)

            # Add skills context to system prompt
            system = self.config.system_prompt
            if self.skills_mgr:
                skills_context = self.skills_mgr.get_context()
                if skills_context:
                    system += f"\n\n{skills_context}"

            messages.insert(0, {"role": "system", "content": system})

            # Call extensions: before_llm
            if self.extensions:
                await self.extensions.call("before_llm_call")

            # Get LLM response
            response, reasoning = self.model.complete(messages)

            # Call extensions: after_llm
            if self.extensions:
                await self.extensions.call("after_llm_call")

            # Add to history
            self.history.add_message("user", user_message)
            self.history.add_message("assistant", response)

            # Check if tools needed and execute them
            tool_calls = self.parse_tool_calls(response)
            if tool_calls:
                tool_results = await self.execute_tools(tool_calls)
                return await self.think(f"Tool results:\n{tool_results}", _depth=_depth + 1)

            # Call extensions: monologue_end
            if self.extensions:
                await self.extensions.call("monologue_end")

            return response

        finally:
            self.running = False

    async def build_messages(self, user_message: str) -> list[dict]:
        """Build message history"""
        messages = []

        # Add recent history
        recent = self.history.get_recent(10)
        for msg in recent:
            messages.append({"role": msg["role"], "content": msg["content"]})

        # Add current message
        messages.append({"role": "user", "content": user_message})

        return messages

    def parse_tool_calls(self, response: str) -> list[dict]:
        """Parse tool calls from the LLM response.

        Looks for structured tool call markers like:
            <tool_call>{"tool": "calculator", "params": {"expression": "2+2"}}</tool_call>
            [TOOL_CALL]{"tool": "search", "params": {"query": "weather"}}[/TOOL_CALL]

        Returns a list of parsed tool call dicts, or empty list if none found.
        """
        calls = []

        # Pattern 1: <tool_call>...</tool_call>
        for match in TOOL_CALL_PATTERN.finditer(response):
            try:
                call = json.loads(match.group(1))
                if isinstance(call, dict) and "tool" in call:
                    calls.append(call)
            except (json.JSONDecodeError, KeyError):
                continue

        # Pattern 2: [TOOL_CALL]...[/TOOL_CALL]
        bracket_pattern = re.compile(
            r'\[TOOL_CALL\]\s*(\{.*?\})\s*\[/TOOL_CALL\]',
            re.DOTALL
        )
        for match in bracket_pattern.finditer(response):
            try:
                call = json.loads(match.group(1))
                if isinstance(call, dict) and "tool" in call:
                    calls.append(call)
            except (json.JSONDecodeError, KeyError):
                continue

        return calls

    async def execute_tools(self, tool_calls: list[dict]) -> str:
        """Execute parsed tool calls via ToolsManager.

        Args:
            tool_calls: List of dicts with 'tool' and 'params' keys.

        Returns:
            Formatted string of all tool results.
        """
        if not self.tools_mgr:
            return "Error: Tools system not initialized. Call agent.init() first."

        results = []
        for call in tool_calls:
            tool_name = call.get("tool", "")
            params = call.get("params", {})

            if not tool_name:
                results.append("Error: Tool call missing 'tool' name.")
                continue

            # Call extensions: tool_before
            if self.extensions:
                await self.extensions.call("tool_before", tool_name=tool_name, params=params)

            result = await self.tools_mgr.execute(tool_name, **params)

            # Call extensions: tool_after
            if self.extensions:
                await self.extensions.call("tool_after", tool_name=tool_name, result=result)

            # Record in history
            self.history.add_message("tool", f"[{tool_name}] {result.message}")

            results.append(f"[{tool_name}]: {result.message}")

        return "\n".join(results)

    async def pause(self):
        """Pause agent"""
        self.paused = True

    async def resume(self):
        """Resume agent"""
        self.paused = False

    def get_state(self) -> dict:
        """Get agent state"""
        return {
            "id": self.id,
            "name": self.name,
            "running": self.running,
            "paused": self.paused,
            "history_count": len(self.history.messages),
        }


class AgentContext:
    """Agent context for multi-agent coordination"""

    _contexts: dict[str, Agent] = {}

    @staticmethod
    def create(config: AgentConfig) -> Agent:
        """Create new agent context"""
        agent = Agent(config)
        AgentContext._contexts[agent.id] = agent
        return agent

    @staticmethod
    def get(agent_id: str) -> Optional[Agent]:
        """Get agent by ID"""
        return AgentContext._contexts.get(agent_id)

    @staticmethod
    def remove(agent_id: str):
        """Remove an agent from the registry"""
        AgentContext._contexts.pop(agent_id, None)

    @staticmethod
    def all() -> list[Agent]:
        """Get all agents"""
        return list(AgentContext._contexts.values())


__all__ = ["Agent", "AgentConfig", "AgentContext"]
