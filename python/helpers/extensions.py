"""
Extensions System - Hook-based extension points for the agent lifecycle.
"""

from typing import Any, Callable, Dict, List


class ExtensionsManager:
    """Manages agent lifecycle extensions/hooks."""

    # Valid hook points in the agent lifecycle
    VALID_HOOKS = {
        "monologue_start",
        "before_llm_call",
        "after_llm_call",
        "monologue_end",
        "tool_before",
        "tool_after",
        "error",
    }

    def __init__(self, agent):
        self.agent = agent
        self._hooks: Dict[str, List[Callable]] = {hook: [] for hook in self.VALID_HOOKS}

    def register(self, hook_name: str, callback: Callable):
        """Register a callback for a lifecycle hook."""
        if hook_name not in self.VALID_HOOKS:
            raise ValueError(f"Unknown hook: {hook_name}. Valid hooks: {self.VALID_HOOKS}")
        self._hooks[hook_name].append(callback)

    def unregister(self, hook_name: str, callback: Callable):
        """Remove a callback from a hook."""
        if hook_name in self._hooks:
            self._hooks[hook_name] = [cb for cb in self._hooks[hook_name] if cb != callback]

    async def call(self, hook_name: str, **kwargs) -> List[Any]:
        """Call all registered callbacks for a hook."""
        if hook_name not in self._hooks:
            return []

        results = []
        for callback in self._hooks[hook_name]:
            try:
                import asyncio
                if asyncio.iscoroutinefunction(callback):
                    result = await callback(self.agent, **kwargs)
                else:
                    result = callback(self.agent, **kwargs)
                results.append(result)
            except Exception as e:
                print(f"Extension hook '{hook_name}' error: {e}")

        return results

    def list_hooks(self) -> Dict[str, int]:
        """List all hooks and their registered callback count."""
        return {name: len(cbs) for name, cbs in self._hooks.items()}
