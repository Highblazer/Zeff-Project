#!/usr/bin/env python3
"""
TradeBot - IC Markets cTrader Open API
Official SDK + Protobuf
"""

import json
import os
import time
from datetime import datetime
from twisted.internet import reactor, defer
from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq, ProtoOAAccountAuthReq,
    ProtoOASymbolsListReq, ProtoOANewOrderReq,
    ProtoOAClosePositionReq, ProtoOAReconcileReq
)

# Config
CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config.json')
STATE_FILE = os.path.join(os.path.dirname(__file__), 'paper-trading-state.json')

with open(CONFIG_FILE, 'r') as f:
    APP_CONFIG = json.load(f)

IC = APP_CONFIG['icmarkets']
TRADING = APP_CONFIG['trading']

# Trading pairs
SYMBOLS = {
    'EURUSD': {'symbol_id': 1, 'name': 'EUR/USD', 'lot_size': 0.01},
    'GBPUSD': {'symbol_id': 2, 'name': 'GBP/USD', 'lot_size': 0.01},
    'USDJPY': {'symbol_id': 3, 'name': 'USD/JPY', 'lot_size': 0.01},
    'AUDUSD': {'symbol_id': 4, 'name': 'AUD/USD', 'lot_size': 0.01},
    'USDCAD': {'symbol_id': 5, 'name': 'USD/CAD', 'lot_size': 0.01},
}

class TradeBot:
    def __init__(self):
        self.client = None
        self.ctid_account_id = IC.get('ctid_trader_account_id', int(IC['account_id']))
        self.access_token = IC.get('access_token', '')
        self.positions = {}
        self.balance = 20000  # Demo account balance
        self.authenticated = False
        
    def start(self):
        host = EndPoints.PROTOBUF_DEMO_HOST if IC.get('mode') == 'demo' else EndPoints.PROTOBUF_LIVE_HOST
        print(f"🔗 Connecting to {host}...")
        
        self.client = Client(host, EndPoints.PROTOBUF_PORT, TcpProtocol)
        self.client.setConnectedCallback(self.on_connected)
        self.client.setDisconnectedCallback(self.on_disconnected)
        self.client.startService()
        reactor.run()

    def on_connected(self, client):
        print("✅ Connected!")
        # App auth
        req = ProtoOAApplicationAuthReq()
        req.clientId = IC['client_id']
        req.clientSecret = IC['api_secret']
        d = client.send(req)
        d.addCallbacks(self.on_app_auth, self.on_error)

    def on_app_auth(self, response):
        print("✅ App authenticated")
        self.authenticated = True
        
        # Account auth
        req = ProtoOAAccountAuthReq()
        req.accessToken = self.access_token
        req.ctidTraderAccountId = self.ctid_account_id
        d = self.client.send(req)
        d.addCallbacks(self.on_account_auth, self.on_error)

    def on_account_auth(self, response):
        print(f"✅ Account authenticated: {self.ctid_account_id}")
        print("🎉 Ready to trade!")
        print("-" * 40)
        
        # Get positions
        self.get_positions()
        
        # Start trading loop
        self.trading_loop()

    def get_positions(self):
        # Request positions via reconcile
        req = ProtoOAReconcileReq()
        req.ctidTraderAccountId = self.ctid_account_id
        d = self.client.send(req)
        d.addCallbacks(self.on_reconcile, self.on_error)

    def on_reconcile(self, response):
        print(f"📊 Reconcile OK! Type: {response.payloadType}")
        data = Protobuf.extract(response)
        print(f"Data: {json.dumps(data, indent=2, default=str)[:500]}")

    def trading_loop(self):
        print("🔄 Starting trading loop...")
        # Placeholder for trading logic
        # Here you would:
        # 1. Fetch prices
        # 2. Check signals
        # 3. Open/close positions
        
        reactor.callLater(60, self.trading_loop)

    def on_disconnected(self, client, reason):
        print(f"❌ Disconnected: {reason}")

    def on_error(self, failure):
        print(f"❌ Error: {failure}")

def main():
    print("=" * 50)
    print("🤖 TradeBot - IC Markets cTrader Open API")
    print("=" * 50)
    print(f"Account: {IC['account_id']}")
    print(f"Mode: {IC.get('mode', 'demo')}")
    print("-" * 50)
    
    bot = TradeBot()
    bot.start()

if __name__ == '__main__':
    main()
