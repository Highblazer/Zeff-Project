"""
Binary Rogue Agent Models Module
LLM provider management using LiteLLM
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
import os

import litellm
from litellm import completion, acompletion

# Load environment
from python.helpers.dotenv import load_dotenv
load_dotenv()

litellm.modify_params = True


class ModelProvider(Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    OLLAMA = "ollama"
    MINIMAX = "minimax"
    LITELLM = "litellm"


@dataclass
class ModelConfig:
    provider: str
    name: str
    api_base: str = ""
    api_key: str = ""
    ctx_length: int = 128000
    max_tokens: int = 8192
    vision: bool = False
    reasoning: bool = False
    temperature: float = 0.7
    kwargs: dict = field(default_factory=dict)


class ChatModel:
    """Unified chat model interface"""
    
    def __init__(self, config: ModelConfig):
        self.config = config
        self.provider = config.provider
        self.model = config.name
    
    def complete(
        self,
        messages: list[dict],
        temperature: float = None,
        max_tokens: int = None,
        **kwargs
    ) -> tuple[str, str]:
        """Synchronous completion - returns (response, reasoning)"""
        
        params = {
            "model": f"{self.provider}/{self.model}",
            "messages": messages,
            "temperature": temperature or self.config.temperature,
            "max_tokens": max_tokens or self.config.max_tokens,
            **self.config.kwargs,
            **kwargs
        }
        
        if self.config.api_key:
            params["api_key"] = self.config.api_key
        if self.config.api_base:
            params["api_base"] = self.config.api_base
        
        response = completion(**params)
        
        # Extract response and reasoning
        reasoning = ""
        if hasattr(response, 'usage') and hasattr(response.usage, 'completion_tokens_details'):
            reasoning = getattr(response.usage.completion_tokens_details, 'reasoning_tokens', "")
        
        content = response.choices[0].message.content
        return content, reasoning
    
    async def acomplete(
        self,
        messages: list[dict],
        temperature: float = None,
        max_tokens: int = None,
        stream_callback=None,
        **kwargs
    ) -> tuple[str, str]:
        """Async completion with streaming"""
        
        params = {
            "model": f"{self.provider}/{self.model}",
            "messages": messages,
            "temperature": temperature or self.config.temperature,
            "max_tokens": max_tokens or self.config.max_tokens,
            **self.config.kwargs,
            **kwargs
        }
        
        if self.config.api_key:
            params["api_key"] = self.config.api_key
        if self.config.api_base:
            params["api_base"] = self.config.api_base
        
        response = await acompletion(**params)
        
        content = response.choices[0].message.content
        reasoning = ""
        
        return content, reasoning


# Default model configurations
DEFAULT_MODELS = {
    "minimax": ModelConfig(
        provider="minimax",
        name="MiniMax-M2.5",
        api_base="https://api.minimax.io/anthropic",
        ctx_length=200000,
        reasoning=True,
    ),
    "openai": ModelConfig(
        provider="openai",
        name="gpt-4o",
        ctx_length=128000,
        vision=True,
    ),
    "anthropic": ModelConfig(
        provider="anthropic",
        name="claude-sonnet-4-20250514",
        ctx_length=200000,
        reasoning=True,
    ),
    "ollama": ModelConfig(
        provider="ollama",
        name="llama3",
        api_base="http://localhost:11434",
        ctx_length=8192,
    ),
}


def get_model(name: str = "minimax") -> ChatModel:
    """Get a model instance by name"""
    config = DEFAULT_MODELS.get(name, DEFAULT_MODELS["minimax"])
    return ChatModel(config)


__all__ = [
    "ModelProvider",
    "ModelConfig", 
    "ChatModel",
    "get_model",
    "DEFAULT_MODELS",
]
