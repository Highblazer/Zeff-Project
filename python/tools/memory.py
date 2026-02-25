"""
Memory Tool - Save and retrieve memories
"""

from python.helpers.tools import Tool, Response


class Memory(Tool):
    """Store and retrieve memories"""
    
    name = "memory"
    description = "Save or retrieve information from memory"
    parameters = {
        "action": {
            "type": "string",
            "description": "Action: save, recall, or search",
            "required": True
        },
        "content": {
            "type": "string",
            "description": "Content to save or query to recall",
            "required": True
        }
    }
    
    def __init__(self, agent):
        super().__init__(agent)
        # Import memory manager
        try:
            from python.helpers.memory import MemoryManager
            self.memory = MemoryManager(agent.name)
        except Exception as e:
            print(f"Memory init error: {e}")
            self.memory = None
    
    async def execute(self, **kwargs) -> Response:
        if not self.memory:
            return Response(
                message="Error: Memory system not available",
                break_loop=False
            )
        
        action = kwargs.get("action", "").lower()
        content = kwargs.get("content", "")
        
        if not content:
            return Response(
                message="Error: No content provided",
                break_loop=False
            )
        
        try:
            if action == "save":
                # Save to memory (not async)
                memory_id = self.memory.remember(content, memory_type="long")
                return Response(
                    message=f"✓ Saved to memory: {content[:50]}...",
                    break_loop=False,
                    data={"memory_id": memory_id}
                )
            
            elif action == "recall" or action == "search":
                # Recall from memory (not async)
                results = self.memory.recall(content, memory_type="long")
                
                if not results:
                    return Response(
                        message=f"No memories found for: {content}",
                        break_loop=False
                    )
                
                formatted = []
                for r in results[:5]:
                    formatted.append(f"• {r['content'][:100]}...")
                
                return Response(
                    message="Memories found:\n\n" + "\n".join(formatted),
                    break_loop=False,
                    data={"results": results}
                )
            
            elif action == "forget":
                # Clear all memories
                self.memory.forget()
                return Response(
                    message="✓ All memories cleared",
                    break_loop=False
                )
            
            else:
                return Response(
                    message=f"Unknown action: {action}. Use: save, recall, or search",
                    break_loop=False
                )
                
        except Exception as e:
            return Response(
                message=f"Memory error: {str(e)}",
                break_loop=False
            )


__all__ = ["Memory"]
