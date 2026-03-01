#!/usr/bin/env python3
"""
TradeBot - IC Markets REST API (Stable Version)
Uses cURL for reliable connectivity
"""

import json
import os
import time
import signal
import subprocess
import sys
from datetime import datetime

CONFIG_FILE = '/root/.openclaw/workspace/conf/icmarkets.json'

with open(CONFIG_FILE, 'r') as f:
    APP_CONFIG = json.load(f)

IC = APP_CONFIG['icmarkets']

# Trading pairs
SYMBOLS = {
    'EURUSD': {'id': 1, 'name': 'EUR/USD'},
    'GBPUSD': {'id': 2, 'name': 'GBP/USD'},
    'USDJPY': {'id': 3, 'name': 'USD/JPY'},
    'AUDUSD': {'id': 4, 'name': 'AUD/USD'},
    'USDCAD': {'id': 5, 'name': 'USD/CAD'},
    'USDCHF': {'id': 6, 'name': 'USD/CHF'},
    'NZDUSD': {'id': 7, 'name': 'NZD/USD'},
    'XAUUSD': {'id': 10, 'name': 'Gold'},
    'XAGUSD': {'id': 11, 'name': 'Silver'},
}

# API Endpoints (Demo)
BASE_URL = "https://demo-api.icmarkets.com"

class TradeBot:
    def __init__(self):
        self.ctid_account_id = IC['ctid_trader_account_id']  # No fallback — must be configured
        self.access_token = IC.get('access_token', '')
        self.refresh_token = IC.get('refresh_token', '')
        self.client_id = IC.get('client_id', '')
        self.client_secret = IC.get('api_secret', '')
        self.balance = 193.21
        self.positions = {}
        self.prices = {}
        self.running = True
        self.authenticated = False
        
    def curl(self, endpoint, method="GET", data=None):
        """Make cURL request to IC Markets API"""
        headers = [
            f"Authorization: Bearer {self.access_token}",
            "Content-Type: application/json"
        ]
        
        cmd = ["curl", "-s", "-X", method]
        for h in headers:
            cmd.extend(["-H", h])
        
        if data:
            cmd.extend(["-d", json.dumps(data)])
        
        cmd.append(f"{BASE_URL}{endpoint}")
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.stdout
    
    def authenticate(self):
        """Refresh authentication token"""
        print("Authenticating with IC Markets...")
        
        data = {
            "refreshToken": self.refresh_token,
            "clientId": self.client_id,
            "clientSecret": self.client_secret
        }
        
        result = self.curl("/ca/authentication/refresh", "POST", data)
        
        try:
            resp = json.loads(result)
            if 'accessToken' in resp:
                self.access_token = resp['accessToken']
                if 'refreshToken' in resp:
                    self.refresh_token = resp['refreshToken']
                self.authenticated = True
                print("✅ Authenticated successfully")
                return True
            else:
                print(f"Auth failed: {result}")
                return False
        except Exception as e:
            print(f"Auth error (parse failure: {e}): {result}")
            return False
    
    def get_positions(self):
        """Get open positions"""
        if not self.authenticated:
            self.authenticate()
        
        result = self.curl(f"/ca/position/positions?accountId={self.ctid_account_id}")
        
        try:
            resp = json.loads(result)
            positions = resp.get('positions', [])
            self.positions = {}
            for pos in positions:
                symbol_id = pos.get('symbolId')
                for sym, info in SYMBOLS.items():
                    if info['id'] == symbol_id:
                        self.positions[sym] = {
                            'volume': pos.get('volume', 0) / 100000,
                            'direction': 'BUY' if pos.get('buySide', 0) > 0 else 'SELL',
                            'entry': pos.get('openPrice', 0)
                        }
            return len(self.positions)
        except Exception as e:
            print(f"Positions error: {e}")
            return 0
    
    def get_prices(self):
        """Get live prices for all symbols"""
        # Use Yahoo Finance as backup for prices
        import requests
        
        symbols = ['EURUSD=X', 'GBPUSD=X', 'USDJPY=X', 'XAUUSD=X']
        
        for sym in symbols:
            yahoo_sym = sym.replace('XAUUSD=X', 'GC=F')  # Gold futures
            try:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
                resp = requests.get(url, timeout=5)
                data = resp.json()
                if 'chart' in data and 'result' in data['chart']:
                    price = data['chart']['result'][0]['meta']['regularMarketPrice']
                    forex_sym = sym.replace('=X', '').replace('GC=F', 'XAUUSD')
                    self.prices[forex_sym] = price
            except Exception as e:
                print(f"Warning: failed to fetch price for {sym}: {e}")

        return len(self.prices)
    
    def execute_trade(self, symbol, direction, volume):
        """Execute a trade"""
        if not self.authenticated:
            if not self.authenticate():
                return False, "Auth failed"
        
        sym_id = SYMBOLS.get(symbol, {}).get('id')
        if not sym_id:
            return False, "Invalid symbol"
        
        side = 1 if direction.upper() == "BUY" else 2
        
        data = {
            "accountId": self.ctid_account_id,
            "symbolId": sym_id,
            "volume": int(volume * 100000),
            "side": side,
            "type": 1,  # Market order
            "positionMode": 0
        }
        
        result = self.curl("/ca/order", "POST", data)
        
        try:
            resp = json.loads(result)
            if 'orderId' in resp:
                return True, f"Order {resp['orderId']} executed"
            else:
                return False, result
        except Exception as e:
            print(f"Warning: failed to parse trade response: {e}")
            return False, result
    
    def run(self):
        """Main trading loop"""
        print("=" * 50)
        print("TradeBot - IC Markets REST API")
        print("=" * 50)
        print(f"Account: {IC['account_id']}")
        print(f"Account ID: {self.ctid_account_id}")
        print(f"Mode: {IC.get('mode', 'demo')}")
        print("-" * 50)
        
        # Initial auth
        self.authenticate()
        
        cycle = 0
        while self.running:
            cycle += 1
            print(f"\n--- Cycle {cycle} | {datetime.now().strftime('%H:%M:%S')} ---")
            
            # Get positions
            pos_count = self.get_positions()
            print(f"Positions: {pos_count}")
            
            # Get prices
            price_count = self.get_prices()
            print(f"Prices: {self.prices}")
            
            # Check balance
            print(f"Balance: ${self.balance}")
            
            # Wait before next cycle
            time.sleep(60)
    
    def stop(self):
        self.running = False

def main():
    bot = TradeBot()
    
    def signal_handler(sig, frame):
        print("\nShutting down...")
        bot.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    bot.run()

if __name__ == '__main__':
    main()
