#!/usr/bin/env python3
"""
Kalshi Prediction Market Bot — Employee #006

Upgraded from archive/tradebot_kalshi.py + tradebot_kalshi_paper.py.

Strategy improvements over original:
  - Uses Natalia's news intelligence as signal input (not just static thresholds)
  - Market momentum (price movement over last hour) instead of static YES<35%/NO>65%
  - Position sizing: 5% of balance per trade (was fixed amounts)
  - Trailing exits: close partial at 50% profit
  - Paper mode by default, real trading requires KALSHI_MODE=live + funded account

Kalshi API v2: https://api.elections.kalshi.com/trade-api/v2
"""

import json
import os
import sys
import time
import requests
from datetime import datetime, timezone, timedelta
from collections import defaultdict

sys.path.insert(0, '/root/.openclaw/workspace')
from lib.atomic_write import atomic_json_write
from lib.telegram import send_message as telegram_send
from lib.zeffbot_report import report_task_completed

# ── Config ──
BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
NEWS_INTEL_PATH = '/root/.openclaw/workspace/memory/tradebot-intel-natalia.md'
STATUS_PATH = '/root/.openclaw/workspace/employees/kalshi_status.json'
STATE_PATH = '/root/.openclaw/workspace/employees/kalshi_state.json'
HISTORY_PATH = '/root/.openclaw/workspace/employees/kalshi_history.jsonl'

# Load credentials
KALSHI_EMAIL = os.environ.get('KALSHI_EMAIL', '')
KALSHI_PASSWORD = os.environ.get('KALSHI_PASSWORD', '')
KALSHI_API_KEY = os.environ.get('KALSHI_API_KEY', '')
KALSHI_MODE = os.environ.get('KALSHI_MODE', 'paper')  # 'paper' or 'live'

CONFIG = {
    'max_positions': 5,
    'position_size_pct': 0.05,     # 5% of balance per trade
    'min_trade_amount': 1.00,      # Minimum $1 per trade
    'check_interval': 60,          # 60s between cycles
    'momentum_window': 3600,       # 1 hour for momentum calculation
    'profit_take_pct': 0.50,       # Take profit at 50% gain
    'stop_loss_pct': 0.80,         # Stop loss at 80% loss of position
    'min_score': 3,                # Minimum signal score to trade (out of 5)
}

# Series to monitor
SERIES = [
    'KXHIGHNY', 'KXTECH', 'KXECON', 'KXCLIMATE', 'KXENT',
    'KXCPI', 'KXGDP', 'KXFED', 'KXNFP',
]


class KalshiRunner:
    def __init__(self):
        self.running = True
        self.mode = KALSHI_MODE
        self.auth_token = None
        self.balance = 100.00 if self.mode == 'paper' else 0.0
        self.positions = {}        # ticker -> position data
        self.closed_trades = []
        self.market_cache = {}     # ticker -> market data
        self.price_history = defaultdict(list)  # ticker -> [(timestamp, yes_price)]

    def log(self, msg):
        ts = datetime.now(timezone.utc).strftime('%H:%M:%S')
        print(f"[{ts}] {msg}")

    # ── Authentication ──

    def authenticate(self):
        """Authenticate with Kalshi API for real trading."""
        if self.mode == 'paper':
            self.log("Paper mode — skipping authentication")
            return True

        if KALSHI_API_KEY:
            self.auth_token = KALSHI_API_KEY
            self.log("Authenticated via API key")
            return True

        if not KALSHI_EMAIL or not KALSHI_PASSWORD:
            self.log("ERROR: KALSHI_EMAIL and KALSHI_PASSWORD required for live mode")
            return False

        try:
            resp = requests.post(f"{BASE_URL}/login", json={
                'email': KALSHI_EMAIL,
                'password': KALSHI_PASSWORD,
            }, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                self.auth_token = data.get('token')
                self.log("Authenticated successfully")
                return True
            else:
                self.log(f"Auth failed: {resp.status_code} {resp.text[:100]}")
                return False
        except Exception as e:
            self.log(f"Auth error: {e}")
            return False

    def _headers(self):
        """Get request headers with auth if available."""
        h = {'Content-Type': 'application/json'}
        if self.auth_token:
            h['Authorization'] = f'Bearer {self.auth_token}'
        return h

    # ── Market Data ──

    def get_markets(self, series_ticker=None, status='open', limit=50):
        """Fetch markets from Kalshi API."""
        try:
            params = {'status': status, 'limit': limit}
            if series_ticker:
                params['series_ticker'] = series_ticker
            resp = requests.get(f"{BASE_URL}/markets", params=params, timeout=10)
            if resp.status_code == 200:
                return resp.json().get('markets', [])
        except Exception as e:
            self.log(f"Market fetch error: {e}")
        return []

    def get_orderbook(self, ticker):
        """Fetch order book for a market."""
        try:
            resp = requests.get(f"{BASE_URL}/markets/{ticker}/orderbook", timeout=10)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            pass
        return {}

    def scan_all_markets(self):
        """Scan markets across all monitored series + general open markets."""
        all_markets = {}

        # Series-specific markets
        for series in SERIES:
            markets = self.get_markets(series_ticker=series)
            for m in markets:
                all_markets[m['ticker']] = m

        # General open markets (top by volume)
        general = self.get_markets(limit=100)
        for m in general:
            if m['ticker'] not in all_markets:
                all_markets[m['ticker']] = m

        self.market_cache = all_markets

        # Track price history for momentum
        now = time.time()
        for ticker, m in all_markets.items():
            yes_price = m.get('yes_bid', m.get('yes_price', 50))
            self.price_history[ticker].append((now, yes_price))
            # Keep only last 2 hours of data
            self.price_history[ticker] = [
                (t, p) for t, p in self.price_history[ticker]
                if now - t < 7200
            ]

        return all_markets

    # ── Intelligence ──

    def get_news_sentiment(self):
        """Read Natalia's intelligence brief for market-relevant sentiment."""
        try:
            with open(NEWS_INTEL_PATH) as f:
                content = f.read().lower()
        except Exception:
            return {}

        sentiment = {}
        # Economy keywords
        econ_bull = sum(1 for kw in ['growth', 'strong economy', 'job gains', 'gdp up', 'consumer spending']
                        if kw in content)
        econ_bear = sum(1 for kw in ['recession', 'slowdown', 'layoffs', 'gdp down', 'contraction']
                        if kw in content)
        sentiment['economy'] = 'bullish' if econ_bull > econ_bear else ('bearish' if econ_bear > econ_bull else 'neutral')

        # Fed/rate keywords
        hawk = sum(1 for kw in ['rate hike', 'hawkish', 'tighten', 'inflation high'] if kw in content)
        dove = sum(1 for kw in ['rate cut', 'dovish', 'ease', 'inflation fall'] if kw in content)
        sentiment['fed'] = 'hawkish' if hawk > dove else ('dovish' if dove > hawk else 'neutral')

        # Tech keywords
        tech_bull = sum(1 for kw in ['ai boom', 'tech rally', 'innovation', 'earnings beat'] if kw in content)
        tech_bear = sum(1 for kw in ['tech crash', 'regulation', 'antitrust', 'earnings miss'] if kw in content)
        sentiment['tech'] = 'bullish' if tech_bull > tech_bear else ('bearish' if tech_bear > tech_bull else 'neutral')

        sentiment['confidence'] = min((econ_bull + econ_bear + hawk + dove + tech_bull + tech_bear) / 6.0, 1.0)
        return sentiment

    def calc_momentum(self, ticker):
        """Calculate price momentum over the last hour.
        Returns: float (-1 to +1) where positive = YES price rising.
        """
        history = self.price_history.get(ticker, [])
        if len(history) < 2:
            return 0.0

        now = time.time()
        window = CONFIG['momentum_window']

        # Get price from ~1 hour ago
        old_prices = [(t, p) for t, p in history if now - t >= window * 0.8]
        if not old_prices:
            old_prices = [history[0]]

        old_price = old_prices[-1][1]
        current_price = history[-1][1]

        if old_price == 0:
            return 0.0

        change = (current_price - old_price) / 100.0  # Normalize: 50 cents = 0.5
        return max(-1.0, min(1.0, change))

    # ── Signal Engine ──

    def score_market(self, market, sentiment):
        """Score a market opportunity (0-5 scale).

        Layers:
          1. Value: YES price significantly below/above 50 (mispricing potential)
          2. Momentum: price moving in favorable direction
          3. News: sentiment supports the direction
          4. Volume: higher volume = more liquid/reliable
          5. Time: closer expiry = faster resolution
        """
        ticker = market.get('ticker', '')
        yes_price = market.get('yes_bid', market.get('yes_price', 50))
        volume = market.get('volume', 0)
        title = market.get('title', '').lower()

        score = 0
        direction = None
        reasons = []

        # Layer 1: Value (mispricing)
        if yes_price <= 25:
            score += 1
            direction = 'YES'
            reasons.append(f'Undervalued YES@{yes_price}c')
        elif yes_price >= 75:
            score += 1
            direction = 'NO'
            reasons.append(f'Overvalued YES@{yes_price}c (buy NO)')
        elif yes_price <= 35:
            score += 0.5
            direction = 'YES'
            reasons.append(f'Slightly undervalued YES@{yes_price}c')
        elif yes_price >= 65:
            score += 0.5
            direction = 'NO'
            reasons.append(f'Slightly overvalued YES@{yes_price}c')
        else:
            return 0, None, []  # Too close to 50/50, skip

        # Layer 2: Momentum
        momentum = self.calc_momentum(ticker)
        if direction == 'YES' and momentum > 0.05:
            score += 1
            reasons.append(f'Momentum +{momentum:.2f}')
        elif direction == 'NO' and momentum < -0.05:
            score += 1
            reasons.append(f'Momentum {momentum:.2f}')

        # Layer 3: News sentiment alignment
        if sentiment:
            if 'econ' in ticker.lower() or 'gdp' in title or 'fed' in title or 'cpi' in title:
                if direction == 'YES' and sentiment.get('economy') == 'bullish':
                    score += 1
                    reasons.append('News: economy bullish')
                elif direction == 'NO' and sentiment.get('economy') == 'bearish':
                    score += 1
                    reasons.append('News: economy bearish')
            if 'tech' in ticker.lower() or 'ai' in title or 'tech' in title:
                if direction == 'YES' and sentiment.get('tech') == 'bullish':
                    score += 1
                    reasons.append('News: tech bullish')
                elif direction == 'NO' and sentiment.get('tech') == 'bearish':
                    score += 1
                    reasons.append('News: tech bearish')

        # Layer 4: Volume (liquidity)
        if volume >= 10000:
            score += 1
            reasons.append(f'High volume ({volume:,})')
        elif volume >= 1000:
            score += 0.5
            reasons.append(f'Good volume ({volume:,})')

        # Layer 5: Time to expiry
        exp = market.get('close_time', '')
        if exp:
            try:
                exp_dt = datetime.fromisoformat(exp.replace('Z', '+00:00'))
                hours_left = (exp_dt - datetime.now(timezone.utc)).total_seconds() / 3600
                if 1 <= hours_left <= 24:
                    score += 0.5
                    reasons.append(f'{hours_left:.0f}h to expiry')
            except Exception:
                pass

        return score, direction, reasons

    # ── Trading ──

    def calc_position_size(self):
        """Calculate position size based on balance."""
        size = self.balance * CONFIG['position_size_pct']
        return max(CONFIG['min_trade_amount'], round(size, 2))

    def place_order(self, ticker, direction, amount):
        """Place a trade (paper or real)."""
        market = self.market_cache.get(ticker, {})
        yes_price = market.get('yes_bid', market.get('yes_price', 50))

        if direction == 'YES':
            cost_per_contract = yes_price / 100.0  # cents to dollars
        else:
            cost_per_contract = (100 - yes_price) / 100.0

        if cost_per_contract <= 0:
            return False

        contracts = int(amount / cost_per_contract)
        if contracts < 1:
            return False

        actual_cost = contracts * cost_per_contract

        if actual_cost > self.balance:
            self.log(f"  Insufficient balance for {ticker} (need ${actual_cost:.2f}, have ${self.balance:.2f})")
            return False

        if self.mode == 'live' and self.auth_token:
            # Real order
            try:
                resp = requests.post(f"{BASE_URL}/portfolio/orders", headers=self._headers(), json={
                    'ticker': ticker,
                    'action': 'buy',
                    'side': 'yes' if direction == 'YES' else 'no',
                    'type': 'market',
                    'count': contracts,
                }, timeout=10)
                if resp.status_code not in (200, 201):
                    self.log(f"  Order rejected: {resp.status_code} {resp.text[:100]}")
                    return False
            except Exception as e:
                self.log(f"  Order error: {e}")
                return False

        # Track position
        self.balance -= actual_cost
        self.positions[ticker] = {
            'direction': direction,
            'contracts': contracts,
            'cost_per_contract': cost_per_contract,
            'total_cost': actual_cost,
            'entry_yes_price': yes_price,
            'opened_at': datetime.now(timezone.utc).isoformat(),
            'title': market.get('title', ticker),
        }

        self.log(f"  TRADE: {direction} {ticker} x{contracts} @ {cost_per_contract:.2f} = ${actual_cost:.2f}")
        return True

    def check_exits(self):
        """Check open positions for take-profit / stop-loss exits."""
        closed = []
        for ticker, pos in list(self.positions.items()):
            market = self.market_cache.get(ticker)
            if not market:
                continue

            current_yes = market.get('yes_bid', market.get('yes_price', 50))
            direction = pos['direction']

            # Current value
            if direction == 'YES':
                current_value_per = current_yes / 100.0
            else:
                current_value_per = (100 - current_yes) / 100.0

            current_value = pos['contracts'] * current_value_per
            cost = pos['total_cost']
            pnl_pct = (current_value - cost) / cost if cost > 0 else 0

            # Take profit
            if pnl_pct >= CONFIG['profit_take_pct']:
                pnl = current_value - cost
                self.balance += current_value
                self.log(f"  TP: {ticker} +${pnl:.2f} ({pnl_pct*100:.0f}%)")
                pos['pnl'] = pnl
                pos['close_reason'] = 'take_profit'
                pos['closed_at'] = datetime.now(timezone.utc).isoformat()
                self.closed_trades.append(pos)
                closed.append(ticker)
                self._archive_trade(pos)

            # Stop loss
            elif pnl_pct <= -CONFIG['stop_loss_pct']:
                pnl = current_value - cost
                self.balance += current_value
                self.log(f"  SL: {ticker} ${pnl:.2f} ({pnl_pct*100:.0f}%)")
                pos['pnl'] = pnl
                pos['close_reason'] = 'stop_loss'
                pos['closed_at'] = datetime.now(timezone.utc).isoformat()
                self.closed_trades.append(pos)
                closed.append(ticker)
                self._archive_trade(pos)

            # Market settled (YES price is 0 or 100)
            elif current_yes <= 1 or current_yes >= 99:
                if (direction == 'YES' and current_yes >= 99) or (direction == 'NO' and current_yes <= 1):
                    pnl = pos['contracts'] * 1.0 - cost  # $1 per contract payout
                    self.balance += pos['contracts'] * 1.0
                    self.log(f"  WIN: {ticker} settled +${pnl:.2f}")
                else:
                    pnl = -cost
                    self.log(f"  LOSS: {ticker} settled ${pnl:.2f}")
                pos['pnl'] = pnl
                pos['close_reason'] = 'settled'
                pos['closed_at'] = datetime.now(timezone.utc).isoformat()
                self.closed_trades.append(pos)
                closed.append(ticker)
                self._archive_trade(pos)

        for t in closed:
            del self.positions[t]

    def _archive_trade(self, trade):
        """Append trade to history JSONL."""
        try:
            with open(HISTORY_PATH, 'a') as f:
                f.write(json.dumps(trade) + '\n')
        except Exception:
            pass

    # ── State ──

    def save_state(self):
        """Save current state to disk."""
        pnls = [t.get('pnl', 0) for t in self.closed_trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        state = {
            'mode': self.mode,
            'balance': round(self.balance, 2),
            'positions': self.positions,
            'stats': {
                'total_trades': len(self.closed_trades),
                'wins': len(wins),
                'losses': len(losses),
                'win_rate': round(len(wins) / len(pnls) * 100, 1) if pnls else 0,
                'total_pnl': round(sum(pnls), 2),
                'profit_factor': round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) != 0 else 0,
            },
            'last_update': datetime.now(timezone.utc).isoformat(),
        }

        try:
            atomic_json_write(STATE_PATH, state)
        except Exception as e:
            self.log(f"Save state error: {e}")

        # Status file for dashboard
        try:
            atomic_json_write(STATUS_PATH, {
                'source': 'Kalshi',
                'mode': self.mode.upper(),
                'connected': True,
                'balance': round(self.balance, 2),
                'open_positions': len(self.positions),
                'total_trades': len(self.closed_trades),
                'win_rate': state['stats']['win_rate'],
                'last_update': datetime.now(timezone.utc).isoformat(),
            })
        except Exception:
            pass

    def load_state(self):
        """Restore state from disk if available."""
        try:
            with open(STATE_PATH) as f:
                state = json.load(f)
            self.balance = state.get('balance', self.balance)
            self.positions = state.get('positions', {})
            self.log(f"Restored state: ${self.balance:.2f}, {len(self.positions)} positions")
        except FileNotFoundError:
            self.log("No saved state — starting fresh")
        except Exception as e:
            self.log(f"State load error: {e}")

    # ── Main Loop ──

    def run(self):
        self.log("=" * 60)
        self.log(f"Kalshi Prediction Market Bot — {self.mode.upper()} MODE")
        self.log(f"Strategy: Momentum + News + Value | Position Size: {CONFIG['position_size_pct']*100:.0f}%")
        self.log("=" * 60)

        self.load_state()

        if self.mode == 'live':
            if not self.authenticate():
                self.log("FATAL: Cannot authenticate in live mode")
                return

        cycle = 0
        while self.running:
            cycle += 1
            self.log(f"\n--- Cycle {cycle} ---")

            # Scan markets
            markets = self.scan_all_markets()
            self.log(f"Scanned {len(markets)} open markets")

            # Get news sentiment
            sentiment = self.get_news_sentiment()
            if sentiment:
                self.log(f"  Sentiment: econ={sentiment.get('economy','?')} fed={sentiment.get('fed','?')} tech={sentiment.get('tech','?')}")

            # Check exits first
            self.check_exits()

            # Score and rank opportunities
            opportunities = []
            for ticker, market in markets.items():
                if ticker in self.positions:
                    continue
                score, direction, reasons = self.score_market(market, sentiment)
                if score >= CONFIG['min_score'] and direction:
                    opportunities.append((score, ticker, direction, reasons, market))

            opportunities.sort(reverse=True)  # Best first

            # Take top opportunities (respect position limit)
            trades_made = 0
            for score, ticker, direction, reasons, market in opportunities[:5]:
                if len(self.positions) >= CONFIG['max_positions']:
                    break

                amount = self.calc_position_size()
                if amount < CONFIG['min_trade_amount']:
                    continue

                self.log(f"  Signal: {direction} {ticker} (score {score:.1f}/5)")
                for r in reasons:
                    self.log(f"    - {r}")

                if self.place_order(ticker, direction, amount):
                    trades_made += 1

            # Summary
            pnls = [t.get('pnl', 0) for t in self.closed_trades]
            wins = len([p for p in pnls if p > 0])
            total = len(pnls)
            wr = round(wins / total * 100, 1) if total > 0 else 0
            self.log(f"  Balance: ${self.balance:.2f} | Open: {len(self.positions)} | "
                     f"Closed: {total} | WR: {wr}%")

            self.save_state()

            # Sleep
            for _ in range(CONFIG['check_interval'] // 10):
                if not self.running:
                    break
                time.sleep(10)

        self.log("Kalshi bot stopped")
        self.save_state()


def main():
    bot = KalshiRunner()
    try:
        bot.run()
    except KeyboardInterrupt:
        bot.running = False
        bot.save_state()


if __name__ == '__main__':
    main()
