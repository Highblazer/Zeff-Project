#!/usr/bin/env python3
"""
TradeBot - Ultra Robust Version
24/5 operation with auto-reconnect and persistence
"""

import json
import time
import signal
import sys
import os
from datetime import datetime
from twisted.internet import reactor
from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq, ProtoOAAccountAuthReq,
    ProtoOANewOrderReq, ProtoOAReconcileReq
)

CONFIG_FILE = '/root/.openclaw/workspace/conf/icmarkets.json'
STATE_FILE = '/root/.openclaw/workspace/employees/trading_status.json'

# Load config
with open(CONFIG_FILE, 'r') as f:
    APP_CONFIG = json.load(f)

IC = APP_CONFIG['icmarkets']

SYMBOLS = {
    'EURUSD': {'symbol_id': 1}, 'GBPUSD': {'symbol_id': 2},
    'USDJPY': {'symbol_id': 3}, 'AUDUSD': {'symbol_id': 4},
    'USDCAD': {'symbol_id': 5}, 'USDCHF': {'symbol_id': 6},
    'NZDUSD': {'symbol_id': 7}, 'XAUUSD': {'symbol_id': 10},
    'XAGUSD': {'symbol_id': 11},
}

class TradeBot:
    def __init__(self):
        self.client = None
        self.ctid_account_id = int(IC['ctid_trader_account_id'])  # No fallback — must be configured
        self.access_token = IC.get('access_token', '')
        self.client_id = IC.get('client_id', '')
        self.client_secret = IC.get('api_secret', '')
        self.positions = {}
        self.balance = 193.21
        self.authenticated = False
        self.running = True
        self.reconnect_delay = 5
        self.max_reconnect_delay = 60
        self.cycle_count = 0
        self.last_status_time = 0
        
    def log(self, msg):
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{timestamp}] {msg}")
        self.write_status()
        
    def write_status(self):
        """Write status to file"""
        try:
            status = {
                'balance': self.balance,
                'connected': self.authenticated,
                'mode': IC.get('mode', 'demo'),
                'account': str(self.ctid_account_id),
                'positions': len(self.positions),
                'cycles': self.cycle_count,
                'last_update': datetime.now().isoformat()
            }
            with open(STATE_FILE, 'w') as f:
                json.dump(status, f)
        except Exception as e:
            print(f"Warning: failed to write status: {e}")

    def start(self):
        self.log("=" * 50)
        self.log("TradeBot STARTING - Ultra Robust Mode")
        self.log(f"Account: {self.ctid_account_id}")
        self.log(f"Mode: {IC.get('mode', 'demo')}")
        self.log("=" * 50)
        
        # Set up signal handlers
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        self.connect()
        
        # Keep reactor running
        reactor.run(installSignalHandlers=False)

    def connect(self):
        """Connect to cTrader"""
        self.log(f"Connecting to {EndPoints.PROTOBUF_DEMO_HOST}...")
        
        try:
            self.client = Client(EndPoints.PROTOBUF_DEMO_HOST, EndPoints.PROTOBUF_PORT, TcpProtocol)
            self.client.setConnectedCallback(self.on_connected)
            self.client.setDisconnectedCallback(self.on_disconnected)
            self.client.startService()
        except Exception as e:
            self.log(f"Connection error: {e}")
            self.schedule_reconnect()

    def on_connected(self, client):
        self.log("✅ Connected!")
        self._authenticate()

    def _authenticate(self):
        req = ProtoOAApplicationAuthReq()
        req.clientId = self.client_id
        req.clientSecret = self.client_secret
        d = self.client.send(req)
        d.addCallbacks(self.on_app_auth, self.on_error)

    def on_app_auth(self, response):
        self.log("✅ App authenticated")
        self.authenticated = True
        self.reconnect_delay = 5  # Reset delay
        
        req = ProtoOAAccountAuthReq()
        req.accessToken = self.access_token
        req.ctidTraderAccountId = self.ctid_account_id
        d = self.client.send(req)
        d.addCallbacks(self.on_account_auth, self.on_error)

    def on_account_auth(self, response):
        self.log(f"✅ Account authenticated: {self.ctid_account_id}")
        self.log("🚀 READY TO TRADE!")
        
        # Get initial positions and balance
        self.get_positions()
        self.get_balance()
        
        # Start trading loop
        self.trading_loop()

    def get_balance(self):
        """Get account balance"""
        req = ProtoOAReconcileReq()
        req.ctidTraderAccountId = self.ctid_account_id
        d = self.client.send(req)
        d.addCallbacks(self.on_balance, lambda f: None)

    def on_balance(self, response):
        try:
            data = Protobuf.extract(response)
            if 'accountInformation' in data:
                self.balance = data['accountInformation'].get('balance', self.balance) / 10000
                self.log(f"Balance: ${self.balance}")
        except Exception as e:
            print(f"Warning: failed to parse balance: {e}")

    def get_positions(self):
        req = ProtoOAReconcileReq()
        req.ctidTraderAccountId = self.ctid_account_id
        d = self.client.send(req)
        d.addCallbacks(self.on_reconcile, lambda f: None)

    def on_reconcile(self, response):
        try:
            data = Protobuf.extract(response)
            self.positions = {}
            if 'position' in data:
                for pos in data['position']:
                    symbol_id = pos.get('symbolId')
                    volume = pos.get('volume', 0) / 100000
                    if volume > 0:
                        for sym, info in SYMBOLS.items():
                            if info['symbol_id'] == symbol_id:
                                self.positions[sym] = {
                                    'volume': volume,
                                    'side': 'BUY' if pos.get('buySide', 0) > 0 else 'SELL'
                                }
            self.log(f"Positions: {len(self.positions)}")
        except Exception as e:
            print(f"Warning: failed to reconcile positions: {e}")

    def trading_loop(self):
        if not self.running:
            return
            
        self.cycle_count += 1
        self.log(f"--- Cycle {self.cycle_count} | Pos: {len(self.positions)} | Bal: ${self.balance:.2f} ---")
        
        # Refresh data
        self.get_positions()
        self.get_balance()
        
        # Write status
        self.write_status()
        
        # Schedule next cycle (30 seconds)
        reactor.callLater(30, self.trading_loop)

    def execute_trade(self, symbol, direction, volume):
        if not self.authenticated:
            self.log("Not authenticated, cannot trade")
            return False
            
        sym_id = SYMBOLS.get(symbol, {}).get('symbol_id')
        if not sym_id:
            return False
        
        side = 1 if direction.upper() == 'BUY' else 2
        
        req = ProtoOANewOrderReq()
        req.symbolId = sym_id
        req.volume = int(volume * 100000)
        req.side = side
        req.type = 1
        req.ctidTraderAccountId = self.ctid_account_id
        
        d = self.client.send(req)
        d.addCallbacks(
            lambda r: self.log(f"✅ TRADE: {direction} {volume} {symbol}"),
            lambda f: self.log(f"❌ Trade failed: {f}")
        )
        return True

    def on_disconnected(self, client, reason):
        self.log(f"⚠️ Disconnected: {reason}")
        self.authenticated = False
        if self.running:
            self.schedule_reconnect()

    def schedule_reconnect(self):
        self.log(f"Reconnecting in {self.reconnect_delay}s...")
        reactor.callLater(self.reconnect_delay, self.reconnect)
        # Exponential backoff
        self.reconnect_delay = min(self.reconnect_delay * 2, self.max_reconnect_delay)

    def reconnect(self):
        if not self.running:
            return
        self.log("Attempting reconnect...")
        self.connect()

    def on_error(self, failure):
        self.log(f"Error: {failure}")

    def signal_handler(self, signum, frame):
        self.log("Shutting down...")
        self.running = False
        reactor.stop()
        sys.exit(0)

def main():
    bot = TradeBot()
    bot.start()

if __name__ == '__main__':
    main()
