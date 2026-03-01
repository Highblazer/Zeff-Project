#!/usr/bin/env python3
"""
TradeBot - IC Markets cTrader Open API
Full trading with IC Markets prices
"""

import json
import os
import time
import requests
from datetime import datetime
from twisted.internet import reactor, defer
from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq, ProtoOAAccountAuthReq,
    ProtoOAReconcileReq, ProtoOANewOrderReq, ProtoOAClosePositionReq,
    ProtoOASubscribeLiveTrendbarReq, ProtoOAUnsubscribeLiveTrendbarReq
)
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoHeartbeatEvent

CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config.json')

with open(CONFIG_FILE, 'r') as f:
    APP_CONFIG = json.load(f)

IC = APP_CONFIG['icmarkets']
TRADING = APP_CONFIG['trading']

# Symbol ID mapping for IC Markets
SYMBOLS = {
    1: {'name': 'EURUSD', 'ic_name': 'EUR/USD'},
    2: {'name': 'GBPUSD', 'ic_name': 'GBP/USD'},
    3: {'name': 'USDJPY', 'ic_name': 'USD/JPY'},
    4: {'name': 'AUDUSD', 'ic_name': 'AUD/USD'},
    5: {'name': 'USDCAD', 'ic_name': 'USD/CAD'},
    6: {'name': 'USDCHF', 'ic_name': 'USD/CHF'},
    7: {'name': 'NZDUSD', 'ic_name': 'NZD/USD'},
}

class TradeBot:
    def __init__(self):
        self.client = None
        self.ctid_account_id = IC.get('ctid_trader_account_id')
        self.access_token = IC.get('access_token', '')
        self.positions = {}
        self.balance = 20000
        self.equity = 20000
        self.authenticated = False
        self.prices = {}
        self.running = False
        
    def start(self):
        host = EndPoints.PROTOBUF_DEMO_HOST if IC.get('mode') == 'demo' else EndPoints.PROTOBUF_LIVE_HOST
        print(f"🔗 Connecting to {host}...")
        
        self.client = Client(host, EndPoints.PROTOBUF_PORT, TcpProtocol)
        self.client.setConnectedCallback(self.on_connected)
        self.client.setDisconnectedCallback(self.on_disconnected)
        self.client.setMessageReceivedCallback(self.on_message)
        self.client.startService()
        reactor.run()

    def on_connected(self, client):
        print("✅ Connected!")
        req = ProtoOAApplicationAuthReq()
        req.clientId = IC['client_id']
        req.clientSecret = IC['api_secret']
        d = client.send(req)
        d.addCallbacks(self.on_app_auth, self.on_error)

    def on_app_auth(self, response):
        print("✅ App authenticated")
        self.authenticated = True
        
        req = ProtoOAAccountAuthReq()
        req.accessToken = self.access_token
        req.ctidTraderAccountId = self.ctid_account_id
        d = self.client.send(req)
        d.addCallbacks(self.on_account_auth, self.on_error)

    def on_account_auth(self, response):
        print(f"✅ Account authenticated: {self.ctid_account_id}")
        print("🎉 Ready to trade!")
        print("-" * 40)
        
        self.running = True
        
        # Subscribe to live prices
        self.subscribe_prices()
        
        # Get account info
        self.get_account_info()
        
        # Start trading loop
        self.trading_loop()

    def subscribe_prices(self):
        """Subscribe to live trendbars (prices)"""
        for symbol_id in SYMBOLS.keys():
            req = ProtoOASubscribeLiveTrendbarReq()
            req.ctidTraderAccountId = self.ctid_account_id
            req.symbolId = symbol_id
            req.period = 1  # Default 1-minute bars
            
            d = self.client.send(req)
            d.addCallbacks(lambda r, sid=symbol_id: print(f"📊 Subscribed to {SYMBOLS[sid]['name']}"),
                          lambda f: print(f"❌ Subscribe error: {f}"))

    def on_message(self, client, message):
        """Handle incoming messages"""
        # Check if it's a protobuf message we can extract
        try:
            data = Protobuf.extract(message)
            if not isinstance(data, dict):
                return
            payload_type = data.get('payloadType', 0)
            
            # Handle price updates
            if payload_type == 112:  # ProtoOALiveTrendbarEvent
                self.handle_price_update(data)
            elif payload_type == 2125:  # ProtoOAReconcileRes
                self.handle_reconcile(data)
        except:
            pass

    def handle_price_update(self, data):
        """Handle live price update"""
        symbol_id = data.get('symbolId')
        if symbol_id in SYMBOLS:
            # Get the last trendbar
            trendbars = data.get('trendbars', [])
            if trendbars:
                tb = trendbars[-1]
                price = (tb.get('high', 0) + tb.get('low', 0)) / 2
                self.prices[symbol_id] = price

    def handle_reconcile(self, data):
        """Handle account reconcile"""
        self.balance = data.get('balance', self.balance)

    def get_account_info(self):
        """Keep connection alive"""
        if not self.running:
            return
        req = ProtoOAReconcileReq()
        req.ctidTraderAccountId = self.ctid_account_id
        d = self.client.send(req)
        d.addCallbacks(lambda r: None, lambda f: print(f"❌ Reconcile: {f}"))
        
        # Schedule next
        reactor.callLater(30, self.get_account_info)

    def trading_loop(self):
        if not self.running:
            return
            
        print("\n" + "="*45)
        print(f"🔄 Trading Cycle - {datetime.now().strftime('%H:%M:%S')}")
        print("="*45)
        
        # Show current prices
        print("📊 Prices:")
        for symbol_id, price in self.prices.items():
            name = SYMBOLS.get(symbol_id, {}).get('name', str(symbol_id))
            print(f"   {name}: {price:.5f}")
        
        # Get signals
        signals = self.check_signals()
        
        # Check existing positions
        self.check_positions()
        
        # Execute new trades
        for symbol_id, signal in signals.items():
            if symbol_id not in self.positions:
                price = self.prices.get(symbol_id)
                if price:
                    self.open_position(symbol_id, signal, price)
        
        print(f"💰 Balance: ${self.balance:.2f}")
        print(f"📈 Open Positions: {len(self.positions)}")
        
        # Schedule next cycle
        reactor.callLater(60, self.trading_loop)

    def check_signals(self):
        """Simple EMA crossover from recent prices"""
        signals = {}
        # This would need historical data - for now return empty
        # In production, fetch from IC Markets historical API
        return signals

    def check_positions(self):
        """Check positions and apply SL/TP"""
        # Simplified - in production, track actual positions
        pass

    def open_position(self, symbol_id, direction, price):
        """Open a new position"""
        volume = TRADING.get('lot_size', 1000)
        
        req = ProtoOANewOrderReq()
        req.ctidTraderAccountId = self.ctid_account_id
        req.symbolId = symbol_id
        req.volume = volume
        req.orderType = 1  # Market
        req.tradeSide = 1 if direction == 'BUY' else 2
        
        name = SYMBOLS.get(symbol_id, {}).get('name', str(symbol_id))
        print(f"📤 Opening {direction} {name} @ {price}")
        
        d = self.client.send(req)
        d.addCallbacks(lambda r: self.on_order_filled(r, symbol_id, direction),
                      lambda f: self.on_order_error(f, name))

    def on_order_filled(self, response, symbol_id, direction):
        name = SYMBOLS.get(symbol_id, {}).get('name', str(symbol_id))
        print(f"✅ Order filled! {name} {direction}")
        self.positions[symbol_id] = {
            'direction': direction,
            'opened_at': datetime.now().isoformat()
        }

    def on_order_error(self, failure, name):
        print(f"❌ Order failed for {name}: {failure}")

    def on_disconnected(self, client, reason):
        self.running = False
        print(f"❌ Disconnected: {reason}")

    def on_error(self, failure):
        print(f"❌ Error: {failure}")

def main():
    print("=" * 50)
    print("🤖 TradeBot - IC Markets cTrader Open API")
    print("=" * 50)
    print(f"Account: {IC.get('account_id')}")
    print(f"ctidTraderAccountId: {IC.get('ctid_trader_account_id')}")
    print(f"Mode: {IC.get('mode', 'demo')}")
    print("-" * 50)
    
    bot = TradeBot()
    bot.start()

if __name__ == '__main__':
    main()
