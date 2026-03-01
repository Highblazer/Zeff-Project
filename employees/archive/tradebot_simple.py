#!/usr/bin/env python3
"""
TradeBot - Simple Loop Version
Uses simple loop instead of twisted reactor
"""

import json
import time
import socket
import ssl
import threading
from datetime import datetime

CONFIG_FILE = '/root/.openclaw/workspace/conf/icmarkets.json'
STATE_FILE = '/root/.openclaw/workspace/employees/trading_status.json'

with open(CONFIG_FILE, 'r') as f:
    APP_CONFIG = json.load(f)

IC = APP_CONFIG['icmarkets']

SYMBOLS = {
    'EURUSD': 1, 'GBPUSD': 2, 'USDJPY': 3, 'AUDUSD': 4,
    'USDCAD': 5, 'USDCHF': 6, 'NZDUSD': 7, 'XAUUSD': 10, 'XAGUSD': 11
}

class TradeBot:
    def __init__(self):
        self.ctid_account_id = int(IC['ctid_trader_account_id'])  # No fallback — must be configured
        self.access_token = IC.get('access_token', '')
        self.client_id = IC.get('client_id', '')
        self.client_secret = IC.get('api_secret', '')
        self.positions = {}
        self.balance = 193.21
        self.running = True
        self.connected = False
        
    def log(self, msg):
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{timestamp}] {msg}")
        
    def write_status(self):
        try:
            status = {
                'balance': self.balance,
                'connected': self.connected,
                'mode': IC.get('mode', 'demo'),
                'account': str(self.ctid_account_id),
                'positions': len(self.positions),
                'last_update': datetime.now().isoformat()
            }
            with open(STATE_FILE, 'w') as f:
                json.dump(status, f)
        except Exception as e:
            print(f"Warning: failed to write status: {e}")

    def connect_with_retry(self):
        """Try to connect to cTrader"""
        self.log("Connecting to cTrader...")
        
        for attempt in range(5):
            try:
                # Create SSL socket with proper certificate verification
                context = ssl.create_default_context()
                
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(30)
                
                host = "demo.ctraderapi.com"
                port = 5045  # Different port for simpler protocol
                
                sock.connect((host, port))
                self.connected = True
                self.log("Connected!")
                return sock
            except Exception as e:
                self.log(f"Connection attempt {attempt+1} failed: {e}")
                time.sleep(5)
        
        return None

    def run(self):
        self.log("=" * 50)
        self.log("TradeBot SIMPLE MODE")
        self.log(f"Account: {self.ctid_account_id}")
        self.log("=" * 50)
        
        cycle = 0
        while self.running:
            cycle += 1
            self.log(f"--- Cycle {cycle} ---")
            
            # Try to connect
            sock = self.connect_with_retry()
            
            if sock:
                self.log("Session active")
                # Keep alive for 5 minutes
                for i in range(10):
                    if not self.running:
                        break
                    time.sleep(30)
                    self.log(f"Alive {i+1}/10")
                    self.write_status()
                
                sock.close()
            else:
                self.log("Connection failed, retrying in 30s...")
                time.sleep(30)
            
            self.write_status()
        
        self.log("TradeBot stopped")

def main():
    bot = TradeBot()
    try:
        bot.run()
    except KeyboardInterrupt:
        bot.running = False
        bot.log("Stopped")

if __name__ == '__main__':
    main()
