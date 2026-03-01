"""
Tools System - Base Tool Class and Manager
"""

import os
import importlib
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
import json


class Tool(ABC):
    """Base class for all tools"""
    
    name: str = ""
    description: str = ""
    parameters: Dict = {}
    
    def __init__(self, agent):
        self.agent = agent
    
    @abstractmethod
    async def execute(self, **kwargs) -> Any:
        """Execute the tool with given parameters"""
        pass
    
    def validate_params(self, params: Dict) -> bool:
        """Validate tool parameters"""
        return True


class Response:
    """Tool response wrapper"""
    
    def __init__(self, message: str = "", break_loop: bool = False, data: Any = None):
        self.message = message
        self.break_loop = break_loop
        self.data = data or {}


class ToolsManager:
    """Manages loading and execution of tools"""
    
    def __init__(self, agent):
        self.agent = agent
        self.tools: Dict[str, Tool] = {}
        self._load_tools()
    
    def _load_tools(self):
        """Load all tools from the tools directory"""
        tools_dir = os.path.join(
            os.path.dirname(__file__), 
            "..", 
            "tools"
        )
        
        if not os.path.exists(tools_dir):
            # Try alternative paths
            paths = [
                "/root/.openclaw/workspace/python/tools",
                "./python/tools",
            ]
            for path in paths:
                if os.path.exists(path):
                    tools_dir = path
                    break
        
        if not os.path.exists(tools_dir):
            print(f"Tools directory not found")
            return
        
        # Load each tool module
        for filename in os.listdir(tools_dir):
            if filename.endswith(".py") and not filename.startswith("_"):
                tool_name = filename[:-3]
                self._load_tool(tool_name)
    
    def _load_tool(self, tool_name: str):
        """Load a single tool"""
        try:
            # Try different import paths
            for module_path in [
                f"python.tools.{tool_name}",
                f"/root/.openclaw/workspace/python/tools.{tool_name}",
            ]:
                try:
                    module = importlib.import_module(module_path)
                    
                    # Find tool class - try multiple naming conventions
                    possible_names = [
                        "".join(word.capitalize() for word in tool_name.split("_")),  # memory -> Memory
                        "".join(word.capitalize() for word in tool_name.split("_")) + "Tool",  # memory -> MemoryTool
                        tool_name.capitalize(),  # memory -> Memory
                    ]
                    
                    tool_class = None
                    for class_name in possible_names:
                        if hasattr(module, class_name):
                            tool_class = getattr(module, class_name)
                            break
                    
                    if tool_class:
                        tool_instance = tool_class(self.agent)
                        self.tools[tool_name] = tool_instance
                        return
                    
                except (ImportError, AttributeError):
                    continue
            
            # Log if not found but module imported
            try:
                importlib.import_module(f"python.tools.{tool_name}")
            except Exception:
                pass  # Module not found via any import path
                
        except Exception as e:
            print(f"Error loading tool {tool_name}: {e}")
    
    def get_tool(self, name: str) -> Optional[Tool]:
        """Get a tool by name"""
        return self.tools.get(name)
    
    def list_tools(self) -> list:
        """List all available tools"""
        return [
            {
                "name": name,
                "description": tool.description,
                "parameters": tool.parameters
            }
            for name, tool in self.tools.items()
        ]
    
    async def execute(self, tool_name: str, **kwargs) -> Response:
        """Execute a tool"""
        tool = self.get_tool(tool_name)
        
        if not tool:
            return Response(
                message=f"Tool not found: {tool_name}",
                break_loop=False
            )
        
        try:
            result = await tool.execute(**kwargs)
            
            if isinstance(result, Response):
                return result
            
            return Response(message=str(result), break_loop=False)
            
        except Exception as e:
            return Response(
                message=f"Error executing {tool_name}: {str(e)}",
                break_loop=False
            )
    
    def has_tool(self, name: str) -> bool:
        """Check if tool exists"""
        return name in self.tools


__all__ = ["Tool", "Response", "ToolsManager"]
