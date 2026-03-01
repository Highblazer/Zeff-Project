"""
Skills System - SKILL.md based capabilities (Anthropic-compatible standard)
"""

import os
import re
import yaml
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from pathlib import Path


@dataclass
class Skill:
    """A skill with metadata and content"""
    name: str
    description: str
    path: Path
    version: str = ""
    author: str = ""
    tags: List[str] = field(default_factory=list)
    trigger_patterns: List[str] = field(default_factory=list)
    allowed_tools: List[str] = field(default_factory=list)
    content: str = ""  # The actual skill instructions


class SkillsManager:
    """Manages skills discovery, loading, and execution"""
    
    def __init__(self, skills_dir: str = "skills"):
        self.skills_dir = skills_dir
        self.loaded_skills = []
        self._discover_skills()
    
    def _discover_skills(self):
        """Find all SKILL.md files"""
        self.skills = []
        
        # Search in multiple locations
        search_paths = [
            self.skills_dir,
            "usr/skills",
            "python/skills",
        ]
        
        for search_path in search_paths:
            if not os.path.exists(search_path):
                continue
            
            for root, dirs, files in os.walk(search_path):
                # Skip hidden folders
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                
                if "SKILL.md" in files:
                    skill_path = os.path.join(root, "SKILL.md")
                    skill = self._parse_skill(skill_path)
                    if skill:
                        self.skills.append(skill)
    
    def _parse_skill(self, filepath: str) -> Optional[Skill]:
        """Parse a SKILL.md file"""
        try:
            with open(filepath, 'r') as f:
                content = f.read()
            
            # Split frontmatter and content
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    frontmatter = parts[1]
                    skill_content = parts[2].strip()
                    
                    # Parse YAML frontmatter
                    meta = yaml.safe_load(frontmatter)
                    
                    if meta:
                        return Skill(
                            name=meta.get("name", ""),
                            description=meta.get("description", ""),
                            path=Path(filepath),
                            version=meta.get("version", ""),
                            author=meta.get("author", ""),
                            tags=meta.get("tags", []),
                            trigger_patterns=meta.get("trigger_patterns", []),
                            allowed_tools=meta.get("allowed_tools", []),
                            content=skill_content
                        )
        except Exception as e:
            print(f"Error parsing skill {filepath}: {e}")
        
        return None
    
    def list_skills(self) -> List[Skill]:
        """List all available skills"""
        return self.skills
    
    def find_skill(self, name: str) -> Optional[Skill]:
        """Find a skill by name"""
        for skill in self.skills:
            if skill.name.lower() == name.lower():
                return skill
        return None
    
    def find_by_trigger(self, query: str) -> List[Skill]:
        """Find skills matching a trigger pattern"""
        query_lower = query.lower()
        matches = []
        
        for skill in self.skills:
            for pattern in skill.trigger_patterns:
                if pattern.lower() in query_lower:
                    matches.append(skill)
                    break
        
        return matches
    
    def load_skill(self, name: str) -> Optional[str]:
        """Load a skill's content into context"""
        skill = self.find_skill(name)
        if skill:
            if skill.name not in self.loaded_skills:
                self.loaded_skills.append(skill.name)
            return skill.content
        return None
    
    def unload_skill(self, name: str):
        """Unload a skill"""
        if name in self.loaded_skills:
            self.loaded_skills.remove(name)
    
    def get_loaded(self) -> List[str]:
        """Get list of loaded skill names"""
        return self.loaded_skills.copy()
    
    def get_context(self) -> str:
        """Get context string for all loaded skills"""
        if not self.loaded_skills:
            return ""
        
        lines = ["## Active Skills"]
        for skill_name in self.loaded_skills:
            skill = self.find_skill(skill_name)
            if skill:
                lines.append(f"\n### {skill.name}")
                lines.append(f"{skill.description}\n")
                lines.append(skill.content)
        
        return "\n".join(lines)


# Example SKILL.md format for reference
SKILL_TEMPLATE = """---
name: "example-skill"
description: "What this skill does and when to use it"
version: "1.0.0"
author: "Your Name"
tags: ["category", "example"]
trigger_patterns:
  - "trigger phrase"
  - "keywords"
allowed_tools:
  - "code_execution"
  - "memory"
---

# Example Skill

## When to Use
Describe when this skill should be activated...

## Instructions
Step-by-step instructions for the agent...

## Examples
Example interactions...
"""


if __name__ == "__main__":
    # Test
    mgr = SkillsManager()
    
    print(f"Found {len(mgr.skills)} skills:")
    for skill in mgr.skills:
        print(f"  - {skill.name}: {skill.description}")
    
    # Test loading
    if mgr.skills:
        first = mgr.skills[0]
        content = mgr.load_skill(first.name)
        print(f"\nLoaded '{first.name}': {len(content)} chars")
