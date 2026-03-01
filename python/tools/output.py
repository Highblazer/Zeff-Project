"""
Output Tool - Send response to user
"""

from python.helpers.tools import Tool, Response


class Output(Tool):
    """Send output to the user"""
    
    name = "output"
    description = "Send a message or response to the user"
    parameters = {
        "message": {
            "type": "string",
            "description": "Message to send to user",
            "required": True
        },
        "type": {
            "type": "string",
            "description": "Type of message (text, error, warning, success)",
            "default": "text"
        }
    }
    
    async def execute(self, **kwargs) -> Response:
        message = kwargs.get("message", "")
        msg_type = kwargs.get("type", "text")
        
        if not message:
            return Response(message="Error: No message provided", break_loop=False)
        
        # Format based on type
        if msg_type == "error":
            formatted = f"❌ Error: {message}"
        elif msg_type == "warning":
            formatted = f"⚠️ Warning: {message}"
        elif msg_type == "success":
            formatted = f"✅ Success: {message}"
        else:
            formatted = message
        
        return Response(
            message=formatted,
            break_loop=True,  # This ends the agent's turn
            data={"type": msg_type}
        )


__all__ = ["Output"]
