#!/usr/bin/env python3
"""
TradeBot - IC Markets cTrader Open API
With heartbeat and auto-reconnect
"""

import json
import os
import time
import requests
from datetime import datetime
import signal
import sys
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
        self.reconnect_delay = 5
        self.heartbeat_task = None
        self.trading_task = None
        
    def start(self):
        host = EndPoints.PROTOBUF_DEMO_HOST if IC.get('mode') == 'demo' else EndPoints.PROTOBUF_LIVE_HOST
        print(f"🔗 Connecting to {host}...")
        
        self.client = Client(host, EndPoints.PROTOBUF_PORT, TcpProtocol)
        self.client.setConnectedCallback(self.on_connected)
        self.client.setDisconnectedCallback(self.on_disconnected)
        self.client.setMessageReceivedCallback(self.on_message)
        self.client.startService()
        
        # Run reactor
        reactor.run()

    def on_connected(self, client):
        print("✅ Connected!")
        self.reconnect_delay = 5  # Reset reconnect delay
        
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
        
        # Start heartbeat (every 10 seconds)
        self.start_heartbeat()
        
        # Start trading loop (every 60 seconds)
        self.start_trading_loop()

    def start_heartbeat(self):
        """Send heartbeat every 10 seconds to keep connection alive"""
        if not self.running:
            return
        
        try:
            # Send a light weight request to keep connection alive
            req = ProtoOAReconcileReq()
            req.ctidTraderAccountId = self.ctid_account_id
            d = self.client.send(req)
            d.addCallbacks(
                lambda r: None,  # Silent success
                lambda f: None  # Silent failure - let reconnect handle it
            )
        except:
            pass
        
        # Schedule next heartbeat
        self.heartbeat_task = reactor.callLater(10, self.start_heartbeat)

    def start_trading_loop(self):
        """Trading cycle"""
        if not self.running:
            return
        
        self.trading_cycle()
        
        # Schedule next cycle
        self.trading_task = reactor.callLater(60, self.start_trading_loop)

    def subscribe_prices(self):
        """Subscribe to live trendbars (prices)"""
        for symbol_id in SYMBOLS.keys():
            req = ProtoOASubscribeLiveTrendbarReq()
            req.ctidTraderAccountId = self.ctid_account_id
            req.symbolId = symbol_id
            req.period = 1
            
            d = self.client.send(req)
            d.addCallbacks(
                lambda r, sid=symbol_id: print(f"📊 Subscribed to {SYMBOLS[sid]['name']}"),
                lambda f: print(f"❌ Subscribe error: {f}")
            )

    def on_message(self, client, message):
        """Handle incoming messages"""
        try:
            data = Protobuf.extract(message)
            if not isinstance(data, dict):
                return
            payload_type = data.get('payloadType', 0)
            
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
            trendbars = data.get('trendbars', [])
            if trendbars:
                tb = trendbars[-1]
                price = (tb.get('high', 0) + tb.get('low', 0)) / 2
                self.prices[symbol_id] = price

    def handle_reconcile(self, data):
        """Handle account reconcile"""
        self.balance = data.get('balance', self.balance)

    def trading_cycle(self):
        print("\n" + "="*45)
        print(f"🔄 Trading Cycle - {datetime.now().strftime('%H:%M:%S')}")
        print("="*45)
        
        # Show current prices
        if self.prices:
            print("📊 Prices:")
            for symbol_id, price in self.prices.items():
                name = SYMBOLS.get(symbol_id, {}).get('name', str(symbol_id))
                print(f"   {name}: {price:.5f}")
        else:
            print("📊 Waiting for prices...")
        
        # Get signals and trade
        signals = self.check_signals()
        for symbol_id, signal in signals.items():
            if symbol_id not in self.positions and self.prices.get(symbol_id):
                self.open_position(symbol_id, signal, self.prices[symbol_id])
        
        print(f"💰 Balance: ${self.balance:.2f}")
        print(f"📈 Open Positions: {len(self.positions)}")

    def check_signals(self):
        """EMA crossover strategy"""
        signals = {}
        # Placeholder - add strategy logic here
        return signals

    def open_position(self, symbol_id, direction, price):
        """Open a new position"""
        volume = TRADING.get('lot_size', 1000)
        
        req = ProtoOANewOrderReq()
        req.ctidTraderAccountId = self.ctid_account_id
        req.symbolId = symbol_id
        req.volume = volume
        req.orderType = 1
        req.tradeSide = 1 if direction == 'BUY' else 2
        
        name = SYMBOLS.get(symbol_id, {}).get('name', str(symbol_id))
        print(f"📤 Opening {direction} {name} @ {price}")
        
        # Write to trade activity log
        with open('/root/.openclaw/workspace/logs/trade_activity.log', 'a') as f:
            f.write(f"{datetime.now().isoformat()} | TRADEBOT: {direction} {name} @ {price:.5f}\n")
        
        d = self.client.send(req)
        d.addCallbacks(
            lambda r: self.on_order_filled(r, symbol_id, direction),
            lambda f: self.on_order_error(f, name)
        )

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
        print(f"❌ Disconnected: {reason}")
        self.running = False
        
        # Cancel scheduled tasks
        if self.heartbeat_task and self.heartbeat_task.active():
            self.heartbeat_task.cancel()
        if self.trading_task and self.trading_task.active():
            self.trading_task.cancel()
        
        # Schedule reconnect
        print(f"🔄 Reconnecting in {self.reconnect_delay}s...")
        reactor.callLater(self.reconnect_delay, self.reconnect)
        
        # Increase reconnect delay (max 30s)
        self.reconnect_delay = min(30, self.reconnect_delay + 5)

    def reconnect(self):
        """Reconnect to API"""
        host = EndPoints.PROTOBUF_DEMO_HOST if IC.get('mode') == 'demo' else EndPoints.PROTOBUF_LIVE_HOST
        print(f"🔗 Reconnecting to {host}...")
        
        self.client = Client(host, EndPoints.PROTOBUF_PORT, TcpProtocol)
        self.client.setConnectedCallback(self.on_connected)
        self.client.setDisconnectedCallback(self.on_disconnected)
        self.client.setMessageReceivedCallback(self.on_message)
        self.client.startService()

    def on_error(self, failure):
        print(f"❌ Error: {failure}")

    def shutdown(self):
        """Graceful shutdown"""
        print("🛑 Shutting down...")
        self.running = False
        if self.heartbeat_task and self.heartbeat_task.active():
            self.heartbeat_task.cancel()
        if self.trading_task and self.trading_task.active():
            self.trading_task.cancel()
        reactor.stop()

def main():
    print("=" * 50)
    print("🤖 TradeBot - IC Markets cTrader Open API")
    print("=" * 50)
    print(f"Account: {IC.get('account_id')}")
    print(f"ctidTraderAccountId: {IC.get('ctid_trader_account_id')}")
    print(f"Mode: {IC.get('mode', 'demo')}")
    print("-" * 50)
    
    bot = TradeBot()
    
    # Handle graceful shutdown
    def signal_handler(sig, frame):
        bot.shutdown()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    bot.start()

if __name__ == '__main__':
    main()
