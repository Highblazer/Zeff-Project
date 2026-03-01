#!/usr/bin/env python3
"""
TradeBot - Advanced Strategy: Fair Value Gaps + S/R + Market Structure
Risk:Reward 1:3 | Focus on market opens
"""

import requests
import json
import time
from datetime import datetime, timezone
from collections import deque

# Configuration - Updated for 1:3 Risk:Reward + Crypto
PAIRS = {
    # Forex
    'EURUSD': {'name': 'EUR/USD', 'type': 'forex', 'lot_size': 0.01, 'risk_pips': 15, 'reward_pips': 45},
    'GBPUSD': {'name': 'GBP/USD', 'type': 'forex', 'lot_size': 0.01, 'risk_pips': 20, 'reward_pips': 60},
    'USDJPY': {'name': 'USD/JPY', 'type': 'forex', 'lot_size': 0.1, 'risk_pips': 20, 'reward_pips': 60},
    'AUDUSD': {'name': 'AUD/USD', 'type': 'forex', 'lot_size': 0.01, 'risk_pips': 20, 'reward_pips': 60},
    'USDCAD': {'name': 'USD/CAD', 'type': 'forex', 'lot_size': 0.01, 'risk_pips': 20, 'reward_pips': 60},
    # Commodities
    'XAUUSD': {'name': 'Gold', 'type': 'commodity', 'lot_size': 0.01, 'risk_pips': 25, 'reward_pips': 75},
    'XAGUSD': {'name': 'Silver', 'type': 'commodity', 'lot_size': 0.05, 'risk_pips': 20, 'reward_pips': 60},
    # Crypto (24/7 trading)
    'BTCUSD': {'name': 'Bitcoin', 'type': 'crypto', 'lot_size': 0.001, 'risk_pips': 300, 'reward_pips': 900},
    'ETHUSD': {'name': 'Ethereum', 'type': 'crypto', 'lot_size': 0.01, 'risk_pips': 150, 'reward_pips': 450},
    'SOLUSD': {'name': 'Solana', 'type': 'crypto', 'lot_size': 0.1, 'risk_pips': 50, 'reward_pips': 150},
}

CONFIG = {
    'initial_balance': 200.0,
    'max_positions': 5,  # More positions
    'check_interval': 60,  # Check every 1 minute - more aggressive
    'cooldown_minutes': 10,  # Much shorter cooldown - more trades
    'pairs': PAIRS,
}

# Market open times (hour in GMT) - high volatility periods
HIGH_VOLATILITY = {
    'tokyo_open': 0,    # 00:00 GMT
    'london_open': 8,   # 08:00 GMT
    'london_close': 17, # 17:00 GMT  
    'ny_open': 13,      # 13:00 GMT
    'ny_close': 21,     # 21:00 GMT
}


def get_price(symbol):
    """Fetch live price from Yahoo Finance"""
    yahoo_symbols = {
        'EURUSD': 'EURUSD=X', 'GBPUSD': 'GBPUSD=X', 'USDJPY': 'USDJPY=X',
        'AUDUSD': 'AUDUSD=X', 'USDCAD': 'USDCAD=X',
        'XAUUSD': 'GC=F', 'XAGUSD': 'SI=F',
        'BTCUSD': 'BTC-USD', 'ETHUSD': 'ETH-USD', 'SOLUSD': 'SOL-USD',
    }
    
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbols.get(symbol, symbol)}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        
        if 'result' not in data['chart'] or not data['chart']['result']:
            return None, None
            
        price = data['chart']['result'][0]['meta']['regularMarketPrice']
        
        # Get 1-hour candles for structure analysis
        url2 = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbols.get(symbol, symbol)}?interval=1h&range=48h"
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
        return None, None


def find_fvg(closes, highs, lows):
    """
    Find Fair Value Gaps
    Bullish FVG: candle[i-2].high < candle[i].low (gap up)
    Bearish FVG: candle[i-2].low > candle[i].high (gap down)
    """
    fvgs = []
    
    if len(closes) < 3:
        return fvgs
    
    for i in range(2, len(closes)):
        # Bullish FVG (potential support)
        if highs[i-2] < lows[i]:
            fvg = {
                'type': 'bullish',
                'top': lows[i],
                'bottom': highs[i-2],
                'mid': (lows[i] + highs[i-2]) / 2,
                'strength': lows[i] - highs[i-2]  # Gap size
            }
            fvgs.append(fvg)
        
        # Bearish FVG (potential resistance)
        if lows[i-2] > highs[i]:
            fvg = {
                'type': 'bearish',
                'top': lows[i-2],
                'bottom': highs[i],
                'mid': (highs[i] + lows[i-2]) / 2,
                'strength': lows[i-2] - highs[i]
            }
            fvgs.append(fvg)
    
    return fvgs[-5:]  # Last 5 FVGs


def find_sr_levels(highs, lows, closes):
    """Find support and resistance levels"""
    if len(closes) < 20:
        return None, None
    
    # Recent swing high/low
    recent_high = max(highs[-20:])
    recent_low = min(lows[-20:])
    
    # Current price position
    current = closes[-1]
    
    # Dynamic S/R based on price action
    resistance = None
    support = None
    
    # Look for resistance above current price
    for h in highs[-10:]:
        if h > current and (resistance is None or h < resistance):
            resistance = h
    
    # Look for support below current price
    for l in lows[-10:]:
        if l < current and (support is None or l > support):
            support = l
    
    return support, resistance


# Fibonacci retracement levels
FIB_LEVELS = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]


def find_fib_levels(highs, lows):
    """Calculate Fibonacci retracement levels from recent swing"""
    if len(highs) < 20 or len(lows) < 20:
        return {}
    
    # Find swing high and low
    swing_high = max(highs[-20:])
    swing_low = min(lows[-20:])
    
    diff = swing_high - swing_low
    
    levels = {}
    for fib in FIB_LEVELS:
        levels[fib] = swing_low + (diff * fib)
    
    return levels


def is_at_fib_support(current, fib_levels):
    """Check if price is near a Fibonacci support level"""
    for level in [0.618, 0.5, 0.382, 0.236]:
        if level in fib_levels:
            # Price within 0.3% of fib level = support zone
            if abs(current - fib_levels[level]) / current < 0.003:
                return level, 'support'
    return None, None


def is_at_fib_resistance(current, fib_levels):
    """Check if price is near a Fibonacci resistance level"""
    for level in [0.786, 0.618, 0.5, 0.382]:
        if level in fib_levels:
            if abs(current - fib_levels[level]) / current < 0.003:
                return level, 'resistance'
    return None, None


def is_market_open():
    """Check for high volatility periods - now more flexible"""
    current_hour = datetime.now(timezone.utc).hour
    
    # Market opens (high volatility)
    for market, open_hour in HIGH_VOLATILITY.items():
        if abs(current_hour - open_hour) <= 1:
            return True, market
    
    # Also during major overlaps
    if 8 <= current_hour <= 17:  # London session
        return True, "london_session"
    if 13 <= current_hour <= 21:  # NY session
        return True, "ny_session"
    
    # Crypto trades 24/7 - always available
    return True, "always_active"


def calculate_ema(prices, period):
    if len(prices) < period:
        return None
    multiplier = 2 / (period + 1)
    ema = prices[0]
    for p in prices[1:]:
        ema = (p - ema) * multiplier + ema
    return ema


def get_signal(symbol, price, data):
    """Advanced signal - active throughout the day with quality setups"""
    
    if not data or len(data.get('closes', [])) < 30:
        return 'HOLD', 'Insufficient data'
    
    closes = data['closes']
    highs = data['highs']
    lows = data['lows']
    
    in_session, session_name = is_market_open()
    
    fvgs = find_fvg(closes, highs, lows)
    support, resistance = find_sr_levels(highs, lows, closes)
    
    ema_20 = calculate_ema(closes, 20)
    ema_50 = calculate_ema(closes, 50)
    
    current_price = closes[-1]
    trend = 'bullish' if ema_20 and ema_50 and ema_20 > ema_50 else 'bearish'
    
    signals = []
    
    # 1. FVG + S/R confirmation - AGGRESSIVE
    for fvg in fvgs:
        if fvg['type'] == 'bullish':
            # Any FVG near support
            if current_price < fvg['top'] and current_price > fvg['bottom']:
                if support and current_price > support:
                    signals.append(('BUY', f'FVG + Support {session_name}'))
        elif fvg['type'] == 'bearish':
            if current_price > fvg['bottom'] and current_price < fvg['top']:
                if resistance and current_price < resistance:
                    signals.append(('SELL', f'FVG + Resistance {session_name}'))
    
    # 2. ANY trend pullback to EMA - AGGRESSIVE
    if ema_20 and ema_50:
        # Strong trend
        if ema_20 > ema_50:  # Bullish
            if current_price >= ema_20 * 0.998:  # Close to EMA
                signals.append(('BUY', f'Trend pullback {session_name}'))
        else:  # Bearish
            if current_price <= ema_20 * 1.002:
                signals.append(('SELL', f'Trend pullback {session_name}'))
    
    # 3. Fibonacci - AGGRESSIVE - trigger on ANY fib level
    fib_levels = find_fib_levels(highs, lows)
    if fib_levels:
        # Check all fib levels
        for fib, level in fib_levels.items():
            if abs(current_price - level) / current_price < 0.005:  # 0.5% tolerance
                if trend == 'bullish' and level < current_price:
                    signals.append(('BUY', f'Fib {fib} Support'))
                elif trend == 'bearish' and level > current_price:
                    signals.append(('SELL', f'Fib {fib} Resistance'))
    
    # 4. Breakout - AGGRESSIVE
    if len(closes) >= 5:
        high_5 = max(closes[-5:])
        low_5 = min(closes[-5:])
        range_pct = (high_5 - low_5) / low_5
        
        if range_pct > 0.003:  # > 0.3% move - more sensitive
            if current_price > high_5:
                signals.append(('BUY', f'Breakout {session_name}'))
            elif current_price < low_5:
                signals.append(('SELL', f'Breakout {session_name}'))
    
    # 5. Simple trend - ALWAYS
    if ema_20 and ema_50:
        if ema_20 > ema_50:  # Uptrend
            signals.append(('BUY', f'Uptrend {session_name}'))
        else:
            signals.append(('SELL', f'Downtrend {session_name}'))
    if in_session and len(closes) >= 10:
        high_10 = max(closes[-10:])
        low_10 = min(closes[-10:])
        if current_price > high_10:
            signals.append(('BUY', f'Breakout up {session_name}'))
        elif current_price < low_10:
            signals.append(('SELL', f'Breakout down {session_name}'))
    
    if signals:
        # Return first valid signal - AGGRESSIVE
        return signals[0]
    
    return 'HOLD', 'No setup'


class Trader:
    def __init__(self):
        self.balance = CONFIG['initial_balance']
        self.positions = {}
        self.closed_trades = []
        self.last_trade_time = {}  # {symbol: last_trade_time}
        
    def open_position(self, symbol, direction, entry_price, config):
        # Check cooldown
        if symbol in self.last_trade_time:
            last = self.last_trade_time[symbol]
            if (datetime.now() - last).total_seconds() < CONFIG['cooldown_minutes'] * 60:
                return False, "Cooldown active"
        
        if len(self.positions) >= CONFIG['max_positions']:
            return False, "Max positions"
        
        # Calculate SL and TP based on 1:3 ratio
        risk_pips = config['risk_pips']
        reward_pips = config['reward_pips']
        
        # Adjust for JPY and commodities
        multiplier = 0.0001
        if 'JPY' in symbol:
            multiplier = 0.01
        elif symbol.startswith('XAU') or symbol.startswith('XAG'):
            multiplier = 0.01
        
        if direction == 'BUY':
            sl = entry_price - (risk_pips * multiplier)
            tp = entry_price + (reward_pips * multiplier)
        else:
            sl = entry_price + (risk_pips * multiplier)
            tp = entry_price - (reward_pips * multiplier)
        
        self.positions[symbol] = {
            'direction': direction,
            'entry_price': entry_price,
            'stop_loss': sl,
            'take_profit': tp,
            'lot_size': config['lot_size'],
            'risk_pips': risk_pips,
            'open_time': datetime.now().isoformat(),
        }
        
        self.last_trade_time[symbol] = datetime.now()
        return True, f"{direction} {config['name']} @ {entry_price:.5f}"
    
    def check_positions(self, prices):
        to_close = []
        
        for symbol, pos in list(self.positions.items()):
            if symbol not in prices:
                continue
            
            price = prices[symbol]
            should_close = False
            reason = ""
            
            # Check SL/TP
            if pos['direction'] == 'BUY':
                if price <= pos['stop_loss']:
                    should_close = True
                    reason = 'STOP_LOSS'
                elif price >= pos['take_profit']:
                    should_close = True
                    reason = 'TAKE_PROFIT'
            else:
                if price >= pos['stop_loss']:
                    should_close = True
                    reason = 'STOP_LOSS'
                elif price <= pos['take_profit']:
                    should_close = True
                    reason = 'TAKE_PROFIT'
            
            if should_close:
                # Calculate PnL
                if pos['direction'] == 'BUY':
                    pnl = (price - pos['entry_price']) * pos['lot_size'] * 100000
                else:
                    pnl = (pos['entry_price'] - price) * pos['lot_size'] * 100000
                
                # Adjust for JPY/commodities
                if 'JPY' in symbol or symbol.startswith('XAU') or symbol.startswith('XAG'):
                    pnl = pnl / 100
                
                pnl -= pos['lot_size'] * 7  # Commission
                self.balance += pnl
                
                self.closed_trades.append({
                    'symbol': symbol,
                    **pos,
                    'exit_price': price,
                    'close_time': datetime.now().isoformat(),
                    'pnl': pnl,
                    'exit_reason': reason
                })
                to_close.append((symbol, pnl, reason))
                del self.positions[symbol]
        
        return to_close
    
    def get_stats(self):
        if not self.closed_trades:
            return {
                'balance': round(self.balance, 2),
                'open': len(self.positions),
                'total': 0, 'wins': 0, 'losses': 0,
                'win_rate': 0, 'total_pnl': 0
            }
        
        wins = [t for t in self.closed_trades if t['pnl'] > 0]
        losses = [t for t in self.closed_trades if t['pnl'] <= 0]
        
        return {
            'balance': round(self.balance, 2),
            'open': len(self.positions),
            'total': len(self.closed_trades),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': round(len(wins) / len(self.closed_trades) * 100, 1),
            'total_pnl': round(sum(t['pnl'] for t in self.closed_trades), 2)
        }


def send_alert(message):
    """Send alert via OpenClaw"""
    try:
        import urllib.request
        data = json.dumps({
            "message": message,
            "target": "telegram:7425642116"
        }).encode()
        req = urllib.request.Request(
            "http://localhost:8080/message/send",
            data=data,
            headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=5)
    except:
        pass


def main():
    print("=" * 60)
    print("🤖 TradeBot - Advanced Strategy (FVG + S/R + 1:3 Risk)")
    print("=" * 60)
    print(f"Balance: ${CONFIG['initial_balance']}")
    print(f"Risk:Reward = 1:3")
    print(f"Market opens: Tokyo, London, New York")
    print("-" * 60)
    
    trader = Trader()
    
    while True:
        cycle = datetime.now().strftime("%H:%M:%S")
        print(f"\n🔄 [{cycle}] Checking {len(PAIRS)} pairs...")
        
        prices = {}
        signals = {}
        
        # Get prices for all pairs
        for symbol, config in PAIRS.items():
            price, data = get_price(symbol)
            if price and data:
                prices[symbol] = price
                signal, reason = get_signal(symbol, price, data)
                signals[symbol] = signal
                
                in_open, market = is_market_open()
                print(f"  {config['name']}: {price:.5f} | {signal} ({reason}) @ {market if in_open else 'off-peak'}")
        
        # Check existing positions
        if trader.positions:
            closed = trader.check_positions(prices)
            for symbol, pnl, reason in closed:
                print(f"  ❌ Closed {symbol} | PnL: ${pnl:.2f} ({reason})")
                send_alert(f"🚨 TRADE CLOSED\n{symbol}\nPnL: ${pnl:.2f} ({reason})\nBalance: ${trader.balance:.2f}")
        
        # Check for new signals
        for symbol, config in PAIRS.items():
            if symbol not in signals:
                continue
            
            signal = signals[symbol]
            if signal == 'HOLD':
                continue
            
            if symbol in trader.positions:
                continue
            
            success, msg = trader.open_position(symbol, signal, prices[symbol], config)
            if success:
                print(f"  ✅ {msg}")
                risk = config['risk_pips']
                reward = config['reward_pips']
                send_alert(f"🚀 TRADE OPENED\n{msg}\nSL: {risk} pips | TP: {reward} pips (1:3)")
        
        # Save state
        stats = trader.get_stats()
        
        state_data = {
            'balance': stats['balance'],
            'positions': trader.positions,
            'closed_trades': trader.closed_trades,
            'stats': stats,
            'last_update': datetime.now().isoformat()
        }
        
        for path in ['/root/.openclaw/workspace/employees/paper-trading-state.json',
                     '/root/.openclaw/workspace/paper-trading-state.json']:
            try:
                with open(path, 'w') as f:
                    json.dump(state_data, f, indent=2)
            except:
                pass
        
        print(f"  📊 Balance: ${stats['balance']} | Open: {stats['open']} | Closed: {stats['total']} | Win Rate: {stats['win_rate']}%")
        
        time.sleep(CONFIG['check_interval'])


if __name__ == '__main__':
    main()
