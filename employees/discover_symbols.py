#!/usr/bin/env python3
"""
Discover all available symbols on IC Markets cTrader Demo.
Queries the broker API and prints symbol IDs, names, and categories.
"""

import sys
sys.path.insert(0, '/root/.openclaw/workspace')
from lib.credentials import get_icm_credentials

from twisted.internet import reactor, defer
from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq, ProtoOAAccountAuthReq,
    ProtoOASymbolsListReq, ProtoOASymbolByIdReq, ProtoOAAssetListReq,
)

_creds = get_icm_credentials()
CTID = _creds['ctid_trader_account_id']
CLIENT_ID = _creds['client_id']
CLIENT_SECRET = _creds['api_secret']
ACCESS_TOKEN = _creds['access_token']

client = Client(EndPoints.PROTOBUF_DEMO_HOST, EndPoints.PROTOBUF_PORT, TcpProtocol)
symbols_found = []


def on_connected(c):
    req = ProtoOAApplicationAuthReq()
    req.clientId = CLIENT_ID
    req.clientSecret = CLIENT_SECRET
    d = client.send(req)
    d.addCallbacks(on_app_auth, on_error)


def on_app_auth(msg):
    req = ProtoOAAccountAuthReq()
    req.ctidTraderAccountId = CTID
    req.accessToken = ACCESS_TOKEN
    d = client.send(req)
    d.addCallbacks(on_account_auth, on_error)


def on_account_auth(msg):
    print("Authenticated. Fetching symbol list...")
    req = ProtoOASymbolsListReq()
    req.ctidTraderAccountId = CTID
    d = client.send(req)
    d.addCallbacks(on_symbols_list, on_error)


def on_symbols_list(msg):
    payload = Protobuf.extract(msg)
    symbols = payload.symbol

    # Collect all symbols with their IDs
    for s in symbols:
        name = s.symbolName if hasattr(s, 'symbolName') else ''
        sid = s.symbolId
        enabled = s.enabled if hasattr(s, 'enabled') else True
        if enabled and name:
            symbols_found.append((sid, name))

    symbols_found.sort(key=lambda x: x[1])

    # Print categorized
    crypto = [(sid, n) for sid, n in symbols_found if any(c in n.upper() for c in ['BTC', 'ETH', 'XRP', 'LTC', 'ADA', 'SOL', 'DOGE', 'DOT', 'AVAX', 'LINK', 'MATIC', 'CRYPTO'])]
    commodities = [(sid, n) for sid, n in symbols_found if any(c in n.upper() for c in ['XAU', 'XAG', 'OIL', 'BRENT', 'WTI', 'NATGAS', 'COPPER', 'PLAT', 'PALLAD'])]
    indices = [(sid, n) for sid, n in symbols_found if any(c in n.upper() for c in ['US500', 'US30', 'US100', 'NAS', 'SPX', 'DJ', 'DAX', 'FTSE', 'UK100', 'JP225', 'AUS200', 'EU50', 'HK50', 'NIKKEI', 'SP', 'STOXX'])]
    forex_extra = [(sid, n) for sid, n in symbols_found if n.endswith('USD') or n.startswith('USD') or 'EUR' in n or 'GBP' in n]

    print(f"\n=== TOTAL SYMBOLS: {len(symbols_found)} ===\n")

    print("=== CRYPTO ===")
    for sid, n in crypto:
        print(f"  '{n}': {sid},")

    print("\n=== COMMODITIES ===")
    for sid, n in commodities:
        print(f"  '{n}': {sid},")

    print("\n=== INDICES ===")
    for sid, n in indices:
        print(f"  '{n}': {sid},")

    print("\n=== ALL SYMBOLS (for reference) ===")
    for sid, n in symbols_found:
        print(f"  {sid:6d}  {n}")

    reactor.stop()


def on_error(failure):
    print(f"Error: {failure.getErrorMessage()}")
    reactor.stop()


client.setConnectedCallback(on_connected)
client.setDisconnectedCallback(lambda c, r: None)
client.setMessageReceivedCallback(lambda c, m: None)
client.startService()
reactor.run()
