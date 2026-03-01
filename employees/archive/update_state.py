#!/usr/bin/env python3
"""Auto-update trading state for dashboard - preserves positions"""

import json
from datetime import datetime

STATE_FILE = '/root/.openclaw/workspace/employees/paper-trading-state.json'

def update_state():
    """Update trading state - preserves existing positions"""
    
    try:
        with open(STATE_FILE, 'r') as f:
            state = json.load(f)
    except Exception as e:
        print(f"Warning: failed to load state file, using defaults: {e}")
        state = {"balance": 20000, "positions": {}, "closed_trades": [], "bots": {}}
    
    # Preserve existing positions and balance
    positions = state.get('positions', {})
    balance = state.get('balance', 20000)
    stats = state.get('stats', {})
    closed_trades = state.get('closed_trades', [])
    
    # Update timestamp
    state['last_update'] = datetime.now().isoformat()
    
    # Set bots
    state['bots'] = {
        'tradebot': {
            'name': 'TradeBot',
            'status': 'running',
            'strategy': 'conservative',
            'markets': ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD']
        },
        'ego': {
            'name': 'EgoTradingBot',
            'status': 'running', 
            'strategy': 'gap_hunter',
            'risk_per_trade': 0.10,
            'markets': ['EURUSD', 'USDCHF', 'GBPNZD', 'NZDUSD', 'USDJPY', 'XAUUSD', 'AUDUSD', 'XAGUSD', 'USDCAD', 'BTCUSD']
        }
    }
    
    # Restore preserved data
    state['positions'] = positions
    state['balance'] = balance
    state['stats'] = stats
    state['closed_trades'] = closed_trades
    
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)
    
    print(f"State updated: {state['last_update']}")

if __name__ == '__main__':
    update_state()
