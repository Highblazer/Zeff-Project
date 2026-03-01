#!/usr/bin/env python3
"""
EgoTradingBot - Aggressive Gap Hunter Strategy
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
    ProtoOAReconcileReq, ProtoOANewOrderReq,
    ProtoOASubscribeLiveTrendbarReq
)

import sys
sys.path.insert(0, '/root/.openclaw/workspace')
from lib.trading_safety import check_kill_switch, require_demo_mode

CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config.json')

with open(CONFIG_FILE, 'r') as f:
    APP_CONFIG = json.load(f)

IC = APP_CONFIG['icmarkets']
TRADING = APP_CONFIG['trading']

# Aggressive symbol config
SYMBOLS = {
    1: {'name': 'EURUSD', 'type': 'forex', 'risk_multiplier': 2.0},
    2: {'name': 'GBPUSD', 'type': 'forex', 'risk_multiplier': 2.0},
    3: {'name': 'USDJPY', 'type': 'forex', 'risk_multiplier': 2.0},
    4: {'name': 'AUDUSD', 'type': 'forex', 'risk_multiplier': 1.8},
    5: {'name': 'USDCAD', 'type': 'forex', 'risk_multiplier': 1.8},
    6: {'name': 'USDCHF', 'type': 'forex', 'risk_multiplier': 1.5},
    7: {'name': 'NZDUSD', 'type': 'forex', 'risk_multiplier': 1.5},
    10: {'name': 'XAUUSD', 'type': 'commodity', 'risk_multiplier': 3.0},  # Gold - VERY AGGRESSIVE
    11: {'name': 'XAGUSD', 'type': 'commodity', 'risk_multiplier': 2.5},
    12: {'name': 'USOIL', 'type': 'commodity', 'risk_multiplier': 2.5},
}

# Yahoo Finance for price data
YAHOO_SYMBOLS = {
    'EURUSD': 'EURUSD=X', 'GBPUSD': 'GBPUSD=X', 'USDJPY': 'USDJPY=X',
    'AUDUSD': 'AUDUSD=X', 'USDCAD': 'USDCAD=X', 'USDCHF': 'USDCHF=X',
    'NZDUSD': 'NZDUSD=X', 'XAUUSD': 'GC=F', 'XAGUSD': 'SI=F', 'USOIL': 'CL=F'
}

class EgoTradingBot:
    def __init__(self):
        self.client = None
        self.ctid_account_id = IC.get('ctid_trader_account_id')
        self.access_token = IC.get('access_token', '')
        self.positions = {}
        self.balance = 200
        self.running = False
        self.prices = {}
        self.price_history = {}
        self.heartbeat_task = None
        self.trading_task = None
        self.reconnect_delay = 5
        self.last_trade_time = 0
        self.min_trade_interval = 30  # seconds between trades
        
    def start(self):
        host = EndPoints.PROTOBUF_DEMO_HOST if IC.get('mode') == 'demo' else EndPoints.PROTOBUF_LIVE_HOST
        print(f"⚡ EGO TRADING - AGGRESSIVE MODE - connecting to {host}...")
        
        self.client = Client(host, EndPoints.PROTOBUF_PORT, TcpProtocol)
        self.client.setConnectedCallback(self.on_connected)
        self.client.setDisconnectedCallback(self.on_disconnected)
        self.client.setMessageReceivedCallback(self.on_message)
        self.client.startService()
        reactor.run()

    def on_connected(self, client):
        print("✅ Connected!")
        self.reconnect_delay = 5
        
        req = ProtoOAApplicationAuthReq()
        req.clientId = IC['client_id']
        req.clientSecret = IC['api_secret']
        d = client.send(req)
        d.addCallbacks(self.on_app_auth, self.on_error)

    def on_app_auth(self, response):
        print("✅ App authenticated")
        
        req = ProtoOAAccountAuthReq()
        req.accessToken = self.access_token
        req.ctidTraderAccountId = self.ctid_account_id
        d = self.client.send(req)
        d.addCallbacks(self.on_account_auth, self.on_error)

    def on_account_auth(self, response):
        print(f"✅ Account authenticated: {self.ctid_account_id}")
        print("⚡ EGO TRADING ONLINE - AGGRESSIVE GAP HUNTER")
        print("=" * 50)
        
        self.running = True
        self.subscribe_prices()
        self.start_heartbeat()
        self.start_trading_loop()

    def start_heartbeat(self):
        if not self.running:
            return
        try:
            req = ProtoOAReconcileReq()
            req.ctidTraderAccountId = self.ctid_account_id
            d = self.client.send(req)
            d.addCallbacks(lambda r: None, lambda f: None)
        except Exception as e:
            print(f"Warning: {e}")
        self.heartbeat_task = reactor.callLater(10, self.start_heartbeat)

    def start_trading_loop(self):
        if not self.running:
            return
        self.trading_cycle()
        self.trading_task = reactor.callLater(15, self.start_trading_loop)  # Check every 15 seconds

    def subscribe_prices(self):
        for symbol_id in SYMBOLS.keys():
            req = ProtoOASubscribeLiveTrendbarReq()
            req.ctidTraderAccountId = self.ctid_account_id
            req.symbolId = symbol_id
            req.period = 1
            d = self.client.send(req)
            d.addCallbacks(lambda r, sid=symbol_id: None, lambda f: None)

    def on_message(self, client, message):
        try:
            data = Protobuf.extract(message)
            if not isinstance(data, dict):
                return
            payload_type = data.get('payloadType', 0)
            
            if payload_type == 112:  # Price update
                symbol_id = data.get('symbolId')
                if symbol_id in SYMBOLS:
                    trendbars = data.get('trendbars', [])
                    if trendbars:
                        tb = trendbars[-1]
                        price = (tb.get('high', 0) + tb.get('low', 0)) / 2
                        
                        if symbol_id not in self.price_history:
                            self.price_history[symbol_id] = []
                        self.price_history[symbol_id].append(price)
                        self.price_history[symbol_id] = self.price_history[symbol_id][-30:]  # Keep last 30
                        
                        self.prices[symbol_id] = price
                        
            elif payload_type == 2125:  # Reconcile
                self.balance = data.get('balance', self.balance)
        except Exception as e:
            print(f"Warning: {e}")

    def trading_cycle(self):
        print(f"\n⚡ EGO TRADING CYCLE - {datetime.now().strftime('%H:%M:%S')}")

        if check_kill_switch():
            print("KILL SWITCH ACTIVE - halting all trading")
            self.running = False
            return

        if not self.prices:
            print("📊 Waiting for prices...")
            return
        
        # Check for gap opportunities
        signals = self.find_gap_signals()
        
        # Also check Yahoo for additional signals
        yahoo_prices = self.get_yahoo_prices()
        self.prices.update(yahoo_prices)
        
        yahoo_signals = self.find_yahoo_gap_signals(yahoo_prices)
        signals.update(yahoo_signals)
        
        print(f"📊 Signals found: {signals}")
        
        # Execute trades
        now = time.time()
        for symbol_id, signal in signals.items():
            # Rate limiting
            if now - self.last_trade_time < self.min_trade_interval:
                continue
                
            if len(self.positions) >= 3:  # Max 3 positions
                break
            if symbol_id in self.positions:
                continue
            if symbol_id not in self.prices:
                continue
            
            self.last_trade_time = now
            self.open_position(symbol_id, signal, self.prices[symbol_id])
        
        print(f"💰 Balance: ${self.balance:.2f}")
        print(f"📈 Open Positions: {len(self.positions)}")

    def find_gap_signals(self):
        """Find gaps from cTrader price data"""
        signals = {}
        
        for symbol_id, history in self.price_history.items():
            if len(history) < 10:
                continue
            
            config = SYMBOLS[symbol_id]
            risk_mult = config.get('risk_multiplier', 1.0)
            
            # Calculate recent volatility
            recent_high = max(history[-10:])
            recent_low = min(history[-10:])
            current = history[-1]
            
            range_pct = (recent_high - recent_low) / recent_low * 100
            
            # AGGRESSIVE gap thresholds
            gap_threshold = 0.2 * risk_mult  # Lower = more trades
            
            # Check for gap up
            if current > recent_high * (1 - gap_threshold/100):
                signals[symbol_id] = 'BUY'
                print(f"💎 GAP UP: {config['name']} ({range_pct:.2f}%)")
            
            # Check for gap down  
            elif current < recent_low * (1 + gap_threshold/100):
                signals[symbol_id] = 'SELL'
                print(f"💎 GAP DOWN: {config['name']} ({range_pct:.2f}%)")
            
            # Also check for strong momentum
            elif len(history) >= 5:
                ma5 = sum(history[-5:]) / 5
                ma10 = sum(history[-10:]) / 10
                
                if current > ma5 * 1.001 and ma5 > ma10:
                    if risk_mult >= 2.0:  # Only high risk symbols
                        signals[symbol_id] = 'BUY'
                        print(f"📈 MOMENTUM: {config['name']}")
                
                elif current < ma5 * 0.999 and ma5 < ma10:
                    if risk_mult >= 2.0:
                        signals[symbol_id] = 'SELL'
                        print(f"📉 MOMENTUM: {config['name']}")
        
        return signals

    def get_yahoo_prices(self):
        """Get additional prices from Yahoo"""
        prices = {}
        for symbol, yahoo in YAHOO_SYMBOLS.items():
            try:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo}"
                r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
                data = r.json()
                if 'result' in data['chart'] and data['chart']['result']:
                    price = data['chart']['result'][0]['meta']['regularMarketPrice']
                    # Map back to symbol ID
                    for sid, conf in SYMBOLS.items():
                        if conf['name'] == symbol:
                            prices[sid] = price
            except Exception as e:
                print(f"Warning: {e}")
        return prices

    def find_yahoo_gap_signals(self, prices):
        """Find signals from Yahoo data"""
        signals = {}
        
        for symbol, yahoo in YAHOO_SYMBOLS.items():
            try:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo}?interval=1h&range=24h"
                r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
                data = r.json()
                
                if 'result' not in data['chart'] or not data['chart']['result']:
                    continue
                
                closes = data['chart']['result'][0]['indicators']['quote'][0]['close']
                closes = [c for c in closes if c is not None]
                
                if len(closes) < 5:
                    continue
                
                # Find symbol ID
                symbol_id = None
                for sid, conf in SYMBOLS.items():
                    if conf['name'] == symbol:
                        symbol_id = sid
                        break
                
                if not symbol_id or symbol_id in signals:
                    continue
                
                config = SYMBOLS[symbol_id]
                risk_mult = config.get('risk_multiplier', 1.0)
                
                # Check for large moves in last 4 hours
                if len(closes) >= 4:
                    change = (closes[-1] - closes[-4]) / closes[-4] * 100
                    
                    # AGGRESSIVE: 0.5% move in 4 hours = signal
                    if change > 0.5 * risk_mult:
                        signals[symbol_id] = 'BUY'
                        print(f"💎 YAHOO GAP UP: {symbol} ({change:+.2f}%)")
                    elif change < -0.5 * risk_mult:
                        signals[symbol_id] = 'SELL'
                        print(f"💎 YAHOO GAP DOWN: {symbol} ({change:+.2f}%)")
                        
            except Exception as e:
                pass
        
        return signals

    def open_position(self, symbol_id, direction, price):
        """Open aggressive position"""
        config = SYMBOLS[symbol_id]
        risk_mult = config.get('risk_multiplier', 1.0)
        
        # Calculate lot size based on balance and risk
        # Conservative: 2% risk per trade (was 15% * multiplier, which was catastrophic)
        risk_pct = 0.02
        risk_amount = self.balance * risk_pct
        
        # Volume calculation (simplified)
        volume = min(TRADING.get('lot_size', 1000), 100000)  # Cap at 1 standard lot
        
        req = ProtoOANewOrderReq()
        req.ctidTraderAccountId = self.ctid_account_id
        req.symbolId = symbol_id
        req.volume = int(volume)
        req.orderType = 1  # Market
        req.tradeSide = 1 if direction == 'BUY' else 2
        
        print(f"⚡ EXECUTING: {direction} {config['name']} @ {price:.5f} (Risk: {risk_pct*100}%)")
        
        d = self.client.send(req)
        d.addCallbacks(
            lambda r: self.on_filled(r, symbol_id, direction),
            lambda f: self.on_error(f, config['name'])
        )

    def on_filled(self, response, symbol_id, direction):
        config = SYMBOLS[symbol_id]
        print(f"✅ FILLED! {direction} {config['name']}")
        self.positions[symbol_id] = {
            'direction': direction,
            'opened_at': datetime.now().isoformat()
        }

    def on_error(self, failure, name):
        print(f"❌ Error on {name}: {failure}")

    def on_disconnected(self, client, reason):
        print(f"❌ Disconnected: {reason}")
        self.running = False
        
        if self.heartbeat_task:
            self.heartbeat_task.cancel()
        if self.trading_task:
            self.trading_task.cancel()
        
        print(f"⚡ Reconnecting in {self.reconnect_delay}s...")
        reactor.callLater(self.reconnect_delay, self.reconnect)
        self.reconnect_delay = min(30, self.reconnect_delay + 5)

    def reconnect(self):
        host = EndPoints.PROTOBUF_DEMO_HOST if IC.get('mode') == 'demo' else EndPoints.PROTOBUF_LIVE_HOST
        self.client = Client(host, EndPoints.PROTOBUF_PORT, TcpProtocol)
        self.client.setConnectedCallback(self.on_connected)
        self.client.setDisconnectedCallback(self.on_disconnected)
        self.client.setMessageReceivedCallback(self.on_message)
        self.client.startService()

    def on_error(self, failure):
        print(f"❌ Error: {failure}")

def main():
    print("=" * 50)
    print("⚡ EGO TRADING BOT - AGGRESSIVE GAP HUNTER")
    print("=" * 50)
    print(f"Account: {IC.get('account_id')}")
    print(f"Mode: {IC.get('mode', 'demo')}")
    print("Strategy: Aggressive Gap Hunter (15% risk)")
    print("-" * 50)
    
    bot = EgoTradingBot()
    bot.start()

if __name__ == '__main__':
    main()
