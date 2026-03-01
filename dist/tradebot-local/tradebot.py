#!/usr/bin/env python3
"""
TradeBot - Paper Trading with Yahoo Finance prices
Uses IC Markets demo account: 9877716 ($20,000)
"""

import requests
import json
import time
import os
from datetime import datetime, timezone
from collections import deque

# Load config
CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config.json')
STATE_FILE = os.path.join(os.path.dirname(__file__), 'paper-trading-state.json')

with open(CONFIG_FILE, 'r') as f:
    APP_CONFIG = json.load(f)

# Trading pairs config
PAIRS = {
    'EURUSD': {'name': 'EUR/USD', 'type': 'forex', 'lot_size': 0.01, 'risk_pips': 15, 'reward_pips': 45},
    'GBPUSD': {'name': 'GBP/USD', 'type': 'forex', 'lot_size': 0.01, 'risk_pips': 20, 'reward_pips': 60},
    'USDJPY': {'name': 'USD/JPY', 'type': 'forex', 'lot_size': 0.1, 'risk_pips': 20, 'reward_pips': 60},
    'AUDUSD': {'name': 'AUD/USD', 'type': 'forex', 'lot_size': 0.01, 'risk_pips': 20, 'reward_pips': 60},
    'USDCAD': {'name': 'USD/CAD', 'type': 'forex', 'lot_size': 0.01, 'risk_pips': 20, 'reward_pips': 60},
    'XAUUSD': {'name': 'Gold', 'type': 'commodity', 'lot_size': 0.01, 'risk_pips': 25, 'reward_pips': 75},
    'XAGUSD': {'name': 'Silver', 'type': 'commodity', 'lot_size': 0.05, 'risk_pips': 20, 'reward_pips': 60},
    'BTCUSD': {'name': 'Bitcoin', 'type': 'crypto', 'lot_size': 0.001, 'risk_pips': 300, 'reward_pips': 900},
    'ETHUSD': {'name': 'Ethereum', 'type': 'crypto', 'lot_size': 0.01, 'risk_pips': 150, 'reward_pips': 450},
}

TRADER_CONFIG = {
    'initial_balance': 20000.0,  # Match demo account
    'max_positions': APP_CONFIG['trading']['max_positions'],
    'check_interval': 60,
    'cooldown_minutes': 10,
}

Yahoo_SYMBOLS = {
    'EURUSD': 'EURUSD=X', 'GBPUSD': 'GBPUSD=X', 'USDJPY': 'USDJPY=X',
    'AUDUSD': 'AUDUSD=X', 'USDCAD': 'USDCAD=X',
    'XAUUSD': 'GC=F', 'XAGUSD': 'SI=F',
    'BTCUSD': 'BTC-USD', 'ETHUSD': 'ETH-USD',
}


def get_price(symbol):
    """Fetch live price from Yahoo Finance"""
    ysym = Yahoo_SYMBOLS.get(symbol, symbol)
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ysym}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        if 'result' not in data['chart'] or not data['chart']['result']:
            return None, None
        price = data['chart']['result'][0]['meta']['regularMarketPrice']
        
        # Get 1h candles
        url2 = f"https://query1.finance.yahoo.com/v8/finance/chart/{ysym}?interval=1h&range=48h"
        r2 = requests.get(url2, headers=headers, timeout=10)
        data2 = r2.json()
        if 'result' not in data2['chart'] or not data2['chart']['result']:
            return price, None
        candles = data2['chart']['result'][0]['indicators']['quote'][0]
        highs = [h for h in candles.get('high', []) if h is not None]
        lows = [l for l in candles.get('low', []) if l is not None]
        closes = [c for c in candles.get('close', []) if c is not None]
        return price, {'highs': highs, 'lows': lows, 'closes': closes}
    except Exception as e:
        print(f"  ⚠️ {symbol} price error: {e}")
        return None, None


def is_market_open():
    """Check if we're in a high volatility session"""
    gmt_hour = datetime.now(timezone.utc).hour
    # London: 8-17, NY: 13-21
    if gmt_hour in range(8, 17) or gmt_hour in range(13, 21):
        return True, "London/NY"
    return False, "off-peak"


def get_signal(symbol, price, data):
    """Simple EMA crossover strategy"""
    closes = data.get('closes', [])
    if len(closes) < 50:
        return 'HOLD', 'warming up'
    
    ema20 = sum(closes[-20:]) / 20
    ema50 = sum(closes[-50:]) / 50
    
    if ema20 > ema50 * 1.001:
        return 'BUY', f'EMA cross (20>{50})'
    elif ema20 < ema50 * 0.999:
        return 'SELL', f'EMA cross (20<{50})'
    return 'HOLD', 'no signal'


class Trader:
    def __init__(self):
        self.balance = TRADER_CONFIG['initial_balance']
        self.positions = {}
        self.closed_trades = []
    
    def open_position(self, symbol, direction, entry, config):
        risk_pct = APP_CONFIG['trading']['risk_per_trade']
        risk_amt = self.balance * risk_pct
        lot_size = config['lot_size']
        
        self.positions[symbol] = {
            'direction': direction,
            'entry': entry,
            'lot_size': lot_size,
            'risk_pips': config['risk_pips'],
            'reward_pips': config['reward_pips'],
            'opened_at': datetime.now().isoformat()
        }
        return True, f"{direction} {config['name']} @ {entry:.5f}"
    
    def check_positions(self, prices):
        closed = []
        for symbol, pos in list(self.positions.items()):
            if symbol not in prices:
                continue
            current = prices[symbol]
            entry = pos['entry']
            direction = pos['direction']
            
            pnl_pct = (current - entry) / entry if direction == 'BUY' else (entry - current) / entry
            pnl = self.balance * 0.1 * pnl_pct  # Simplified
            
            # Check SL/TP
            stop_pct = APP_CONFIG['trading']['stop_loss_pct'] / 100
            tp_pct = APP_CONFIG['trading']['take_profit_pct'] / 100
            
            reason = ''
            if pnl_pct <= -stop_pct:
                reason = 'STOP LOSS'
                pnl = -self.balance * stop_pct
                closed.append((symbol, pnl, reason))
                del self.positions[symbol]
            elif pnl_pct >= tp_pct:
                reason = 'TAKE PROFIT'
                pnl = self.balance * tp_pct
                closed.append((symbol, pnl, reason))
                del self.positions[symbol]
        
        if closed:
            self.balance += sum(c[1] for c in closed)
        return closed
    
    def get_stats(self):
        wins = sum(1 for t in self.closed_trades if t.get('pnl', 0) > 0)
        return {
            'balance': self.balance,
            'open': len(self.positions),
            'total': len(self.closed_trades),
            'wins': wins,
            'losses': len(self.closed_trades) - wins,
            'win_rate': int(wins / len(self.closed_trades) * 100) if self.closed_trades else 0,
        }


def main():
    print("=" * 60)
    print("🤖 TradeBot - Paper Trading (IC Markets Demo)")
    print("=" * 60)
    print(f"Account: {APP_CONFIG['icmarkets']['account_id']}")
    print(f"Balance: ${TRADER_CONFIG['initial_balance']}")
    print(f"Risk:Reward = 1:3")
    print("-" * 60)
    
    trader = Trader()
    
    while True:
        cycle = datetime.now().strftime("%H:%M:%S")
        print(f"\n🔄 [{cycle}] Checking {len(PAIRS)} pairs...")
        
        prices = {}
        signals = {}
        
        for symbol, config in PAIRS.items():
            price, data = get_price(symbol)
            if price and data:
                prices[symbol] = price
                signal, reason = get_signal(symbol, price, data)
                signals[symbol] = signal
                in_open, market = is_market_open()
                print(f"  {config['name']}: {price:.5f} | {signal} ({reason}) @ {market if in_open else 'off-peak'}")
        
        if trader.positions:
            closed = trader.check_positions(prices)
            for symbol, pnl, reason in closed:
                print(f"  ❌ Closed {symbol} | PnL: ${pnl:.2f} ({reason})")
        
        for symbol, config in PAIRS.items():
            if symbol not in signals or signals[symbol] == 'HOLD':
                continue
            if symbol in trader.positions:
                continue
            
            success, msg = trader.open_position(symbol, signals[symbol], prices[symbol], config)
            if success:
                print(f"  ✅ {msg}")
        
        stats = trader.get_stats()
        state_data = {
            'balance': stats['balance'],
            'positions': trader.positions,
            'closed_trades': trader.closed_trades,
            'stats': stats,
            'last_update': datetime.now().isoformat()
        }
        
        with open(STATE_FILE, 'w') as f:
            json.dump(state_data, f, indent=2)
        
        print(f"  📊 Balance: ${stats['balance']} | Open: {stats['open']} | Win Rate: {stats['win_rate']}%")
        
        time.sleep(TRADER_CONFIG['check_interval'])


if __name__ == '__main__':
    main()
