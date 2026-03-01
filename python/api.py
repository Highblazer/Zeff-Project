#!/usr/bin/env python3
"""
API Server — redirects legacy endpoints to the new FastAPI Signal Service.

Legacy endpoints (port 8080) are preserved for backward compatibility.
New Signal API runs on port 8000 via signal_api.py (FastAPI + uvicorn).

To run the new API: python signal_api.py  (port 8000, auto-docs at /docs)
To run this legacy: python api.py         (port 8080, simple HTTP)
"""

import json
import os
from http.server import HTTPServer, SimpleHTTPRequestHandler
from datetime import datetime


ALLOWED_ORIGINS = ['http://localhost:8501', 'http://127.0.0.1:8501', 'http://localhost:8502']

SIGNAL_API_URL = "http://localhost:8000"


class APIHandler(SimpleHTTPRequestHandler):
    """Custom handler with API endpoints + redirect notice for new endpoints."""

    def _send_cors_headers(self):
        origin = self.headers.get('Origin', '')
        if origin in ALLOWED_ORIGINS:
            self.send_header('Access-Control-Allow-Origin', origin)
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-API-Key')

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        # Legacy endpoints — preserved for dashboard compatibility
        if self.path == '/api/tools':
            self._json_response(self.get_tools())

        elif self.path == '/api/status':
            self._json_response(self.get_system_status())

        elif self.path == '/api/agents':
            self._json_response(self.get_agents())

        # Redirect to new Signal API for signal-related endpoints
        elif self.path.startswith('/api/signals') or self.path.startswith('/api/news') or self.path.startswith('/api/stats'):
            self.send_response(301)
            self.send_header('Location', f'{SIGNAL_API_URL}{self.path}')
            self.send_header('Content-type', 'application/json')
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps({
                "redirect": f"{SIGNAL_API_URL}{self.path}",
                "message": "This endpoint has moved to the Signal API on port 8000. See /docs for documentation.",
            }).encode())

        elif self.path == '/':
            self._json_response({
                "service": "OpenClaw API Gateway",
                "legacy_endpoints": ["/api/tools", "/api/status", "/api/agents"],
                "signal_api": f"{SIGNAL_API_URL}/docs",
                "copy_trade_ws": "ws://localhost:8765",
                "public_dashboard": "http://localhost:8502",
            })

        else:
            self.send_response(404)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Not found"}).encode())

    def _json_response(self, data):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

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
            {"id": "003", "name": "TradeBot", "role": "CTO", "status": "running"},
            {"id": "004", "name": "Natalia", "role": "CRO", "status": "running"},
            {"id": "005", "name": "Ali.bot", "role": "CTS", "status": "running"},
            {"id": "006", "name": "Kalshi Bot", "role": "Prediction Markets", "status": "paper"},
            {"id": "007", "name": "Polymarket Bot", "role": "Prediction Markets", "status": "paper"},
            {"id": "008", "name": "Poly.Bot", "role": "CPO — Chief Prediction Officer", "status": "running"},
        ]

    def log_message(self, format, *args):
        pass


def run_server(port=8080):
    """Run the API server - bound to localhost only"""
    server = HTTPServer(('127.0.0.1', port), APIHandler)
    print(f"OpenClaw API Gateway running on 127.0.0.1:{port}")
    print(f"Signal API: {SIGNAL_API_URL}/docs")
    print(f"Copy-Trade WS: ws://localhost:8765")
    server.serve_forever()


if __name__ == '__main__':
    run_server()
