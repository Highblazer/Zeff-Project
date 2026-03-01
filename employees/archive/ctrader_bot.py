#!/usr/bin/env python3
"""
TradeBot - IC Markets cTrader Open API
Connects to demo account, fetches prices, executes trades
"""

import json
import os
import time
import signal
import sys
from datetime import datetime
from twisted.internet import reactor, defer
from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq, ProtoOAAccountAuthReq,
    ProtoOASymbolsListReq, ProtoOANewOrderReq,
    ProtoOAClosePositionReq, ProtoOAReconcileReq
)

# Config
CONFIG_FILE = '/root/.openclaw/workspace/conf/icmarkets.json'

with open(CONFIG_FILE, 'r') as f:
    APP_CONFIG = json.load(f)

IC = APP_CONFIG['icmarkets']

# Trading pairs (cTrader symbol IDs)
SYMBOLS = {
    'EURUSD': {'symbol_id': 1, 'name': 'EUR/USD', 'lot_size': 0.01},
    'GBPUSD': {'symbol_id': 2, 'name': 'GBP/USD', 'lot_size': 0.01},
    'USDJPY': {'symbol_id': 3, 'name': 'USD/JPY', 'lot_size': 0.01},
    'AUDUSD': {'symbol_id': 4, 'name': 'AUD/USD', 'lot_size': 0.01},
    'USDCAD': {'symbol_id': 5, 'name': 'USD/CAD', 'lot_size': 0.01},
    'USDCHF': {'symbol_id': 6, 'name': 'USD/CHF', 'lot_size': 0.01},
    'NZDUSD': {'symbol_id': 7, 'name': 'NZD/USD', 'lot_size': 0.01},
    'XAUUSD': {'symbol_id': 10, 'name': 'Gold', 'lot_size': 0.01},
    'XAGUSD': {'symbol_id': 11, 'name': 'Silver', 'lot_size': 0.05},
}

class TradeBot:
    def __init__(self):
        self.client = None
        self.ctid_account_id = int(IC['ctid_trader_account_id'])  # No fallback — must be configured
        self.access_token = IC.get('access_token', '')
        self.client_id = IC.get('client_id', '')
        self.client_secret = IC.get('api_secret', '')
        self.positions = {}
        self.balance = float(IC.get('accounts', {}).get(str(self.ctid_account_id), {}).get('balance', 193.21))
        self.authenticated = False
        self.reconnecting = False
        self.running = True
        
    def start(self):
        host = EndPoints.PROTOBUF_DEMO_HOST if IC.get('mode') == 'demo' else EndPoints.PROTOBUF_LIVE_HOST
        print(f"Connecting to cTrader {IC.get('mode')}...")
        
        self.client = Client(host, EndPoints.PROTOBUF_PORT, TcpProtocol)
        self.client.setConnectedCallback(self.on_connected)
        self.client.setDisconnectedCallback(self.on_disconnected)
        self.client.startService()
        reactor.run()

    def on_connected(self, client):
        print("Connected to cTrader!")
        self._authenticate()

    def _authenticate(self):
        req = ProtoOAApplicationAuthReq()
        req.clientId = self.client_id
        req.clientSecret = self.client_secret
        d = self.client.send(req)
        d.addCallbacks(self.on_app_auth, self.on_error)

    def on_app_auth(self, response):
        print("App authenticated")
        self.authenticated = True
        
        req = ProtoOAAccountAuthReq()
        req.accessToken = self.access_token
        req.ctidTraderAccountId = self.ctid_account_id
        d = self.client.send(req)
        d.addCallbacks(self.on_account_auth, self.on_error)

    def on_account_auth(self, response):
        print(f"Account authenticated: {self.ctid_account_id}")
        print(f"Balance: ${self.balance}")
        print("Ready to trade!")
        
        self.get_positions()
        self.trading_loop()

    def get_positions(self):
        req = ProtoOAReconcileReq()
        req.ctidTraderAccountId = self.ctid_account_id
        d = self.client.send(req)
        d.addCallbacks(self.on_reconcile, self.on_error)

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
                                    'side': 'BUY' if pos.get('buySide', 0) > 0 else 'SELL',
                                    'symbol_id': symbol_id
                                }
            print(f"Open positions: {len(self.positions)}")
        except Exception as e:
            print(f"Reconcile error: {e}")

    def trading_loop(self):
        if not self.running:
            return
            
        now = datetime.now().strftime('%H:%M:%S')
        print(f"\n--- Trading cycle {now} ---")
        print(f"Positions: {len(self.positions)}, Balance: ${self.balance}")
        
        if not self.authenticated:
            print("Not authenticated, reconnecting...")
            self._authenticate()
        
        reactor.callLater(30, self.trading_loop)

    def execute_trade(self, symbol, direction, volume):
        if not self.authenticated:
            print("Not authenticated")
            return False
            
        sym_id = SYMBOLS.get(symbol, {}).get('symbol_id')
        if not sym_id:
            print(f"Unknown symbol: {symbol}")
            return False
        
        side = 1 if direction.upper() == 'BUY' else 2
        
        req = ProtoOANewOrderReq()
        req.symbolId = sym_id
        req.volume = int(volume * 100000)
        req.side = side
        req.type = 1
        req.ctidTraderAccountId = self.ctid_account_id
        
        d = self.client.send(req)
        d.addCallbacks(lambda r: print(f"Trade executed: {direction} {volume} {symbol}"), 
                      lambda f: print(f"Trade failed: {f}"))
        return True

    def on_disconnected(self, client, reason):
        print(f"Disconnected: {reason}")
        if self.running and not self.reconnecting:
            print("Attempting reconnect in 5 seconds...")
            self.reconnecting = True
            self.authenticated = False
            reactor.callLater(5, self.reconnect)

    def reconnect(self):
        print("Reconnecting...")
        try:
            host = EndPoints.PROTOBUF_DEMO_HOST if IC.get('mode') == 'demo' else EndPoints.PROTOBUF_LIVE_HOST
            self.client = Client(host, EndPoints.PROTOBUF_PORT, TcpProtocol)
            self.client.setConnectedCallback(self.on_connected)
            self.client.setDisconnectedCallback(self.on_disconnected)
            self.client.startService()
            self.reconnecting = False
        except Exception as e:
            print(f"Reconnect failed: {e}")
            reactor.callLater(10, self.reconnect)

    def on_error(self, failure):
        print(f"Error: {failure}")

    def stop(self):
        self.running = False
        reactor.stop()

def main():
    print("=" * 50)
    print("TradeBot - IC Markets cTrader")
    print("=" * 50)
    print(f"Account: {IC['account_id']}")
    print(f"Account ID: {IC.get('ctid_trader_account_id')}")
    print(f"Mode: {IC.get('mode', 'demo')}")
    print(f"Balance: ${APP_CONFIG['icmarkets']['accounts'].get(str(IC.get('ctid_trader_account_id')), {}).get('balance', 'N/A')}")
    print("-" * 50)
    
    bot = TradeBot()
    
    def signal_handler(sig, frame):
        print("\nShutting down...")
        bot.stop()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    bot.start()

if __name__ == '__main__':
    main()
