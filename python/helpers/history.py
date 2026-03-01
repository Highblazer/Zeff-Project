"""
History management for agents
"""

from datetime import datetime
from typing import Optional
import json


class History:
    """Manages conversation history"""
    
    def __init__(self, agent, max_messages: int = 100):
        self.agent = agent
        self.max_messages = max_messages
        self.messages = []
    
    def add_message(self, role: str, content: str, metadata: dict = None):
        """Add a message to history"""
        msg = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {}
        }
        self.messages.append(msg)
        
        # Trim if too long
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages:]
        
        return msg
    
    def add_user(self, content: str):
        return self.add_message("user", content)
    
    def add_assistant(self, content: str):
        return self.add_message("assistant", content)
    
    def add_system(self, content: str):
        return self.add_message("system", content)
    
    def add_tool(self, tool_name: str, input_data: str, output_data: str):
        return self.add_message("tool", f"{tool_name}: {input_data}", 
                               {"tool_output": output_data})
    
    def get_recent(self, count: int = 10) -> list:
        """Get recent messages"""
        return self.messages[-count:]
    
    def get_messages_for_llm(self, count: int = 20) -> list:
        """Get messages formatted for LLM"""
        recent = self.get_recent(count)
        return [{"role": m["role"], "content": m["content"]} for m in recent]
    
    def search(self, query: str) -> list:
        """Search history"""
        return [m for m in self.messages if query.lower() in m["content"].lower()]
    
    def clear(self):
        """Clear history"""
        self.messages = []
    
    def save(self, filepath: str):
        """Save to file"""
        with open(filepath, 'w') as f:
            json.dump({
                "agent": self.agent.name,
                "messages": self.messages
            }, f, indent=2)
    
    def load(self, filepath: str):
        """Load from file"""
        with open(filepath, 'r') as f:
            data = json.load(f)
            self.messages = data.get("messages", [])
    
    def summarize(self, max_chars: int = 1000) -> str:
        """Summarize conversation"""
        if not self.messages:
            return "No conversation history."
        
        total = sum(len(m["content"]) for m in self.messages)
        if total < max_chars:
            return f"Conversation: {len(self.messages)} messages, {total} chars"
        
        # Summarize
        return f"Conversation: {len(self.messages)} messages. Recent topics: {self.messages[-3]['content'][:100]}..."
    
    def __len__(self):
        return len(self.messages)
    
    def __repr__(self):
        return f"History({len(self.messages)} messages)"
