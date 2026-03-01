#!/usr/bin/env python3
"""
TradeBot - IC Markets cTrader LIVE Trading
"""

from twisted.internet import reactor
from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints

# Override to live server
EndPoints.PROTOBUF_LIVE_HOST = "live-uk-eqx-01.p.c-trader.com"

import json
import signal
import sys
from datetime import datetime
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq, ProtoOAAccountAuthReq,
    ProtoOANewOrderReq, ProtoOAReconcileReq
)

CONFIG_FILE = '/root/.openclaw/workspace/conf/icmarkets.json'

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
        self.balance = 0
        self.authenticated = False
        self.running = True
        self.reconnect_delay = 5
        
    def start(self):
        print("=" * 50)
        print("⚠️  LIVE TRADING MODE  ⚠️")
        print("=" * 50)
        print(f"Connecting to LIVE server...")
        print(f"Account ID: {self.ctid_account_id}")
        print("-" * 50)
        
        self.client = Client(EndPoints.PROTOBUF_LIVE_HOST, EndPoints.PROTOBUF_PORT, TcpProtocol)
        self.client.setConnectedCallback(self.on_connected)
        self.client.setDisconnectedCallback(self.on_disconnected)
        self.client.startService()
        reactor.run()

    def on_connected(self, client):
        print("✅ Connected to LIVE server!")
        self._authenticate()

    def _authenticate(self):
        req = ProtoOAApplicationAuthReq()
        req.clientId = self.client_id
        req.clientSecret = self.client_secret
        d = self.client.send(req)
        d.addCallbacks(self.on_app_auth, lambda f: None)

    def on_app_auth(self, response):
        print("✅ App authenticated")
        self.authenticated = True
        self.reconnect_delay = 5
        
        req = ProtoOAAccountAuthReq()
        req.accessToken = self.access_token
        req.ctidTraderAccountId = self.ctid_account_id
        d = self.client.send(req)
        d.addCallbacks(self.on_account_auth, lambda f: None)

    def on_account_auth(self, response):
        print(f"✅ Account authenticated: {self.ctid_account_id}")
        print("🚀 READY TO TRADE!")
        print("-" * 50)
        
        self.get_positions()
        self.trading_loop()

    def get_positions(self):
        req = ProtoOAReconcileReq()
        req.ctidTraderAccountId = self.ctid_account_id
        d = self.client.send(req)
        d.addCallbacks(self.on_reconcile, lambda f: None)

    def write_status(self):
        """Write status to file for dashboard"""
        import json
        status = {
            'balance': self.balance,
            'connected': self.authenticated,
            'mode': 'LIVE',
            'account': str(self.ctid_account_id),
            'positions': len(self.positions),
            'last_update': datetime.now().isoformat()
        }
        with open('/root/.openclaw/workspace/employees/trading_status.json', 'w') as f:
            json.dump(status, f)

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
        except Exception as e:
            print(f"Warning: failed to reconcile positions: {e}")

    def trading_loop(self):
        if not self.running:
            return
        now = datetime.now().strftime('%H:%M:%S')
        print(f"--- {now} | Positions: {len(self.positions)} ---")
        self.get_positions()
        self.write_status()
        reactor.callLater(30, self.trading_loop)

    def execute_trade(self, symbol, direction, volume):
        if not self.authenticated:
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
        d.addCallbacks(lambda r: print(f"✅ TRADE: {direction} {volume} {symbol}"), 
                      lambda f: print(f"❌ Trade failed"))
        return True

    def on_disconnected(self, client, reason):
        print("⚠️ Disconnected")
        if self.running:
            print(f"Reconnecting in {self.reconnect_delay}s...")
            reactor.callLater(self.reconnect_delay, self.reconnect)
            self.reconnect_delay = min(self.reconnect_delay * 2, 60)

    def reconnect(self):
        self.authenticated = False
        self.client = Client(EndPoints.PROTOBUF_LIVE_HOST, EndPoints.PROTOBUF_PORT, TcpProtocol)
        self.client.setConnectedCallback(self.on_connected)
        self.client.setDisconnectedCallback(self.on_disconnected)
        self.client.startService()

    def stop(self):
        self.running = False
        reactor.stop()

def main():
    print("⚠️  LIVE TRADING  ⚠️")
    bot = TradeBot()
    signal.signal(signal.SIGINT, lambda s, f: bot.stop())
    bot.start()

if __name__ == '__main__':
    main()
