#!/usr/bin/env python3
"""
Polymarket Prediction Market Bot — Employee #007

Trades on Polymarket using the CLOB API + Natalia's intelligence engine.
Polymarket uses Polygon blockchain + USDC for settlement.

Strategy: Same intelligence-driven approach as Kalshi bot:
  - News sentiment from Natalia's research
  - Market momentum (price changes over time)
  - Value identification (mispriced outcomes)
  - Volume/liquidity filtering

Modes:
  - paper (default): Track positions virtually, no real orders
  - live: Place real orders via CLOB API (requires API key + USDC funding)

Env vars:
  POLYMARKET_PRIVATE_KEY  — Polygon wallet private key (for deriving API creds)
  POLYMARKET_API_KEY, POLYMARKET_API_SECRET, POLYMARKET_PASSPHRASE — or set directly
  POLYMARKET_MODE=paper|live
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from collections import defaultdict

sys.path.insert(0, '/root/.openclaw/workspace')
from lib.polymarket_api import PolymarketClient
from lib.atomic_write import atomic_json_write
from lib.telegram import send_message as telegram_send

# ── Config ──
NEWS_INTEL_PATH = '/root/.openclaw/workspace/memory/tradebot-intel-natalia.md'
STATE_PATH = '/root/.openclaw/workspace/employees/polymarket_state.json'
STATUS_PATH = '/root/.openclaw/workspace/employees/polymarket_status.json'
HISTORY_PATH = '/root/.openclaw/workspace/employees/polymarket_history.jsonl'

POLYMARKET_MODE = os.environ.get('POLYMARKET_MODE', 'paper')

CONFIG = {
    'max_positions': 5,
    'position_size_pct': 0.05,     # 5% of balance per trade
    'min_trade_amount': 1.00,
    'check_interval': 120,         # 2 min between cycles (Polymarket is slower)
    'profit_take_pct': 0.40,       # Take profit at 40% gain
    'stop_loss_pct': 0.70,         # Stop loss at 70% loss
    'min_score': 3,                # Minimum score to trade (out of 5)
    'min_liquidity': 1000,         # Minimum 24h volume in USD
}


class PolymarketRunner:
    def __init__(self):
        self.running = True
        self.mode = POLYMARKET_MODE

        # Initialize API client
        api_key = os.environ.get('POLYMARKET_API_KEY')
        api_secret = os.environ.get('POLYMARKET_API_SECRET')
        passphrase = os.environ.get('POLYMARKET_PASSPHRASE')
        self.private_key = os.environ.get('POLYMARKET_PRIVATE_KEY', '')
        self.client = PolymarketClient(api_key, api_secret, passphrase)

        self.balance = 100.00 if self.mode == 'paper' else 0.0
        self.positions = {}        # condition_id -> position data
        self.closed_trades = []
        self.market_cache = {}     # condition_id -> market data
        self.price_history = defaultdict(list)  # token_id -> [(timestamp, price)]

    def log(self, msg):
        ts = datetime.now(timezone.utc).strftime('%H:%M:%S')
        print(f"[{ts}] {msg}")

    # ── Market Discovery ──

    def scan_markets(self):
        """Scan Polymarket for active markets, sorted by volume."""
        markets = self.client.get_markets(limit=100, active=True)
        if not markets:
            self.log("No markets returned")
            return {}

        result = {}
        for m in markets:
            cid = m.get('condition_id') or m.get('id', '')
            if not cid:
                continue
            result[cid] = m

            # Track price history for YES token
            tokens = m.get('tokens', [])
            if tokens:
                yes_token = tokens[0] if tokens[0].get('outcome', '').upper() == 'YES' else (tokens[1] if len(tokens) > 1 else tokens[0])
                token_id = yes_token.get('token_id', '')
                price = float(yes_token.get('price', 0.5))
                if token_id:
                    now = time.time()
                    self.price_history[token_id].append((now, price))
                    # Keep 2 hours
                    self.price_history[token_id] = [
                        (t, p) for t, p in self.price_history[token_id]
                        if now - t < 7200
                    ]

        self.market_cache = result
        return result

    # ── Intelligence ──

    def get_news_sentiment(self):
        """Read Natalia's intelligence for market-relevant sentiment."""
        try:
            with open(NEWS_INTEL_PATH) as f:
                content = f.read().lower()
        except Exception:
            return {}

        sentiment = {}
        categories = {
            'politics': (['election', 'trump', 'biden', 'congress', 'senate', 'vote', 'policy'], []),
            'crypto': (['bitcoin', 'ethereum', 'crypto', 'blockchain', 'defi'], []),
            'economy': (['gdp', 'inflation', 'fed', 'rate', 'employment', 'recession'], []),
            'tech': (['ai', 'tech', 'startup', 'silicon valley', 'openai', 'google'], []),
            'geopolitics': (['war', 'conflict', 'sanctions', 'trade war', 'nato'], []),
        }

        for category, (keywords, _) in categories.items():
            hits = sum(1 for kw in keywords if kw in content)
            sentiment[category] = {
                'relevance': min(hits / 3.0, 1.0),
                'hits': hits,
            }

        return sentiment

    def calc_momentum(self, token_id):
        """Calculate price momentum over the last hour."""
        history = self.price_history.get(token_id, [])
        if len(history) < 2:
            return 0.0

        now = time.time()
        old = [p for t, p in history if now - t >= 3000]
        if not old:
            old = [history[0][1]]
        current = history[-1][1]
        old_price = old[-1]

        if old_price == 0:
            return 0.0
        return max(-1.0, min(1.0, current - old_price))

    # ── Signal Engine ──

    def score_market(self, market, sentiment):
        """Score a Polymarket opportunity (0-5).

        Layers:
          1. Value: price far from 0.5 (mispricing potential)
          2. Momentum: price trending favorably
          3. News relevance: sentiment matches market category
          4. Liquidity: sufficient volume
          5. Spread: tight spread = efficient market
        """
        question = market.get('question', '').lower()
        tokens = market.get('tokens', [])
        volume_24h = float(market.get('volume24hr', 0) or 0)

        if not tokens or volume_24h < CONFIG['min_liquidity']:
            return 0, None, None, []

        # Find YES/NO tokens
        yes_token = None
        no_token = None
        for t in tokens:
            outcome = t.get('outcome', '').upper()
            if outcome == 'YES':
                yes_token = t
            elif outcome == 'NO':
                no_token = t

        if not yes_token:
            yes_token = tokens[0]
        if not no_token and len(tokens) > 1:
            no_token = tokens[1]

        yes_price = float(yes_token.get('price', 0.5))
        yes_token_id = yes_token.get('token_id', '')

        score = 0
        direction = None
        reasons = []

        # Layer 1: Value
        if yes_price <= 0.25:
            score += 1
            direction = 'YES'
            reasons.append(f'Undervalued YES@{yes_price:.2f}')
        elif yes_price >= 0.75:
            score += 1
            direction = 'NO'
            reasons.append(f'Overvalued YES@{yes_price:.2f} (buy NO)')
        elif yes_price <= 0.35:
            score += 0.5
            direction = 'YES'
            reasons.append(f'Slightly undervalued YES@{yes_price:.2f}')
        elif yes_price >= 0.65:
            score += 0.5
            direction = 'NO'
            reasons.append(f'Slightly overvalued YES@{yes_price:.2f}')
        else:
            return 0, None, None, []

        # Layer 2: Momentum
        momentum = self.calc_momentum(yes_token_id)
        if direction == 'YES' and momentum > 0.03:
            score += 1
            reasons.append(f'Momentum +{momentum:.3f}')
        elif direction == 'NO' and momentum < -0.03:
            score += 1
            reasons.append(f'Momentum {momentum:.3f}')

        # Layer 3: News relevance
        if sentiment:
            for category, info in sentiment.items():
                if info['relevance'] > 0.3 and any(kw in question for kw in [category] + {
                    'politics': ['election', 'president', 'vote', 'congress'],
                    'crypto': ['bitcoin', 'ethereum', 'crypto'],
                    'economy': ['gdp', 'inflation', 'fed', 'rate'],
                    'tech': ['ai', 'tech', 'google', 'apple'],
                    'geopolitics': ['war', 'conflict', 'russia', 'china'],
                }.get(category, [])):
                    score += 1
                    reasons.append(f'News: {category} relevant ({info["hits"]} hits)')
                    break

        # Layer 4: Liquidity
        if volume_24h >= 50000:
            score += 1
            reasons.append(f'High volume (${volume_24h:,.0f})')
        elif volume_24h >= 5000:
            score += 0.5
            reasons.append(f'Good volume (${volume_24h:,.0f})')

        # Layer 5: Spread (check orderbook)
        if yes_token_id:
            book = self.client.get_orderbook(yes_token_id)
            spread = book.get('spread', 1.0)
            if spread <= 0.02:
                score += 0.5
                reasons.append(f'Tight spread ({spread:.3f})')

        # Determine which token to trade
        target_token = yes_token if direction == 'YES' else no_token
        target_token_id = target_token.get('token_id', '') if target_token else ''

        return score, direction, target_token_id, reasons

    # ── Trading ──

    def calc_position_size(self):
        """Calculate position size."""
        size = self.balance * CONFIG['position_size_pct']
        return max(CONFIG['min_trade_amount'], round(size, 2))

    def place_trade(self, condition_id, direction, token_id, amount, market):
        """Place a trade (paper or real)."""
        tokens = market.get('tokens', [])
        target_token = None
        for t in tokens:
            if t.get('token_id') == token_id:
                target_token = t
                break

        if not target_token:
            return False

        price = float(target_token.get('price', 0.5))
        if price <= 0:
            return False

        shares = amount / price
        actual_cost = shares * price

        if actual_cost > self.balance:
            self.log(f"  Insufficient balance (need ${actual_cost:.2f})")
            return False

        if self.mode == 'live' and self.client.api_key:
            result = self.client.place_order(token_id, 'BUY', price, shares)
            if not result:
                return False

        self.balance -= actual_cost
        self.positions[condition_id] = {
            'direction': direction,
            'token_id': token_id,
            'shares': shares,
            'entry_price': price,
            'total_cost': actual_cost,
            'question': market.get('question', ''),
            'opened_at': datetime.now(timezone.utc).isoformat(),
        }

        self.log(f"  TRADE: {direction} {market.get('question', '')[:50]}")
        self.log(f"    {shares:.1f} shares @ ${price:.3f} = ${actual_cost:.2f}")
        return True

    def check_exits(self):
        """Check positions for TP/SL/settlement."""
        closed = []
        for cid, pos in list(self.positions.items()):
            market = self.market_cache.get(cid)
            if not market:
                continue

            # Get current price for our token
            tokens = market.get('tokens', [])
            current_price = None
            for t in tokens:
                if t.get('token_id') == pos['token_id']:
                    current_price = float(t.get('price', 0))
                    break

            if current_price is None:
                continue

            current_value = pos['shares'] * current_price
            cost = pos['total_cost']
            pnl_pct = (current_value - cost) / cost if cost > 0 else 0

            close_reason = None
            if pnl_pct >= CONFIG['profit_take_pct']:
                close_reason = 'take_profit'
            elif pnl_pct <= -CONFIG['stop_loss_pct']:
                close_reason = 'stop_loss'
            elif current_price >= 0.99 or current_price <= 0.01:
                close_reason = 'settled'

            if close_reason:
                pnl = current_value - cost
                self.balance += current_value
                result = 'WIN' if pnl > 0 else 'LOSS'
                self.log(f"  {result}: {pos['question'][:40]} ${pnl:+.2f} ({close_reason})")

                pos['pnl'] = pnl
                pos['close_reason'] = close_reason
                pos['closed_at'] = datetime.now(timezone.utc).isoformat()
                self.closed_trades.append(pos)
                closed.append(cid)

                try:
                    with open(HISTORY_PATH, 'a') as f:
                        f.write(json.dumps(pos) + '\n')
                except Exception:
                    pass

        for cid in closed:
            del self.positions[cid]

    # ── State ──

    def save_state(self):
        """Persist state to disk."""
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
            },
            'last_update': datetime.now(timezone.utc).isoformat(),
        }

        try:
            atomic_json_write(STATE_PATH, state)
        except Exception as e:
            self.log(f"Save error: {e}")

        try:
            atomic_json_write(STATUS_PATH, {
                'source': 'Polymarket',
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
        """Restore from disk."""
        try:
            with open(STATE_PATH) as f:
                state = json.load(f)
            self.balance = state.get('balance', self.balance)
            self.positions = state.get('positions', {})
            self.log(f"Restored: ${self.balance:.2f}, {len(self.positions)} positions")
        except FileNotFoundError:
            self.log("No saved state — starting fresh")
        except Exception as e:
            self.log(f"Load error: {e}")

    # ── Main Loop ──

    def run(self):
        self.log("=" * 60)
        self.log(f"Polymarket Prediction Bot — {self.mode.upper()} MODE")
        self.log(f"Strategy: Intelligence + Momentum + Value | Size: {CONFIG['position_size_pct']*100:.0f}%")
        self.log("=" * 60)

        self.load_state()

        cycle = 0
        while self.running:
            cycle += 1
            self.log(f"\n--- Cycle {cycle} ---")

            # Scan markets
            markets = self.scan_markets()
            self.log(f"Found {len(markets)} active markets")

            # Get sentiment
            sentiment = self.get_news_sentiment()

            # Check exits
            self.check_exits()

            # Score opportunities
            opportunities = []
            for cid, market in markets.items():
                if cid in self.positions:
                    continue
                score, direction, token_id, reasons = self.score_market(market, sentiment)
                if score >= CONFIG['min_score'] and direction and token_id:
                    opportunities.append((score, cid, direction, token_id, reasons, market))

            opportunities.sort(reverse=True)

            # Execute top opportunities
            for score, cid, direction, token_id, reasons, market in opportunities[:3]:
                if len(self.positions) >= CONFIG['max_positions']:
                    break

                amount = self.calc_position_size()
                if amount < CONFIG['min_trade_amount']:
                    continue

                self.log(f"  Signal: {direction} (score {score:.1f}/5)")
                self.log(f"    Q: {market.get('question', '?')[:60]}")
                for r in reasons:
                    self.log(f"    - {r}")

                self.place_trade(cid, direction, token_id, amount, market)

            # Summary
            pnls = [t.get('pnl', 0) for t in self.closed_trades]
            total = len(pnls)
            wins = len([p for p in pnls if p > 0])
            wr = round(wins / total * 100, 1) if total > 0 else 0
            self.log(f"  Balance: ${self.balance:.2f} | Open: {len(self.positions)} | WR: {wr}%")

            self.save_state()

            for _ in range(CONFIG['check_interval'] // 10):
                if not self.running:
                    break
                time.sleep(10)

        self.log("Polymarket bot stopped")
        self.save_state()


def main():
    bot = PolymarketRunner()
    try:
        bot.run()
    except KeyboardInterrupt:
        bot.running = False
        bot.save_state()


if __name__ == '__main__':
    main()
