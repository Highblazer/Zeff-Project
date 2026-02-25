"""
Scheduler Tool - Schedule tasks to run later
"""

from python.helpers.tools import Tool, Response
import json
import os
from datetime import datetime, timedelta


class Scheduler(Tool):
    """Schedule tasks to run later"""
    
    name = "scheduler"
    description = "Schedule tasks to run at specific times"
    parameters = {
        "action": {
            "type": "string",
            "description": "Action: add, list, remove",
            "required": True
        },
        "task": {
            "type": "string",
            "description": "Task description or command",
        },
        "delay_minutes": {
            "type": "integer",
            "description": "Minutes from now to run",
        },
        "task_id": {
            "type": "string",
            "description": "Task ID to remove",
        }
    }
    
    def __init__(self, agent):
        super().__init__(agent)
        self.tasks_file = "/root/.openclaw/workspace/scheduled_tasks.json"
        self._load_tasks()
    
    def _load_tasks(self):
        """Load tasks from file"""
        if os.path.exists(self.tasks_file):
            try:
                with open(self.tasks_file, 'r') as f:
                    self.tasks = json.load(f)
            except Exception as e:
                print(f"Warning: failed to load scheduled tasks: {e}")
                self.tasks = []
        else:
            self.tasks = []
    
    def _save_tasks(self):
        """Save tasks to file"""
        with open(self.tasks_file, 'w') as f:
            json.dump(self.tasks, f, indent=2)
    
    async def execute(self, **kwargs) -> Response:
        action = kwargs.get("action", "").lower()
        
        if action == "add":
            task = kwargs.get("task", "")
            delay = kwargs.get("delay_minutes", 60)
            
            if not task:
                return Response(
                    message="Error: No task provided",
                    break_loop=False
                )
            
            # Add task
            task_id = f"task_{len(self.tasks) + 1}"
            run_at = (datetime.now() + timedelta(minutes=delay)).isoformat()
            
            self.tasks.append({
                "id": task_id,
                "task": task,
                "run_at": run_at,
                "agent": self.agent.name if hasattr(self.agent, 'name') else "default",
                "created": datetime.now().isoformat()
            })
            
            self._save_tasks()
            
            return Response(
                message=f"✓ Task scheduled: '{task}' in {delay} minutes (ID: {task_id})",
                break_loop=False,
                data={"task_id": task_id, "run_at": run_at}
            )
        
        elif action == "list":
            if not self.tasks:
                return Response(
                    message="No scheduled tasks",
                    break_loop=False
                )
            
            now = datetime.now()
            formatted = []
            
            for t in self.tasks:
                run_at = datetime.fromisoformat(t["run_at"])
                status = "⏳" if run_at > now else "✅"
                formatted.append(f"{status} {t['id']}: {t['task']} (at {run_at.strftime('%H:%M')})")
            
            return Response(
                message="Scheduled tasks:\n\n" + "\n".join(formatted),
                break_loop=False,
                data={"tasks": self.tasks}
            )
        
        elif action == "remove":
            task_id = kwargs.get("task_id", "")
            
            if not task_id:
                return Response(
                    message="Error: No task_id provided",
                    break_loop=False
                )
            
            # Remove task
            self.tasks = [t for t in self.tasks if t["id"] != task_id]
            self._save_tasks()
            
            return Response(
                message=f"✓ Task removed: {task_id}",
                break_loop=False
            )
        
        else:
            return Response(
                message="Unknown action. Use: add, list, or remove",
                break_loop=False
            )


__all__ = ["Scheduler"]
