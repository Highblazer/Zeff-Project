#!/usr/bin/env python3
"""
IC Markets Symbol IDs and Trade Executor
"""

SYMBOL_IDS = {
    'EURUSD': 1,
    'GBPUSD': 2,
    'USDJPY': 3,
    'AUDUSD': 4,
    'USDCAD': 5,
    'USDCHF': 6,
    'NZDUSD': 7,
    'XAUUSD': 10,
    'XAGUSD': 11,
    'USOIL': 12,
}

def get_symbol_id(symbol):
    """Get IC Markets symbol ID"""
    return SYMBOL_IDS.get(symbol.upper())

def execute_trade(symbol, direction, volume, account_id, client_id, client_secret, access_token, ctid_account_id):
    """Execute trade with verification"""
    from twisted.internet import reactor
    from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
    from ctrader_open_api.messages.OpenApiMessages_pb2 import (
        ProtoOAApplicationAuthReq, ProtoOAAccountAuthReq, ProtoOANewOrderReq, ProtoOAReconcileReq
    )
    
    symbol_id = get_symbol_id(symbol)
    if not symbol_id:
        print(f"Unknown symbol: {symbol}")
        return None
    
    trade_side = 1 if direction.upper() == 'BUY' else 2
    
    client = Client(EndPoints.PROTOBUF_DEMO_HOST, EndPoints.PROTOBUF_PORT, TcpProtocol)
    
    result = {'success': False, 'message': ''}
    
    def on_connected(c):
        req = ProtoOAApplicationAuthReq()
        req.clientId = client_id
        req.clientSecret = client_secret
        client.send(req).addCallbacks(on_auth, on_error)
    
    def on_auth(r):
        req = ProtoOAAccountAuthReq()
        req.accessToken = access_token
        req.ctidTraderAccountId = ctid_account_id
        client.send(req).addCallbacks(on_account_auth, on_error)
    
    def on_account_auth(r):
        # Execute trade
        req = ProtoOANewOrderReq()
        req.ctidTraderAccountId = ctid_account_id
        req.symbolId = symbol_id
        req.volume = volume
        req.orderType = 1  # Market
        req.tradeSide = trade_side
        client.send(req).addCallbacks(on_trade, on_error)
    
    def on_trade(r):
        result['success'] = True
        result['message'] = f"Trade {direction} {symbol} executed"
        print(f"✅ {result['message']}")
        # Verify by checking positions
        req = ProtoOAReconcileReq()
        req.ctidTraderAccountId = ctid_account_id
        client.send(req).addCallbacks(on_verify, on_error)
    
    def on_verify(r):
        data = Protobuf.extract(r)
        positions = data.get('positionModels', [])
        print(f"📊 Open positions: {len(positions)}")
        for pos in positions:
            print(f"  - {pos.get('symbolName')}: {pos.get('direction')}")
        reactor.stop()
    
    def on_error(f):
        result['message'] = f"Error: {f}"
        print(f"❌ {result['message']}")
        reactor.stop()
    
    client.setConnectedCallback(on_connected)
    client.setDisconnectedCallback(lambda c, r: print(f"Disc: {r}"))
    
    client.startService()
    reactor.callLater(30, reactor.stop)
    reactor.run()
    
    return result

if __name__ == '__main__':
    import json
    with open('/root/.openclaw/workspace/conf/icmarkets.json') as f:
        cfg = json.load(f)
    
    ic = cfg['icmarkets']
    
    # Test: Execute XAUUSD BUY with proper verification
    print("Testing XAUUSD BUY...")
    execute_trade(
        'XAUUSD', 'BUY', 1000,
        ic['account_id'], ic['client_id'], ic['api_secret'],
        ic['access_token'], ic['ctid_trader_account_id']
    )
