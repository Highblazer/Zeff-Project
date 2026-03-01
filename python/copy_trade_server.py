#!/usr/bin/env python3
"""
Copy-Trade WebSocket Server — broadcasts trade events in real-time.

Subscribers connect via WebSocket and receive:
  OPEN:  {"event": "OPEN",  "symbol": "EURUSD", "direction": "BUY", "entry": 1.1234, "sl": 1.1220, "tp": 1.1276, "volume": 100000}
  CLOSE: {"event": "CLOSE", "symbol": "EURUSD", "pnl": 4.20, "reason": "TP hit"}
  AMEND: {"event": "AMEND", "symbol": "EURUSD", "sl": 1.1245, "trailing": true}
  TICK:  {"event": "TICK",  "positions": [...], "balance": 164.80}

Architecture:
  - Watches trading_state.json for changes (poll every 2s)
  - Detects new positions (OPEN), removed positions (CLOSE), SL changes (AMEND)
  - Broadcasts to all connected WebSocket clients
  - API key auth via first message after connect

Usage:
  python copy_trade_server.py
  wscat -c ws://localhost:8765 -x '{"auth": "demo-free-tier"}'
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, '/root/.openclaw/workspace')

try:
    import websockets
except ImportError:
    print("Install websockets: pip install websockets")
    sys.exit(1)

# ── Config ──
STATE_FILE = '/root/.openclaw/workspace/employees/trading_state.json'
API_KEYS_PATH = '/root/.openclaw/workspace/python/api_keys.json'
POLL_INTERVAL = 2  # seconds
HOST = '0.0.0.0'
PORT = 8765

# ── State ──
connected_clients: set = set()
authenticated_clients: dict = {}  # websocket -> key_info
_last_state: dict = {}
_last_positions: dict = {}


def load_api_keys() -> dict:
    try:
        with open(API_KEYS_PATH) as f:
            return json.load(f).get('keys', {})
    except Exception:
        return {}


def load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


async def broadcast(message: dict):
    """Send a JSON message to all authenticated clients."""
    if not authenticated_clients:
        return
    data = json.dumps(message)
    disconnected = set()
    for ws in list(authenticated_clients.keys()):
        try:
            await ws.send(data)
        except websockets.exceptions.ConnectionClosed:
            disconnected.add(ws)
    for ws in disconnected:
        authenticated_clients.pop(ws, None)
        connected_clients.discard(ws)


async def handler(websocket):
    """Handle a new WebSocket connection."""
    connected_clients.add(websocket)
    print(f"[WS] Client connected ({len(connected_clients)} total)")

    try:
        # Wait for auth message (timeout 30s)
        try:
            raw = await asyncio.wait_for(websocket.recv(), timeout=30)
            msg = json.loads(raw)
        except (asyncio.TimeoutError, json.JSONDecodeError):
            await websocket.close(4001, "Auth timeout or invalid JSON")
            return

        api_key = msg.get('auth') or msg.get('api_key')
        if not api_key:
            await websocket.close(4002, "Missing auth key")
            return

        keys = load_api_keys()
        if api_key not in keys:
            await websocket.close(4003, "Invalid API key")
            return

        key_info = keys[api_key]
        if not key_info.get('active', True):
            await websocket.close(4004, "API key deactivated")
            return

        authenticated_clients[websocket] = key_info
        print(f"[WS] Client authenticated (tier={key_info.get('tier', 'free')})")

        # Send current state snapshot
        state = load_state()
        await websocket.send(json.dumps({
            'event': 'SNAPSHOT',
            'positions': state.get('positions', {}),
            'stats': state.get('stats', {}),
            'mode': state.get('mode', 'demo'),
            'connected': state.get('connected', False),
        }))

        # Keep connection alive — listen for pings/messages
        async for message in websocket:
            # Client can send ping or close
            try:
                data = json.loads(message)
                if data.get('type') == 'ping':
                    await websocket.send(json.dumps({'type': 'pong'}))
            except json.JSONDecodeError:
                pass

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        connected_clients.discard(websocket)
        authenticated_clients.pop(websocket, None)
        print(f"[WS] Client disconnected ({len(connected_clients)} remaining)")


async def state_monitor():
    """Poll trading_state.json and detect changes to broadcast."""
    global _last_state, _last_positions

    while True:
        await asyncio.sleep(POLL_INTERVAL)

        if not authenticated_clients:
            continue

        state = load_state()
        if not state:
            continue

        positions = state.get('positions', {})

        # Detect new positions (OPEN events)
        for key, pos in positions.items():
            sym = key.split('_')[0] if '_' in key else key
            if key not in _last_positions:
                await broadcast({
                    'event': 'OPEN',
                    'symbol': sym,
                    'direction': pos.get('direction', '?'),
                    'entry': pos.get('entry_price', 0),
                    'sl': pos.get('stop_loss', 0),
                    'tp': pos.get('take_profit', 0),
                    'volume': pos.get('lot_size', 0),
                    'trail_phase': pos.get('trail_phase', 'initial'),
                    'timestamp': pos.get('open_time', ''),
                })

        # Detect closed positions (CLOSE events)
        for key, pos in _last_positions.items():
            if key not in positions:
                sym = key.split('_')[0] if '_' in key else key
                await broadcast({
                    'event': 'CLOSE',
                    'symbol': sym,
                    'direction': pos.get('direction', '?'),
                    'entry': pos.get('entry_price', 0),
                    'reason': 'Position closed',
                })

        # Detect SL/TP amendments (AMEND events)
        for key, pos in positions.items():
            if key in _last_positions:
                old = _last_positions[key]
                sl_changed = pos.get('stop_loss') != old.get('stop_loss')
                tp_changed = pos.get('take_profit') != old.get('take_profit')
                if sl_changed or tp_changed:
                    sym = key.split('_')[0] if '_' in key else key
                    await broadcast({
                        'event': 'AMEND',
                        'symbol': sym,
                        'sl': pos.get('stop_loss', 0),
                        'tp': pos.get('take_profit', 0),
                        'trailing': pos.get('trail_activated', False),
                        'trail_phase': pos.get('trail_phase', ''),
                    })

        # Periodic tick (every poll) with summary
        await broadcast({
            'event': 'TICK',
            'open_positions': len(positions),
            'balance': state.get('stats', {}).get('balance'),
            'connected': state.get('connected', False),
            'last_update': state.get('last_update'),
        })

        _last_positions = dict(positions)
        _last_state = state


async def main():
    print(f"Copy-Trade WebSocket Server starting on {HOST}:{PORT}")
    print(f"Monitoring: {STATE_FILE}")

    # Initialize state
    global _last_state, _last_positions
    _last_state = load_state()
    _last_positions = dict(_last_state.get('positions', {}))

    async with websockets.serve(handler, HOST, PORT):
        print(f"WebSocket server running on ws://{HOST}:{PORT}")
        await state_monitor()


if __name__ == '__main__':
    asyncio.run(main())
