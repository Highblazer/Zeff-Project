#!/usr/bin/env python3
"""
OpenClaw Browser Tool - Full Integration
Connects to OpenClaw's browser tool for real automation
"""

import json
import os
import sys

# OpenClaw browser tool interface
class OpenClawBrowser:
    """Interface to OpenClaw's browser tool"""
    
    def __init__(self):
        self.target = "host"  # Use local browser
        self.profile = "openclaw"  # OpenClaw-managed browser
        
    def navigate(self, url):
        """Navigate to a URL"""
        return {
            "action": "navigate",
            "targetUrl": url
        }
    
    def snapshot(self):
        """Take a screenshot"""
        return {"action": "snapshot"}
    
    def click(self, ref):
        """Click an element by reference"""
        return {
            "action": "act",
            "request": {
                "kind": "click",
                "ref": ref
            }
        }
    
    def type(self, ref, text):
        """Type text into an element"""
        return {
            "action": "act",
            "request": {
                "kind": "type",
                "ref": ref,
                "text": text
            }
        }
    
    def get_page_info(self):
        """Get current page information"""
        return {"action": "snapshot"}

def create_browser_tool_definition():
    """Create the browser tool definition for MiniMax"""
    
    tool_definition = {
        "name": "browser",
        "description": "Control a web browser to navigate websites, interact with elements, and extract information. Use this tool when you need to access live web content, fill forms, click buttons, or read information from websites.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["navigate", "snapshot", "click", "type", "scroll", "search", "close"],
                    "description": "The browser action to perform"
                },
                "targetUrl": {
                    "type": "string",
                    "description": "URL to navigate to (for navigate action)"
                },
                "ref": {
                    "type": "string",
                    "description": "Element reference to interact with (for click, type actions)"
                },
                "text": {
                    "type": "string",
                    "description": "Text to type (for type action)"
                },
                "direction": {
                    "type": "string",
                    "enum": ["up", "down", "left", "right"],
                    "description": "Scroll direction (for scroll action)"
                },
                "query": {
                    "type": "string",
                    "description": "Search query (for search action)"
                }
            },
            "required": ["action"]
        }
    }
    
    return tool_definition

# Example prompts for MiniMax
EXAMPLE_PROMPTS = [
    "Navigate to news.ycombinator.com and tell me the top 3 stories",
    "Go to wikipedia.org and search for 'artificial intelligence'",
    "Visit github.com and find repositories related to AI agents",
    "Go to a job posting site and find Python developer jobs",
    "Navigate to a news site and summarize the main headlines"
]

def format_browser_response(response):
    """Format browser tool response for display"""
    if "error" in response:
        return f"❌ Error: {response['error']}"
    
    if response.get("action") == "snapshot":
        # Display screenshot info
        return f"📸 Screenshot captured - {len(response.get('elements', []))} elements found"
    
    return f"✅ {response.get('message', 'Action completed')}"

# Demo prompts for the UI
DEMO_TASKS = {
    "News": "Navigate to news.ycombinator.com and list the top 5 headlines",
    "Search": "Go to Wikipedia and search for 'Machine Learning'",
    "Shopping": "Visit Amazon and find trending tech products",
    "Jobs": "Go to LinkedIn and search for AI developer positions",
    "Research": "Visit GitHub and find popular AI agent projects"
}

if __name__ == "__main__":
    print("OpenClaw Browser Tool")
    print("=" * 50)
    print("\nTool Definition:")
    print(json.dumps(create_browser_tool_definition(), indent=2))
    print("\nExample Tasks:")
    for task, prompt in DEMO_TASKS.items():
        print(f"  {task}: {prompt}")
