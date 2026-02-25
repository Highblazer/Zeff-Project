#!/usr/bin/env python3
"""
Simple API server for Binary Rogue Dashboard
"""

import json
import os
from http.server import HTTPServer, SimpleHTTPRequestHandler
from datetime import datetime


ALLOWED_ORIGINS = ['http://localhost:8501', 'http://127.0.0.1:8501']


class APIHandler(SimpleHTTPRequestHandler):
    """Custom handler with API endpoints"""

    def _send_cors_headers(self):
        origin = self.headers.get('Origin', '')
        if origin in ALLOWED_ORIGINS:
            self.send_header('Access-Control-Allow-Origin', origin)
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path == '/api/tools':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self._send_cors_headers()
            self.end_headers()

            tools = self.get_tools()
            self.wfile.write(json.dumps(tools).encode())

        elif self.path == '/api/status':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self._send_cors_headers()
            self.end_headers()

            status = self.get_system_status()
            self.wfile.write(json.dumps(status).encode())

        elif self.path == '/api/agents':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self._send_cors_headers()
            self.end_headers()

            agents = self.get_agents()
            self.wfile.write(json.dumps(agents).encode())

        else:
            # Block static file serving — do not expose workspace files
            self.send_response(404)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Not found"}).encode())

    def get_tools(self):
        """Get available tools"""
        return [
            {
                "name": "calculator",
                "description": "Perform mathematical calculations",
                "status": "available",
                "params": {"expression": "string (required)"}
            },
            {
                "name": "search",
                "description": "Search the web for information",
                "status": "available",
                "params": {"query": "string (required)", "count": "integer (optional)"}
            },
            {
                "name": "browser",
                "description": "Browse websites and extract content",
                "status": "available",
                "params": {"url": "string (required)", "action": "visit|extract"}
            },
            {
                "name": "memory",
                "description": "Save and retrieve persistent memories",
                "status": "available",
                "params": {"action": "save|recall|search", "content": "string"}
            },
            {
                "name": "scheduler",
                "description": "Schedule tasks to run later",
                "status": "available",
                "params": {"action": "add|list|remove", "task": "string", "delay_minutes": "integer"}
            },
            {
                "name": "output",
                "description": "Send response to user",
                "status": "available",
                "params": {"message": "string (required)", "type": "text|error|warning|success"}
            }
        ]

    def get_system_status(self):
        """Get system status"""
        try:
            with open('/proc/uptime') as f:
                uptime_seconds = float(f.read().split()[0])

            with open('/proc/meminfo') as f:
                meminfo = f.read()
            mem_total = int([l for l in meminfo.split('\n') if 'MemTotal' in l][0].split()[1]) / 1024
            mem_avail = int([l for l in meminfo.split('\n') if 'MemAvailable' in l][0].split()[1]) / 1024
            mem_pct = ((mem_total - mem_avail) / mem_total) * 100

            with open('/proc/loadavg') as f:
                load = f.read().split()[:3]

            return {
                "uptime_seconds": int(uptime_seconds),
                "uptime_human": f"{int(uptime_seconds // 3600)}h {int((uptime_seconds % 3600) // 60)}m",
                "memory_percent": round(mem_pct, 1),
                "load": load,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {"error": str(e)}

    def get_agents(self):
        """Get agent status"""
        return [
            {"id": "001", "name": "Zeff.bot", "role": "CEO", "status": "online"},
            {"id": "002", "name": "TradeBot", "role": "Trading", "status": "running"},
            {"id": "003", "name": "Natalia", "role": "Research", "status": "running"}
        ]

    def log_message(self, format, *args):
        pass


def run_server(port=8080):
    """Run the API server - bound to localhost only"""
    server = HTTPServer(('127.0.0.1', port), APIHandler)
    print(f"Binary Rogue API running on 127.0.0.1:{port}")
    server.serve_forever()


if __name__ == '__main__':
    run_server()
