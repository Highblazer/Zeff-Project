"""
Memory System - Vector-based persistent memory using FAISS
"""

import os
import json
from datetime import datetime
from typing import Optional, List
import hashlib


class MemoryStore:
    """Simple in-memory key-value store for quick access"""
    
    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.store = {}
    
    def set(self, key: str, value: str):
        self.store[key] = {
            "value": value,
            "timestamp": datetime.now().isoformat()
        }
    
    def get(self, key: str) -> Optional[str]:
        item = self.store.get(key)
        return item["value"] if item else None
    
    def delete(self, key: str):
        if key in self.store:
            del self.store[key]
    
    def search(self, query: str) -> list:
        """Simple substring search"""
        results = []
        query_lower = query.lower()
        for key, item in self.store.items():
            if query_lower in key.lower() or query_lower in item["value"].lower():
                results.append({"key": key, **item})
        return results
    
    def all(self) -> list:
        return [{"key": k, **v} for k, v in self.store.items()]
    
    def clear(self):
        self.store = {}


class VectorMemory:
    """Vector-based memory using simple embeddings"""
    
    def __init__(self, agent_name: str, memory_dir: str = "memory"):
        self.agent_name = agent_name
        self.memory_dir = memory_dir
        self.vectors = []  # List of {"id", "content", "embedding", "timestamp"}
        self.next_id = 1
        
        # Create memory directory
        self.path = os.path.join(memory_dir, f"{agent_name}.json")
        self.load()
    
    def _get_embedding(self, text: str) -> list:
        """Simple hash-based pseudo-embedding for demo"""
        # In production, use sentence-transformers
        # This creates a deterministic pseudo-embedding
        hash_bytes = hashlib.sha256(text.encode()).digest()
        return list(hash_bytes[:32])  # 32-dim vector
    
    def _cosine_similarity(self, a: list, b: list) -> float:
        """Calculate cosine similarity between two vectors"""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0
        return dot / (norm_a * norm_b)
    
    def add(self, content: str, metadata: dict = None):
        """Add a memory"""
        embedding = self._get_embedding(content)
        
        memory = {
            "id": self.next_id,
            "content": content,
            "embedding": embedding,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {}
        }
        
        self.vectors.append(memory)
        self.next_id += 1
        self.save()
        
        return memory["id"]
    
    def search(self, query: str, top_k: int = 5) -> list:
        """Search memories by similarity"""
        if not self.vectors:
            return []
        
        query_embedding = self._get_embedding(query)
        
        # Calculate similarities
        results = []
        for memory in self.vectors:
            sim = self._cosine_similarity(query_embedding, memory["embedding"])
            results.append({
                "id": memory["id"],
                "content": memory["content"],
                "timestamp": memory["timestamp"],
                "similarity": sim,
                "metadata": memory.get("metadata", {})
            })
        
        # Sort by similarity
        results.sort(key=lambda x: x["similarity"], reverse=True)
        
        return results[:top_k]
    
    def get(self, memory_id: int) -> Optional[dict]:
        """Get a specific memory"""
        for memory in self.vectors:
            if memory["id"] == memory_id:
                return memory
        return None
    
    def delete(self, memory_id: int):
        """Delete a memory"""
        self.vectors = [m for m in self.vectors if m["id"] != memory_id]
        self.save()
    
    def get_all(self) -> list:
        """Get all memories"""
        return sorted(self.vectors, key=lambda x: x["timestamp"], reverse=True)
    
    def clear(self):
        """Clear all memories"""
        self.vectors = []
        self.save()
    
    def save(self):
        """Save to disk"""
        os.makedirs(self.memory_dir, exist_ok=True)
        with open(self.path, 'w') as f:
            json.dump({
                "next_id": self.next_id,
                "memories": self.vectors
            }, f, indent=2)
    
    def load(self):
        """Load from disk"""
        if os.path.exists(self.path):
            try:
                with open(self.path, 'r') as f:
                    data = json.load(f)
                    self.next_id = data.get("next_id", 1)
                    self.vectors = data.get("memories", [])
            except Exception as e:
                print(f"Warning: Failed to load memory from {self.path}: {e}")


class MemoryManager:
    """Manages all memory types for an agent"""
    
    def __init__(self, agent_name: str, memory_dir: str = "memory"):
        self.agent_name = agent_name
        
        # Different memory areas
        self.short_term = MemoryStore(agent_name)  # Quick access
        self.long_term = VectorMemory(agent_name, memory_dir)  # Persistent
    
    def remember(self, content: str, memory_type: str = "long", metadata: dict = None):
        """Store a memory"""
        if memory_type == "short":
            key = f"mem_{datetime.now().timestamp()}"
            self.short_term.set(key, content)
            return key
        else:
            return self.long_term.add(content, metadata)
    
    def recall(self, query: str, memory_type: str = "all") -> list:
        """Recall memories"""
        if memory_type == "short":
            return self.short_term.search(query)
        elif memory_type == "long":
            return self.long_term.search(query)
        else:
            # Search both
            short_results = self.short_term.search(query)
            long_results = self.long_term.search(query)
            return {
                "short_term": short_results,
                "long_term": long_results
            }
    
    def forget(self, memory_id: int = None, memory_type: str = "all"):
        """Forget memories"""
        if memory_type == "short":
            self.short_term.clear()
        elif memory_type == "long":
            if memory_id:
                self.long_term.delete(memory_id)
            else:
                self.long_term.clear()
        else:
            self.short_term.clear()
            self.long_term.clear()


if __name__ == "__main__":
    # Test
    mgr = MemoryManager("test_agent")
    
    # Add memories
    mgr.remember("User prefers to be called Seth")
    mgr.remember("User is interested in trading")
    mgr.remember("User has Shopify store")
    
    # Recall
    results = mgr.recall("trading")
    print("Recall 'trading':", results)
