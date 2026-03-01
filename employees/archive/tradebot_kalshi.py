#!/usr/bin/env python3
"""
TradeBot - Kalshi Market Data
Alternative to IC Markets for market data and trading
"""

import json
import time
import requests
from datetime import datetime

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

# Popular series to track
SERIES = {
    'KXHIGHNY': 'Highest temperature in NYC',
    'KXTECH': 'Tech sector',
    'KXECON': 'Economic events',
    'KXCLIMATE': 'Climate events',
    'KXENT': 'Entertainment events',
}

class TradeBotKalshi:
    def __init__(self):
        self.running = True
        self.markets = {}
        
    def log(self, msg):
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{timestamp}] {msg}")
        self.write_status()
        
    def write_status(self):
        try:
            status = {
                'source': 'Kalshi',
                'connected': True,
                'mode': 'MARKET_DATA',
                'markets': len(self.markets),
                'last_update': datetime.now().isoformat()
            }
            with open('/root/.openclaw/workspace/employees/kalshi_status.json', 'w') as f:
                json.dump(status, f)
        except Exception as e:
            print(f"Warning: failed to write Kalshi status: {e}")

    def get_markets(self, series_ticker=None, status='open'):
        """Get markets from Kalshi"""
        try:
            url = f"{BASE_URL}/markets"
            params = {'status': status}
            if series_ticker:
                params['series_ticker'] = series_ticker
            
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            
            if 'markets' in data:
                return data['markets']
        except Exception as e:
            self.log(f"Error fetching markets: {e}")
        return []

    def get_orderbook(self, market_ticker):
        """Get orderbook for a market"""
        try:
            url = f"{BASE_URL}/markets/{market_ticker}/orderbook"
            response = requests.get(url, timeout=10)
            return response.json()
        except Exception as e:
            self.log(f"Error fetching orderbook: {e}")
        return {}

    def scan_markets(self):
        """Scan all open markets"""
        self.log("Scanning markets...")
        
        all_markets = []
        
        # Get markets from popular series
        for series_ticker in SERIES.keys():
            markets = self.get_markets(series_ticker)
            all_markets.extend(markets)
            self.log(f"  {series_ticker}: {len(markets)} markets")
        
        # Get all open markets (limit to 50)
        all_open = self.get_markets(status='open')[:50]
        self.log(f"Total open markets: {len(all_open)}")
        
        # Find interesting markets (high volume)
        interesting = sorted(all_open, key=lambda x: x.get('volume', 0), reverse=True)[:10]
        
        self.log("\nTop 10 markets by volume:")
        for m in interesting:
            ticker = m.get('ticker', 'N/A')
            title = m.get('title', 'N/A')[:40]
            yes_price = m.get('yes_price', 0)
            volume = m.get('volume', 0)
            self.log(f"  {ticker}: {title}")
            self.log(f"    YES: {yes_price}¢ | Volume: {volume:,}")
        
        self.markets = {m['ticker']: m for m in all_open}
        return len(all_open)

    def run(self):
        self.log("=" * 50)
        self.log("TradeBot - KALSHI MODE")
        self.log("Market Data + Trading")
        self.log("=" * 50)
        
        cycle = 0
        while self.running:
            cycle += 1
            self.log(f"\n=== Cycle {cycle} ===")
            
            # Scan markets
            market_count = self.scan_markets()
            
            self.log(f"Monitoring {market_count} markets")
            
            # Sleep 60 seconds between cycles
            for _ in range(6):
                if not self.running:
                    break
                time.sleep(10)
        
        self.log("TradeBot stopped")

def main():
    bot = TradeBotKalshi()
    try:
        bot.run()
    except KeyboardInterrupt:
        bot.running = False

if __name__ == '__main__':
    main()
