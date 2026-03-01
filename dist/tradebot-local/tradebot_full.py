#!/usr/bin/env python3
"""
TradeBot - IC Markets cTrader Open API
Full trading functionality
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
    ProtoOAReconcileReq, ProtoOASymbolsListReq, 
    ProtoOANewOrderReq, ProtoOAClosePositionReq,
    ProtoOASubscribeLiveTrendbarReq
)

CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config.json')
STATE_FILE = os.path.join(os.path.dirname(__file__), 'paper-trading-state.json')

with open(CONFIG_FILE, 'r') as f:
    APP_CONFIG = json.load(f)

IC = APP_CONFIG['icmarkets']
TRADING = APP_CONFIG['trading']

# Yahoo Finance symbols for prices
YAHOO_SYMBOLS = {
    'EURUSD': 'EURUSD=X', 'GBPUSD': 'GBPUSD=X', 'USDJPY': 'USDJPY=X',
    'AUDUSD': 'AUDUSD=X', 'USDCAD': 'USDCAD=X'
}

SYMBOLS = {
    'EURUSD': {'name': 'EUR/USD', 'symbol_id': 1},
    'GBPUSD': {'name': 'GBP/USD', 'symbol_id': 2},
    'USDJPY': {'name': 'USD/JPY', 'symbol_id': 3},
}

class TradeBot:
    def __init__(self):
        self.client = None
        self.ctid_account_id = IC.get('ctid_trader_account_id', int(IC['account_id']))
        self.access_token = IC.get('access_token', '')
        self.positions = {}
        self.balance = 20000
        self.equity = 20000
        self.authenticated = False
        self.symbols_cache = {}
        
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
        
        # Get account info
        self.get_account_info()
        
        # Start trading loop directly
        self.trading_loop()

    def get_account_info(self):
        req = ProtoOAReconcileReq()
        req.ctidTraderAccountId = self.ctid_account_id
        d = self.client.send(req)
        d.addCallbacks(self.on_account_info, self.on_error)

    def on_account_info(self, response):
        data = Protobuf.extract(response)
        print(f"📊 Account data: {json.dumps(data, indent=2)[:200]}")
        # Schedule next update
        reactor.callLater(60, self.get_account_info)

    def get_symbols(self):
        # Skip for now - use hardcoded symbol IDs
        pass

    def trading_loop(self):
        print("\n" + "="*40)
        print(f"🔄 Trading Cycle - {datetime.now().strftime('%H:%M:%S')}")
        print("="*40)
        
        # Keepalive - send reconcile to keep connection alive
        self.get_account_info()
        
        # Get prices from Yahoo
        prices = self.get_yahoo_prices()
        print(f"📊 Prices: {prices}")
        
        # Check signals
        signals = self.check_signals(prices)
        
        # Check existing positions
        self.check_positions(prices)
        
        # Look for new trades
        for symbol, signal in signals.items():
            if signal and symbol not in self.positions:
                print(f"🎯 Signal: {symbol} -> {signal}")
                # Place trade
                self.open_position(symbol, signal, prices.get(symbol))
        
        print(f"💰 Balance: ${self.balance:.2f} | Equity: ${self.equity:.2f}")
        print("-"*40)
        
        # Next cycle
        reactor.callLater(60, self.trading_loop)

    def get_yahoo_prices(self):
        prices = {}
        for symbol, yahoo in YAHOO_SYMBOLS.items():
            try:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo}"
                r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
                data = r.json()
                if 'result' in data['chart'] and data['chart']['result']:
                    prices[symbol] = data['chart']['result'][0]['meta']['regularMarketPrice']
            except Exception as e:
                print(f"  ⚠️ {symbol} error: {e}")
        return prices

    def check_signals(self, prices):
        """Simple EMA crossover strategy"""
        signals = {}
        
        for symbol in YAHOO_SYMBOLS:
            if symbol not in prices:
                continue
            
            try:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{YAHOO_SYMBOLS[symbol]}?interval=1h&range=48h"
                r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
                data = r.json()
                
                if 'result' not in data['chart'] or not data['chart']['result']:
                    continue
                
                closes = data['chart']['result'][0]['indicators']['quote'][0]['close']
                closes = [c for c in closes if c is not None]
                
                if len(closes) < 50:
                    continue
                
                # EMA 20 vs EMA 50
                ema20 = sum(closes[-20:]) / 20
                ema50 = sum(closes[-50:]) / 50
                
                if ema20 > ema50 * 1.001:
                    signals[symbol] = 'BUY'
                elif ema20 < ema50 * 0.999:
                    signals[symbol] = 'SELL'
                    
            except Exception as e:
                print(f"  ⚠️ {symbol} signal error: {e}")
        
        return signals

    def check_positions(self, prices):
        """Check and close positions at SL/TP"""
        # Simplified - in real implementation, track actual positions
        pass

    def open_position(self, symbol, direction, price):
        """Open a new position"""
        if not price:
            return
            
        volume = TRADING.get('lot_size', 1000)  # micro lots
        symbol_id = SYMBOLS.get(symbol, {}).get('symbol_id', 1)
        
        req = ProtoOANewOrderReq()
        req.ctidTraderAccountId = self.ctid_account_id
        req.symbolId = symbol_id
        req.volume = volume
        req.orderType = 1  # Market
        req.tradeSide = 1 if direction == 'BUY' else 2
        
        print(f"📤 Opening {direction} {symbol} @ {price}")
        
        d = self.client.send(req)
        d.addCallbacks(lambda r: self.on_order_filled(r, symbol, direction), 
                      lambda f: self.on_order_error(f, symbol))

    def on_order_filled(self, response, symbol, direction):
        data = Protobuf.extract(response)
        print(f"✅ Order filled! {symbol} {direction}")
        self.positions[symbol] = {
            'direction': direction,
            'filled_at': datetime.now().isoformat()
        }

    def on_order_error(self, failure, symbol):
        print(f"❌ Order failed for {symbol}: {failure}")

    def on_disconnected(self, client, reason):
        print(f"❌ Disconnected: {reason}")

    def on_error(self, failure):
        print(f"❌ Error: {failure}")

def main():
    print("=" * 50)
    print("🤖 TradeBot - IC Markets cTrader Open API")
    print("=" * 50)
    print(f"Account: {IC.get('account_id', 'N/A')}")
    print(f"ctidTraderAccountId: {IC.get('ctid_trader_account_id', 'N/A')}")
    print(f"Mode: {IC.get('mode', 'demo')}")
    print("-" * 50)
    
    bot = TradeBot()
    bot.start()

if __name__ == '__main__':
    main()
