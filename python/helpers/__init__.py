"""
Binary Rogue - Helper Modules
"""

from datetime import datetime
from typing import Any


# Context management
class Context:
    """Shared context data for agent coordination."""

    _data: dict = {}

    @staticmethod
    def get(key: str, default=None):
        return Context._data.get(key, default)

    @staticmethod
    def set(key: str, value: Any):
        Context._data[key] = value

    @staticmethod
    def clear():
        Context._data = {}


def get_context_data(key: str, default=None):
    return Context.get(key, default)


def set_context_data(key: str, value: Any):
    Context.set(key, value)
