#!/usr/bin/env python3
"""
TradeBot - Kalshi Paper Trading (Simulated)
Practices trading strategies with virtual $1000
"""

import json
import time
import random
from datetime import datetime

class PaperTradingBot:
    def __init__(self):
        self.running = True
        self.balance = 1000.00
        self.trades = []
        self.positions = {}
        
    def log(self, msg):
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{timestamp}] {msg}")
        
    def write_status(self):
        try:
            status = {
                'source': 'Kalshi',
                'mode': 'PAPER_TRADING',
                'balance': round(self.balance, 2),
                'positions': self.positions,
                'trades_count': len(self.trades),
                'wins': sum(1 for t in self.trades if t.get('pnl', 0) > 0),
                'losses': sum(1 for t in self.trades if t.get('pnl', 0) < 0),
                'last_update': datetime.now().isoformat()
            }
            with open('/root/.openclaw/workspace/employees/kalshi_paper_status.json', 'w') as f:
                json.dump(status, f, indent=2)
        except Exception as e:
            print(f"Warning: failed to write paper trading status: {e}")

    def simulate_market_scan(self):
        """Simulate finding trading opportunities"""
        # Simulate finding interesting markets
        opportunities = [
            {'ticker': 'KX-ECON-001', 'title': 'Fed cuts rates by 50bps', 'prob': random.randint(20, 40)},
            {'ticker': 'KX-TECH-002', 'title': 'AI sector up 5%', 'prob': random.randint(30, 50)},
            {'ticker': 'KX-SPORTS-003', 'title': 'Lakers win tonight', 'prob': random.randint(25, 45)},
            {'ticker': 'KX-POLITICS-004', 'title': 'Bill passes Senate', 'prob': random.randint(35, 55)},
            {'ticker': 'KX-WEATHER-005', 'title': 'NYC high > 75F', 'prob': random.randint(40, 60)},
        ]
        return opportunities

    def make_trade_decision(self, market):
        """Decide whether to trade based on probability"""
        prob = market['prob']
        
        # Strategy: Buy YES if probability is low (undervalued)
        # Strategy: Buy NO if probability is high (overvalued)
        
        if prob < 35:
            return 'BUY_YES', prob
        elif prob > 65:
            return 'BUY_NO', 100 - prob
        return None, None

    def execute_paper_trade(self, action, price, ticker, title):
        """Execute a paper trade"""
        cost = price  # Simulated cost in dollars
        
        if cost > self.balance:
            self.log(f"❌ Insufficient balance for {ticker}")
            return False
        
        self.balance -= cost
        
        trade = {
            'id': len(self.trades),
            'ticker': ticker,
            'action': action,
            'price': price,
            'cost': cost,
            'title': title,
            'timestamp': datetime.now().isoformat(),
            'status': 'OPEN'
        }
        
        self.trades.append(trade)
        self.positions[ticker] = trade
        
        self.log(f"✅ PAPER TRADE: {action} {ticker} @ ${price:.2f}")
        self.log(f"   Balance: ${self.balance:.2f}")
        return True

    def close_position(self, ticker):
        """Close position with random outcome"""
        if ticker not in self.positions:
            return
            
        trade = self.positions[ticker]
        
        # Simulate outcome (70% win rate for good trades)
        win = random.random() < 0.7
        
        if win:
            pnl = trade['cost'] * 1.5  # 50% gain
            self.balance += trade['cost'] + pnl
            self.log(f"✅ WIN: {ticker} +${pnl:.2f}")
        else:
            pnl = -trade['cost']  # Lose the stake
            self.balance += trade['cost'] + pnl
            self.log(f"❌ LOSS: {ticker} ${pnl:.2f}")
        
        trade['status'] = 'CLOSED'
        trade['pnl'] = pnl
        del self.positions[ticker]

    def run(self):
        self.log("=" * 50)
        self.log("TradeBot - KALSHI PAPER TRADING (Simulated)")
        self.log(f"Starting Balance: ${self.balance:.2f}")
        self.log("=" * 50)
        
        cycle = 0
        while self.running:
            cycle += 1
            self.log(f"\n=== Cycle {cycle} ===")
            
            # Scan for opportunities
            markets = self.simulate_market_scan()
            self.log(f"Scanning {len(markets)} markets...")
            
            # Make trades
            trades_made = 0
            for market in markets:
                if len(self.positions) >= 3:  # Max 3 positions
                    break
                    
                action, price = self.make_trade_decision(market)
                if action and price > 5:  # Min $5 trade
                    if self.execute_paper_trade(action, price, market['ticker'], market['title']):
                        trades_made += 1
            
            # Close random position occasionally
            if self.positions and random.random() < 0.2:
                ticker = random.choice(list(self.positions.keys()))
                self.close_position(ticker)
            
            # Summary
            self.log(f"\n📊 Summary:")
            self.log(f"   Balance: ${self.balance:.2f}")
            self.log(f"   Open Positions: {len(self.positions)}")
            self.log(f"   Total Trades: {len(self.trades)}")
            wins = sum(1 for t in self.trades if t.get('pnl', 0) > 0)
            losses = sum(1 for t in self.trades if t.get('pnl', 0) < 0)
            if wins + losses > 0:
                win_rate = wins / (wins + losses) * 100
                self.log(f"   Win Rate: {win_rate:.1f}%")
            
            self.write_status()
            
            # Sleep 30 seconds
            for _ in range(3):
                if not self.running:
                    break
                time.sleep(10)
        
        self.log("Trading bot stopped")

def main():
    bot = PaperTradingBot()
    try:
        bot.run()
    except KeyboardInterrupt:
        bot.running = False

if __name__ == '__main__':
    main()
