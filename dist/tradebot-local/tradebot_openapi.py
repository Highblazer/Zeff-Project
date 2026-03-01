#!/usr/bin/env python3
"""
TradeBot - IC Markets via cTrader Open API
Uses official OpenApiPy library
"""

import json
import os
from twisted.internet import reactor
from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq, ProtoOAAccountAuthReq,
    ProtoOAMarginRequirementsReq, ProtoOASymbolsReq,
    ProtoOAPositionOpenReq, ProtoOAPositionCloseReq,
    ProtoOAOrderSendReq
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOAPositionModel

# Load config
CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config.json')
STATE_FILE = os.path.join(os.path.dirname(__file__), 'paper-trading-state.json')

with open(CONFIG_FILE, 'r') as f:
    APP_CONFIG = json.load(f)

IC_CONFIG = APP_CONFIG['icmarkets']
TRADING_CONFIG = APP_CONFIG['trading']

print("=" * 60)
print("🤖 TradeBot - cTrader Open API")
print("=" * 60)
print(f"Client ID: {IC_CONFIG['client_id'][:20]}...")
print(f"Account: {IC_CONFIG['account_id']}")
print("-" * 60)

# Connection state
client = None
account_id = int(IC_CONFIG['account_id'])
access_token = IC_CONFIG.get('access_token', '')

def on_error(failure):
    print(f"❌ Error: {failure}")
    reactor.stop()

def connected(proto_client):
    global client
    client = proto_client
    print("✅ Connected to cTrader Open API")
    
    # Application auth
    auth_req = ProtoOAApplicationAuthReq()
    auth_req.clientId = IC_CONFIG['client_id']
    auth_req.clientSecret = IC_CONFIG['api_secret']
    
    d = client.send(auth_req)
    d.addCallbacks(on_app_auth, on_error)

def on_app_auth(response):
    print(f"✅ App authenticated")
    
    # Now do account auth
    account_auth = ProtoOAAccountAuthReq()
    account_auth.accessToken = access_token if access_token else IC_CONFIG.get('access_token', '')
    account_auth.accountId = account_id
    
    d = client.send(account_auth)
    d.addCallbacks(on_account_auth, on_error)

def on_account_auth(response):
    print(f"✅ Account authenticated: {account_id}")
    print("🎉 Ready to trade!")
    
    # Request symbols
    symbols_req = ProtoOASymbolsReq()
    d = client.send(symbols_req)
    d.addCallbacks(on_symbols, on_error)

def on_symbols(response):
    print(f"📊 Received symbols data")
    reactor.stop()

def disconnected(reason):
    print(f"❌ Disconnected: {reason}")
    reactor.stop()

def main():
    global client
    
    # Create client
    host = EndPoints.PROTOBUF_DEMO_HOST if IC_CONFIG.get('mode') == 'demo' else EndPoints.PROTOBUF_LIVE_HOST
    print(f"Connecting to {host}...")
    
    client = Client(host, EndPoints.PROTOBUF_PORT, TcpProtocol)
    client.setConnectedCallback(connected)
    client.setDisconnectedCallback(disconnected)
    
    client.startService()
    reactor.run()

if __name__ == '__main__':
    main()
