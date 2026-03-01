#!/usr/bin/env python3
"""
TradeBot - IC Markets cTrader Open API
With notifications and dashboard updates
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

CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config.json')
STATE_FILE = '/root/.openclaw/workspace/logs/tradebot_state.json'

with open(CONFIG_FILE, 'r') as f:
    APP_CONFIG = json.load(f)

IC = APP_CONFIG['icmarkets']
TRADING = APP_CONFIG['trading']

SYMBOLS = {
    1: {'name': 'EURUSD', 'type': 'forex'},
    2: {'name': 'GBPUSD', 'type': 'forex'},
    3: {'name': 'USDJPY', 'type': 'forex'},
    4: {'name': 'AUDUSD', 'type': 'forex'},
    5: {'name': 'USDCAD', 'type': 'forex'},
}

class TradeBot:
    def __init__(self):
        self.client = None
        self.ctid_account_id = IC.get('ctid_trader_account_id')
        self.access_token = IC.get('access_token', '')
        self.positions = {}
        self.balance = 20000
        self.running = False
        self.prices = {}
        self.trades_log = []
        
    def notify(self, message):
        """Notify on Telegram"""
        print(f"🔔 {message}")
        self.trades_log.append({
            'time': datetime.now().isoformat(),
            'bot': 'TradeBot',
            'message': message
        })
        self.update_dashboard()
        
    def update_dashboard(self):
        """Update dashboard with current status"""
        try:
            dashboard = """# ⬡ Binary Rogue Command Center

**Last Updated:** {timestamp}

---

## 🤖 CEO Status — Zeff.bot #001

| Metric | Value |
|--------|-------|
| Status | 🟢 ONLINE |
| Model | MiniMax-M2.5 |

---

## 💰 System Resources

| Metric | Value |
|--------|-------|
| Uptime | ~41h |
| Memory | ~2.6 GB |

---

## 👥 Employee Roster

| ID | Name | Status |
|----|------|--------|
| #001 | Zeff.bot (CEO) | 🟢 |
| #002 | Dropship | ⏸️ |
| #003 | TradeBot | 🟢 |
| #004 | Sculpt Trading | 💎 |

---

## 📊 Live Demo Account

| Metric | Value |
|--------|-------|
| Broker | IC Markets |
| Account | 9877716 (Demo) |
| Balance | ${balance} USD |

---

## 📈 Markets

| Bot | Markets |
|-----|---------|
| TradeBot | EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD |
| Sculpt | EURUSD, GBPUSD, USDJPY, XAUUSD, XAGUSD, USOIL |

---

## 🔔 Recent Trades

{recent_trades}

---

*Binary Rogue Systems*
""".format(
                timestamp=datetime.now().strftime('%Y-%m-%d %H:%M CET'),
                balance=self.balance,
                recent_trades='\n'.join([f"- {t['time']}: {t['message']}" for t in self.trades_log[-5:]]) or 'No trades yet'
            )
            
            with open('/root/.openclaw/workspace/dashboard.md', 'w') as f:
                f.write(dashboard)
        except Exception as e:
            print(f"Dashboard error: {e}")

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
        req = ProtoOAAccountAuthReq()
        req.accessToken = self.access_token
        req.ctidTraderAccountId = self.ctid_account_id
        d = self.client.send(req)
        d.addCallbacks(self.on_account_auth, self.on_error)

    def on_account_auth(self, response):
        print(f"✅ Account authenticated: {self.ctid_account_id}")
        self.running = True
        self.notify("🤖 TradeBot is ONLINE")
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
        except:
            pass
        reactor.callLater(10, self.start_heartbeat)

    def start_trading_loop(self):
        if not self.running:
            return
        self.trading_cycle()
        reactor.callLater(60, self.start_trading_loop)

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
            
            if data.get('payloadType') == 112:
                symbol_id = data.get('symbolId')
                if symbol_id in SYMBOLS:
                    trendbars = data.get('trendbars', [])
                    if trendbars:
                        tb = trendbars[-1]
                        price = (tb.get('high', 0) + tb.get('low', 0)) / 2
                        self.prices[symbol_id] = price
            elif data.get('payloadType') == 2125:
                self.balance = data.get('balance', self.balance)
                self.update_dashboard()
        except:
            pass

    def trading_cycle(self):
        self.update_dashboard()

    def open_position(self, symbol_id, direction, price):
        name = SYMBOLS.get(symbol_id, {}).get('name', str(symbol_id))
        self.notify(f"📗 TradeBot: Opening {direction} {name} @ {price:.5f}")
        
        req = ProtoOANewOrderReq()
        req.ctidTraderAccountId = self.ctid_account_id
        req.symbolId = symbol_id
        req.volume = TRADING.get('lot_size', 1000)
        req.orderType = 1
        req.tradeSide = 1 if direction == 'BUY' else 2
        
        d = self.client.send(req)
        d.addCallbacks(lambda r: self.notify(f"✅ FILL: {name} {direction}"), 
                      lambda f: self.notify(f"❌ FAIL: {name} - {f}"))

    def on_disconnected(self, client, reason):
        self.running = False
        print(f"❌ Disconnected: {reason}")
        reactor.callLater(5, self.reconnect)
        self.reconnect_delay = min(30, getattr(self, 'reconnect_delay', 5) + 5)

    def reconnect(self):
        self.start()

    def on_error(self, failure):
        print(f"❌ Error: {failure}")

def main():
    print("🤖 TradeBot with Notifications")
    bot = TradeBot()
    bot.start()

if __name__ == '__main__':
    main()
