#!/usr/bin/env python3
"""
Poly.Bot — Employee #008 | Chief Prediction Officer (CPO)

High-conviction prediction market trader on Polymarket.
Uses Natalia (CRO) as active research partner to validate every trade.

PHILOSOPHY:
  "Only trade what you KNOW. Never gamble — predict."

  The edge comes from INFORMATION, not probability math. Poly.Bot:
  1. Scans Polymarket for markets where news has ALREADY decided the outcome
  2. Dispatches Natalia to research the specific question
  3. Only trades when research confirms a near-certain outcome
  4. Buys YES on events that have effectively already happened (price < 85c)
  5. Buys NO on events that are effectively impossible (price > 15c)
  6. Waits for settlement — collecting the spread as profit

EDGE SOURCES:
  - News lag: Polymarket prices often lag real-world events by minutes-hours
  - Narrative discount: markets overprice unlikely scenarios (fear/hope premium)
  - Research depth: Natalia searches 5+ sources per market — more than most traders
  - Patience: only 1-3 trades per day, each with 85%+ conviction

RISK MANAGEMENT:
  - Never risk more than 3% of balance on one trade
  - Minimum conviction score: 8/10 (4 of 5 layers must confirm)
  - Auto-exits: 30% profit take, 50% stop loss
  - Maximum 5 concurrent positions
  - Paper mode by default — prove the edge before risking real capital

INTEGRATION WITH NATALIA:
  - Dispatches research tasks via lib/task_dispatch.py
  - Reads completed research from tasks/completed/
  - Also reads news feed directly from news/feed.json
  - Reads both intel briefs: tradebot-intel-natalia.md + natalia-intel.md
"""

import json
import os
import sys
import time
import re
from datetime import datetime, timezone, timedelta
from collections import defaultdict

sys.path.insert(0, '/root/.openclaw/workspace')
from lib.polymarket_api import PolymarketClient
from lib.atomic_write import atomic_json_write
from lib.telegram import send_message as telegram_send
from lib.task_dispatch import create_task, get_task, get_pending_tasks
from lib.credentials import _load_dotenv

_load_dotenv()

# ── Paths ──
WORKSPACE = '/root/.openclaw/workspace'
NEWS_FEED_PATH = os.path.join(WORKSPACE, 'news/feed.json')
NATALIA_INTEL_PATH = os.path.join(WORKSPACE, 'memory/tradebot-intel-natalia.md')
NATALIA_BRIEF_PATH = os.path.join(WORKSPACE, 'memory/natalia-intel.md')
STATE_PATH = os.path.join(WORKSPACE, 'employees/polybot_state.json')
STATUS_PATH = os.path.join(WORKSPACE, 'employees/polybot_status.json')
HISTORY_PATH = os.path.join(WORKSPACE, 'employees/polybot_history.jsonl')
RESEARCH_CACHE_PATH = os.path.join(WORKSPACE, 'employees/polybot_research_cache.json')

POLYMARKET_MODE = os.environ.get('POLYMARKET_MODE', 'paper')

# ── Strategy Config ──
CONFIG = {
    # Position management
    'max_positions': 5,
    'position_size_pct': 0.03,     # 3% of balance per trade (conservative)
    'min_trade_amount': 1.00,
    'max_trade_amount': 20.00,     # Cap per trade

    # Timing
    'check_interval': 180,         # 3 min between cycles
    'research_cooldown': 300,      # 5 min between research requests for same market

    # Entry criteria — ONLY trade near-certainties
    'min_conviction': 8,           # Minimum 8/10 conviction to trade
    'max_yes_price_for_buy': 0.85, # Buy YES only if price < 85c (15%+ upside)
    'min_yes_price_for_no': 0.15,  # Buy NO only if YES price > 85c (i.e. NO < 15c)
    'sweet_spot_low': 0.60,        # Value zone: 60-85c (YES) or 15-40c (NO)
    'sweet_spot_high': 0.85,
    'research_dispatch_threshold': 3,  # Dispatch Natalia research at score >= 3

    # Exit criteria
    'profit_take_pct': 0.30,       # Take profit at 30% gain
    'stop_loss_pct': 0.50,         # Stop loss at 50% loss
    'max_hold_hours': 168,         # Force exit after 7 days if not settled

    # Filters
    'min_volume_24h': 5000,        # Minimum $5k daily volume
    'min_liquidity': 1000,         # Minimum orderbook depth
    'max_spread': 0.05,            # Maximum 5c spread
}

# ── Categories Poly.Bot tracks (maps to Natalia's research areas) ──
TRACKED_CATEGORIES = {
    'politics': ['election', 'president', 'congress', 'senate', 'vote', 'bill', 'trump',
                 'biden', 'governor', 'supreme court', 'policy', 'executive order'],
    'economy': ['gdp', 'inflation', 'cpi', 'fed', 'interest rate', 'unemployment',
                'jobs report', 'nonfarm', 'recession', 'treasury', 'deficit'],
    'tech': ['ai', 'openai', 'google', 'apple', 'microsoft', 'nvidia', 'anthropic',
             'tesla', 'meta', 'amazon', 'earnings', 'ipo', 'acquisition'],
    'crypto': ['bitcoin', 'ethereum', 'btc', 'eth', 'crypto', 'defi', 'nft',
               'stablecoin', 'regulation', 'sec', 'etf'],
    'geopolitics': ['war', 'ukraine', 'russia', 'china', 'taiwan', 'nato',
                    'sanctions', 'ceasefire', 'conflict', 'treaty'],
    'sports': ['nba', 'nfl', 'mlb', 'super bowl', 'world cup', 'olympics',
               'championship', 'finals', 'playoff'],
    'science': ['space', 'nasa', 'spacex', 'climate', 'fda', 'vaccine',
                'breakthrough', 'nobel', 'discovery'],
}


class PolyBot:
    """Poly.Bot — High-conviction Polymarket trader using Natalia as research oracle."""

    def __init__(self):
        self.running = True
        self.mode = POLYMARKET_MODE

        # API client
        api_key = os.environ.get('POLYMARKET_API_KEY')
        api_secret = os.environ.get('POLYMARKET_API_SECRET')
        passphrase = os.environ.get('POLYMARKET_PASSPHRASE')
        private_key = os.environ.get('POLYMARKET_PRIVATE_KEY')
        self.client = PolymarketClient(api_key, api_secret, passphrase, private_key)

        # State
        self.balance = 100.00 if self.mode == 'paper' else 0.0
        self.positions = {}          # condition_id -> position
        self.closed_trades = []
        self.market_cache = {}       # condition_id -> market data
        self.research_cache = {}     # condition_id -> {research, timestamp, conviction}
        self.research_pending = {}   # condition_id -> task_id (waiting for Natalia)
        self.price_history = defaultdict(list)
        self._last_news_scan = 0
        self._news_cache = []

        self.load_state()

    def log(self, msg):
        ts = datetime.now(timezone.utc).strftime('%H:%M:%S')
        print(f"[{ts}] [Poly.Bot] {msg}")

    def alert(self, msg):
        """Send Telegram alert."""
        try:
            import html
            safe = html.escape(msg)
            telegram_send(
                f"<b>⬡ POLY.BOT</b>\n"
                f"<i>{datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}</i>\n\n"
                f"{safe}"
            )
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════
    #  INTELLIGENCE LAYER — Natalia Integration
    # ══════════════════════════════════════════════════════════════

    def read_news_feed(self):
        """Read the full news feed for market-relevant intelligence."""
        now = time.time()
        if now - self._last_news_scan < 120 and self._news_cache:
            return self._news_cache

        try:
            with open(NEWS_FEED_PATH) as f:
                data = json.load(f)
            self._news_cache = data.get('articles', [])
            self._last_news_scan = now
            return self._news_cache
        except Exception:
            return []

    def read_natalia_intel(self):
        """Read both of Natalia's intelligence briefs."""
        intel = ''
        for path in [NATALIA_INTEL_PATH, NATALIA_BRIEF_PATH]:
            try:
                with open(path) as f:
                    intel += f.read() + '\n\n'
            except Exception:
                pass
        return intel.lower()

    def search_news_for_market(self, question):
        """Search the news feed for articles relevant to a specific market question."""
        articles = self.read_news_feed()
        question_lower = question.lower()

        # Extract key terms from the question
        terms = set()
        for word in question_lower.split():
            word = word.strip('?.,!:;()')
            if len(word) > 3 and word not in ('will', 'does', 'have', 'been', 'this', 'that',
                                                'with', 'from', 'they', 'their', 'would',
                                                'could', 'should', 'before', 'after',
                                                'about', 'above', 'below', 'between'):
                terms.add(word)

        # Also add known entity names
        for category, keywords in TRACKED_CATEGORIES.items():
            for kw in keywords:
                if kw in question_lower:
                    terms.add(kw)

        # Score each article against the question
        relevant = []
        for article in articles:
            title = (article.get('title', '') or '').lower()
            desc = (article.get('description', '') or '').lower()
            content = (article.get('full_content', '') or article.get('summary', '') or '').lower()
            combined = title + ' ' + desc + ' ' + content

            hits = sum(1 for term in terms if term in combined)
            if hits >= 2:  # At least 2 matching terms
                relevant.append({
                    'title': article.get('title', ''),
                    'source': article.get('source', ''),
                    'age': article.get('age', ''),
                    'description': article.get('description', ''),
                    'content_snippet': content[:500],
                    'relevance': hits / max(len(terms), 1),
                })

        # Sort by relevance
        relevant.sort(key=lambda x: x['relevance'], reverse=True)
        return relevant[:10]

    def dispatch_natalia_research(self, market):
        """Ask Natalia to research a specific prediction market question."""
        cid = market.get('condition_id') or market.get('id', '')
        question = market.get('question', '')

        # Check cooldown
        if cid in self.research_cache:
            last_time = self.research_cache[cid].get('timestamp', 0)
            if time.time() - last_time < CONFIG['research_cooldown']:
                return  # Too soon

        # Check if already pending
        if cid in self.research_pending:
            return

        # Create research task for Natalia
        self.log(f"  Dispatching Natalia: \"{question[:60]}\"")
        task = create_task(
            title=f"Polymarket research: {question[:80]}",
            assigned_to='natalia',
            task_type='research',
            params={
                'query': question,
                'count': 5,
                'context': 'polymarket_prediction',
                'requester': 'polybot',
            },
            priority=3,  # High priority
            created_by='polybot',
        )
        self.research_pending[cid] = task['id']

    def collect_natalia_results(self):
        """Check if any dispatched research tasks have completed."""
        for cid, task_id in list(self.research_pending.items()):
            task = get_task(task_id)
            if not task:
                del self.research_pending[cid]
                continue

            if task['status'] == 'completed' and task.get('result'):
                result = task['result']
                self.research_cache[cid] = {
                    'result': result,
                    'timestamp': time.time(),
                    'summary': result.get('summary', ''),
                    'sources_count': result.get('sources_count', 0),
                }
                del self.research_pending[cid]
                self.log(f"  Natalia returned: {result.get('sources_count', 0)} sources for {cid[:20]}")

            elif task['status'] == 'failed':
                del self.research_pending[cid]

    # ══════════════════════════════════════════════════════════════
    #  CONVICTION ENGINE — 10-point scoring system
    # ══════════════════════════════════════════════════════════════

    def score_conviction(self, market):
        """Score a market on a 0-10 conviction scale.

        Layers:
          1. PRICE VALUE (0-2): How far from fair value is the price?
          2. NEWS EVIDENCE (0-3): Does our news feed confirm the outcome?
          3. NATALIA RESEARCH (0-2): Did Natalia's deep research confirm?
          4. MOMENTUM (0-1): Is the price moving toward our predicted outcome?
          5. MARKET QUALITY (0-2): Volume, spread, time to expiry

        Only trade at conviction >= 8/10.
        """
        cid = market.get('condition_id') or market.get('id', '')
        question = (market.get('question', '') or '').lower()
        tokens = market.get('tokens', [])
        volume_24h = float(market.get('volume24hr', 0) or market.get('volume', 0) or 0)

        if not tokens:
            return 0, None, None, []

        # Identify YES/NO tokens and prices
        yes_token, no_token = None, None
        for t in tokens:
            outcome = (t.get('outcome', '') or '').upper()
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

        # Determine direction: which side has the edge?
        # Only trade markets with clear directional signal — skip 50/50 zones.
        direction = None
        if yes_price <= 0.40:
            direction = 'YES'  # YES is cheap, buy YES
        elif yes_price >= 0.60:
            direction = 'NO'  # YES is expensive, buy NO cheap
        else:
            return 0, None, None, []  # Price too close to 50/50 — no edge

        score = 0
        reasons = []

        # ── Layer 1: PRICE VALUE (0-2) ──
        if direction == 'YES':
            if yes_price <= 0.15:
                score += 2
                reasons.append(f'Extreme value: YES@{yes_price:.2f} (85%+ upside)')
            elif yes_price <= 0.30:
                score += 1.5
                reasons.append(f'Strong value: YES@{yes_price:.2f}')
            elif yes_price <= 0.40:
                score += 1
                reasons.append(f'Good value: YES@{yes_price:.2f}')
            elif yes_price <= 0.50:
                score += 0.5
                reasons.append(f'Moderate value: YES@{yes_price:.2f}')
        else:
            no_price = 1 - yes_price
            if no_price <= 0.15:
                score += 2
                reasons.append(f'Extreme value: NO@{no_price:.2f} (85%+ upside)')
            elif no_price <= 0.30:
                score += 1.5
                reasons.append(f'Strong value: NO@{no_price:.2f}')
            elif no_price <= 0.40:
                score += 1
                reasons.append(f'Good value: NO@{no_price:.2f}')
            elif no_price <= 0.50:
                score += 0.5
                reasons.append(f'Moderate value: NO@{no_price:.2f}')

        # ── Layer 2: NEWS EVIDENCE (0-3) ──
        news_hits = self.search_news_for_market(market.get('question', ''))
        intel = self.read_natalia_intel()

        # Check if news articles directly support our direction
        supporting_articles = 0
        contradicting_articles = 0

        # Determine what "supporting" means based on the question
        question_text = market.get('question', '')
        for article in news_hits:
            content = (article.get('content_snippet', '') + ' ' + article.get('description', '')).lower()
            title = article.get('title', '').lower()

            # Simple sentiment: does this article suggest YES or NO?
            positive_signals = ['confirmed', 'approved', 'passed', 'signed', 'announced',
                                'will', 'expected to', 'set to', 'plans to', 'agreed',
                                'victory', 'win', 'success', 'rise', 'growth', 'increase',
                                'beat', 'exceed', 'record', 'breakthrough']
            negative_signals = ['rejected', 'denied', 'failed', 'blocked', 'cancelled',
                                'unlikely', 'doubt', 'oppose', 'defeat', 'fall', 'decline',
                                'miss', 'below', 'collapse', 'crisis', 'impossible']

            pos_count = sum(1 for sig in positive_signals if sig in content or sig in title)
            neg_count = sum(1 for sig in negative_signals if sig in content or sig in title)

            if direction == 'YES' and pos_count > neg_count:
                supporting_articles += 1
            elif direction == 'NO' and neg_count > pos_count:
                supporting_articles += 1
            elif (direction == 'YES' and neg_count > pos_count) or \
                 (direction == 'NO' and pos_count > neg_count):
                contradicting_articles += 1

        if supporting_articles >= 3 and contradicting_articles == 0:
            score += 3
            reasons.append(f'Strong news support: {supporting_articles} articles confirm')
        elif supporting_articles >= 2 and contradicting_articles == 0:
            score += 2
            reasons.append(f'Good news support: {supporting_articles} articles')
        elif supporting_articles >= 1 and contradicting_articles == 0:
            score += 1
            reasons.append(f'Some news support: {supporting_articles} article(s)')

        # Contradiction is a hard penalty
        if contradicting_articles >= 2:
            score -= 2
            reasons.append(f'NEWS CONFLICT: {contradicting_articles} contradicting articles')

        # Also check Natalia's intel brief for keyword matches
        question_words = [w for w in question_text.lower().split() if len(w) > 4]
        intel_hits = sum(1 for w in question_words if w in intel)
        if intel_hits >= 3:
            score += 0.5
            reasons.append(f'Intel brief relevant ({intel_hits} keyword hits)')

        # ── Layer 3: NATALIA RESEARCH (0-2) ──
        research = self.research_cache.get(cid)
        if research and research.get('sources_count', 0) > 0:
            summary = research.get('summary', '').lower()
            # Check if research summary supports our direction
            if direction == 'YES':
                support_kw = ['likely', 'expected', 'confirmed', 'will happen', 'positive', 'yes']
                oppose_kw = ['unlikely', 'doubtful', 'denied', 'will not', 'negative', 'no']
            else:
                support_kw = ['unlikely', 'doubtful', 'denied', 'will not', 'negative', 'no', 'failed']
                oppose_kw = ['likely', 'expected', 'confirmed', 'will happen', 'positive', 'yes']

            support = sum(1 for kw in support_kw if kw in summary)
            oppose = sum(1 for kw in oppose_kw if kw in summary)

            if support > oppose and support >= 2:
                score += 2
                reasons.append(f'Natalia research confirms ({research["sources_count"]} sources)')
            elif support > oppose:
                score += 1
                reasons.append(f'Natalia research leans favorable')
            elif oppose > support:
                score -= 1
                reasons.append(f'Natalia research contradicts')
        else:
            # No research yet — dispatch it
            self.dispatch_natalia_research(market)
            reasons.append('Research pending (dispatched to Natalia)')

        # ── Layer 4: MOMENTUM (0-1) ──
        history = self.price_history.get(yes_token_id, [])
        if len(history) >= 3:
            recent = [p for _, p in history[-5:]]
            old = [p for _, p in history[:3]]
            avg_recent = sum(recent) / len(recent)
            avg_old = sum(old) / len(old)
            momentum = avg_recent - avg_old

            if direction == 'YES' and momentum < -0.02:
                # Price dropping toward our buy — good entry
                score += 1
                reasons.append(f'Favorable entry: YES price dropping ({momentum:+.3f})')
            elif direction == 'NO' and momentum > 0.02:
                # YES price rising = NO getting cheaper — good entry
                score += 1
                reasons.append(f'Favorable entry: NO price dropping ({momentum:+.3f})')

        # ── Layer 5: MARKET QUALITY (0-2) ──
        # Volume
        if volume_24h >= 50000:
            score += 1
            reasons.append(f'Excellent liquidity (${volume_24h:,.0f}/day)')
        elif volume_24h >= CONFIG['min_volume_24h']:
            score += 0.5
            reasons.append(f'Adequate liquidity (${volume_24h:,.0f}/day)')
        else:
            score -= 1
            reasons.append(f'LOW liquidity (${volume_24h:,.0f}/day) — risky')

        # Spread
        if yes_token_id:
            book = self.client.get_orderbook(yes_token_id)
            spread = book.get('spread', 1.0)
            if spread <= 0.02:
                score += 1
                reasons.append(f'Tight spread ({spread:.3f})')
            elif spread <= CONFIG['max_spread']:
                score += 0.5
                reasons.append(f'Acceptable spread ({spread:.3f})')
            else:
                score -= 0.5
                reasons.append(f'Wide spread ({spread:.3f}) — execution risk')

        # Determine target token
        target_token = yes_token if direction == 'YES' else no_token
        target_id = target_token.get('token_id', '') if target_token else ''

        return round(score, 1), direction, target_id, reasons

    # ══════════════════════════════════════════════════════════════
    #  CATEGORIZATION — What markets should Poly.Bot even look at?
    # ══════════════════════════════════════════════════════════════

    def categorize_market(self, market):
        """Determine which category a market belongs to.
        Returns: category string or None if not in our wheelhouse.
        """
        question = (market.get('question', '') or '').lower()
        description = (market.get('description', '') or '').lower()
        combined = question + ' ' + description

        for category, keywords in TRACKED_CATEGORIES.items():
            hits = sum(1 for kw in keywords if kw in combined)
            if hits >= 1:
                return category
        return None

    # ══════════════════════════════════════════════════════════════
    #  TRADING EXECUTION
    # ══════════════════════════════════════════════════════════════

    def calc_position_size(self, conviction):
        """Calculate position size scaled by conviction.
        Higher conviction = slightly larger size (but capped).
        """
        base = self.balance * CONFIG['position_size_pct']
        # Scale: conviction 8 = 1x, conviction 9 = 1.25x, conviction 10 = 1.5x
        multiplier = 1.0 + (conviction - CONFIG['min_conviction']) * 0.25
        size = base * min(multiplier, 1.5)
        return round(max(CONFIG['min_trade_amount'], min(size, CONFIG['max_trade_amount'])), 2)

    def execute_trade(self, cid, direction, token_id, amount, market, conviction, reasons):
        """Execute a trade with full logging and alerts."""
        tokens = market.get('tokens', [])
        target_token = None
        for t in tokens:
            if t.get('token_id') == token_id:
                target_token = t
                break
        if not target_token:
            return False

        price = float(target_token.get('price', 0.5))
        if price <= 0 or price >= 1:
            return False

        shares = amount / price
        actual_cost = round(shares * price, 2)

        if actual_cost > self.balance:
            self.log(f"  BLOCKED: Insufficient balance (${actual_cost:.2f} > ${self.balance:.2f})")
            return False

        # Live execution
        if self.mode == 'live' and self.client.api_key:
            result = self.client.place_order(token_id, 'BUY', price, shares)
            if not result:
                self.log(f"  BLOCKED: Order rejected by Polymarket")
                return False

        # Record position
        self.balance -= actual_cost
        question = market.get('question', '')
        self.positions[cid] = {
            'direction': direction,
            'token_id': token_id,
            'shares': round(shares, 4),
            'entry_price': price,
            'total_cost': actual_cost,
            'question': question,
            'conviction': conviction,
            'reasons': reasons[:5],
            'category': self.categorize_market(market),
            'opened_at': datetime.now(timezone.utc).isoformat(),
        }

        self.log(f"  TRADE: {direction} @ ${price:.3f} x{shares:.1f} shares = ${actual_cost:.2f}")
        self.log(f"  Conviction: {conviction}/10")
        self.log(f"  Q: {question[:70]}")

        # Alert
        reason_text = '\n'.join(f'  - {r}' for r in reasons[:4])
        self.alert(
            f"NEW TRADE\n"
            f"{direction} — {question[:60]}\n"
            f"Price: ${price:.3f} | Size: ${actual_cost:.2f}\n"
            f"Conviction: {conviction}/10\n"
            f"Reasons:\n{reason_text}"
        )

        return True

    def check_exits(self):
        """Check all positions for TP/SL/settlement/time-based exits."""
        to_close = []

        for cid, pos in list(self.positions.items()):
            market = self.market_cache.get(cid)
            if not market:
                continue

            # Find current price
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
            pnl = current_value - cost
            pnl_pct = pnl / cost if cost > 0 else 0

            close_reason = None

            # Take profit
            if pnl_pct >= CONFIG['profit_take_pct']:
                close_reason = f'TP ({pnl_pct*100:+.0f}%)'

            # Stop loss
            elif pnl_pct <= -CONFIG['stop_loss_pct']:
                close_reason = f'SL ({pnl_pct*100:+.0f}%)'

            # Settlement
            elif current_price >= 0.98 or current_price <= 0.02:
                close_reason = 'Settled'

            # Time-based exit
            elif pos.get('opened_at'):
                try:
                    opened = datetime.fromisoformat(pos['opened_at'])
                    hours_held = (datetime.now(timezone.utc) - opened).total_seconds() / 3600
                    if hours_held >= CONFIG['max_hold_hours']:
                        close_reason = f'Time exit ({hours_held:.0f}h)'
                except Exception:
                    pass

            if close_reason:
                self.balance += current_value
                result = 'WIN' if pnl > 0 else 'LOSS'

                self.log(f"  {result}: {pos['question'][:50]} | ${pnl:+.2f} ({close_reason})")

                pos['pnl'] = round(pnl, 2)
                pos['pnl_pct'] = round(pnl_pct * 100, 1)
                pos['close_reason'] = close_reason
                pos['close_price'] = current_price
                pos['closed_at'] = datetime.now(timezone.utc).isoformat()
                self.closed_trades.append(pos)
                to_close.append(cid)

                # Archive
                try:
                    with open(HISTORY_PATH, 'a') as f:
                        f.write(json.dumps(pos) + '\n')
                except Exception:
                    pass

                # Alert
                self.alert(
                    f"TRADE CLOSED — {result}\n"
                    f"{pos['direction']} — {pos['question'][:50]}\n"
                    f"P&L: ${pnl:+.2f} ({pnl_pct*100:+.1f}%)\n"
                    f"Reason: {close_reason}"
                )

        for cid in to_close:
            del self.positions[cid]

    # ══════════════════════════════════════════════════════════════
    #  STATE MANAGEMENT
    # ══════════════════════════════════════════════════════════════

    def save_state(self):
        """Persist state to disk."""
        pnls = [t.get('pnl', 0) for t in self.closed_trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0 and p != 0]

        state = {
            'mode': self.mode,
            'balance': round(self.balance, 2),
            'positions': self.positions,
            'closed_trades': self.closed_trades[-100:],
            'stats': {
                'total_trades': len(self.closed_trades),
                'wins': len(wins),
                'losses': len(losses),
                'win_rate': round(len(wins) / (len(wins) + len(losses)) * 100, 1) if (wins or losses) else 0,
                'total_pnl': round(sum(pnls), 2),
                'avg_conviction': round(sum(t.get('conviction', 0) for t in self.closed_trades) / max(len(self.closed_trades), 1), 1),
                'profit_factor': round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) != 0 else 0.0,
            },
            'last_update': datetime.now(timezone.utc).isoformat(),
        }

        try:
            atomic_json_write(STATE_PATH, state)
        except Exception as e:
            self.log(f"State save error: {e}")

        # Status for dashboard
        try:
            atomic_json_write(STATUS_PATH, {
                'employee': 'Poly.Bot',
                'employee_id': '008',
                'role': 'CPO — Chief Prediction Officer',
                'source': 'Polymarket',
                'mode': self.mode.upper(),
                'connected': True,
                'balance': round(self.balance, 2),
                'open_positions': len(self.positions),
                'total_trades': state['stats']['total_trades'],
                'win_rate': state['stats']['win_rate'],
                'total_pnl': state['stats']['total_pnl'],
                'avg_conviction': state['stats']['avg_conviction'],
                'last_update': datetime.now(timezone.utc).isoformat(),
            })
        except Exception:
            pass

        # Cache research
        try:
            atomic_json_write(RESEARCH_CACHE_PATH, self.research_cache)
        except Exception:
            pass

    def load_state(self):
        """Restore state from disk."""
        try:
            with open(STATE_PATH) as f:
                state = json.load(f)
            self.balance = state.get('balance', self.balance)
            self.positions = state.get('positions', {})
            self.closed_trades = state.get('closed_trades', [])
            self.log(f"Restored: ${self.balance:.2f}, {len(self.positions)} positions, "
                     f"{len(self.closed_trades)} closed trades")
        except FileNotFoundError:
            self.log("Fresh start — no saved state")
        except Exception as e:
            self.log(f"State load error: {e}")

        # Load research cache
        try:
            with open(RESEARCH_CACHE_PATH) as f:
                self.research_cache = json.load(f)
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════
    #  MAIN LOOP
    # ══════════════════════════════════════════════════════════════

    def run(self):
        self.log("=" * 60)
        self.log("Poly.Bot — Employee #008 | Chief Prediction Officer")
        self.log(f"Mode: {self.mode.upper()} | Strategy: High-Conviction Intelligence")
        self.log(f"Min conviction: {CONFIG['min_conviction']}/10 | Size: {CONFIG['position_size_pct']*100:.0f}%")
        self.log(f"Balance: ${self.balance:.2f}")
        self.log("=" * 60)
        self.log("Philosophy: Only trade what you KNOW. Never gamble — predict.")
        self.log("")

        cycle = 0
        while self.running:
            cycle += 1
            self.log(f"\n{'='*40} Cycle {cycle} {'='*40}")

            # 1. Collect any pending Natalia research
            self.collect_natalia_results()

            # 2. Scan markets
            markets = self.client.get_markets(limit=100, active=True)
            if not markets:
                self.log("No markets available — sleeping")
                time.sleep(CONFIG['check_interval'])
                continue

            # Build cache
            for m in markets:
                cid = m.get('condition_id') or m.get('id', '')
                if cid:
                    self.market_cache[cid] = m
                    # Track price history
                    tokens = m.get('tokens', [])
                    for t in tokens:
                        tid = t.get('token_id', '')
                        if tid:
                            self.price_history[tid].append((time.time(), float(t.get('price', 0.5))))
                            self.price_history[tid] = self.price_history[tid][-60:]  # Keep 60 points

            self.log(f"Scanned {len(markets)} active markets")

            # 3. Check exits FIRST
            self.check_exits()

            # 4. Filter to markets in our categories
            categorized = []
            for m in markets:
                cat = self.categorize_market(m)
                if cat:
                    categorized.append((m, cat))

            self.log(f"  {len(categorized)} markets in tracked categories")

            # 5. Score all categorized markets
            opportunities = []
            score_distribution = defaultdict(int)
            top_near_misses = []
            for m, cat in categorized:
                cid = m.get('condition_id') or m.get('id', '')
                if cid in self.positions:
                    continue  # Already in this market

                conviction, direction, token_id, reasons = self.score_conviction(m)

                score_bucket = int(conviction)
                score_distribution[score_bucket] += 1

                if conviction >= CONFIG['min_conviction'] and direction and token_id:
                    opportunities.append((conviction, cid, direction, token_id, reasons, m))
                elif conviction >= CONFIG['research_dispatch_threshold'] and direction:
                    # Promising but not ready — dispatch research to build conviction
                    self.dispatch_natalia_research(m)
                    top_near_misses.append((conviction, direction, m.get('question', '?')[:55], reasons))
                elif conviction > 0 and direction:
                    top_near_misses.append((conviction, direction, m.get('question', '?')[:55], reasons))

            opportunities.sort(reverse=True)

            # Diagnostic: show score distribution
            if score_distribution:
                dist_str = ' | '.join(f'{k}pt:{v}' for k, v in sorted(score_distribution.items(), reverse=True))
                self.log(f"  Score distribution: {dist_str}")
            # Show top near-misses
            top_near_misses.sort(reverse=True)
            if top_near_misses:
                self.log(f"  Top near-misses:")
                for conv, dirn, q, reasons in top_near_misses[:5]:
                    self.log(f"    [{conv}/10] {dirn} — {q}")
                    for r in reasons[:2]:
                        self.log(f"      > {r}")

            if opportunities:
                self.log(f"\n  TOP OPPORTUNITIES:")
                for conv, cid, direction, tid, reasons, m in opportunities[:5]:
                    q = m.get('question', '?')
                    self.log(f"    [{conv}/10] {direction} — {q[:60]}")

            # 6. Execute top opportunities (respect limits)
            trades_this_cycle = 0
            for conviction, cid, direction, token_id, reasons, m in opportunities:
                if len(self.positions) >= CONFIG['max_positions']:
                    break
                if trades_this_cycle >= 2:
                    break  # Max 2 new trades per cycle

                amount = self.calc_position_size(conviction)
                if self.execute_trade(cid, direction, token_id, amount, m, conviction, reasons):
                    trades_this_cycle += 1

            # 7. Summary
            pnls = [t.get('pnl', 0) for t in self.closed_trades]
            total = len(self.closed_trades)
            wins = len([p for p in pnls if p > 0])
            wr = round(wins / total * 100, 1) if total > 0 else 0
            total_pnl = sum(pnls)
            pending_research = len(self.research_pending)

            self.log(f"\n  Balance: ${self.balance:.2f} | Open: {len(self.positions)} | "
                     f"Closed: {total} | WR: {wr}% | P&L: ${total_pnl:+.2f}")
            if pending_research:
                self.log(f"  Natalia research pending: {pending_research} markets")

            self.save_state()

            # Sleep
            for _ in range(CONFIG['check_interval'] // 10):
                if not self.running:
                    break
                time.sleep(10)

        self.log("Poly.Bot shutting down")
        self.save_state()


PID_FILE = os.path.join(WORKSPACE, 'employees/polybot.pid')


def _acquire_lock():
    """Ensure only one Poly.Bot instance runs at a time."""
    # Check for stale PID file
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE) as f:
                old_pid = int(f.read().strip())
            # Check if process is still alive
            os.kill(old_pid, 0)
            print(f"[Poly.Bot] Another instance running (PID {old_pid}). Exiting.")
            sys.exit(1)
        except (ProcessLookupError, ValueError):
            pass  # Stale PID file, safe to overwrite

    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))


def _release_lock():
    try:
        os.remove(PID_FILE)
    except Exception:
        pass


def main():
    _acquire_lock()
    bot = PolyBot()
    try:
        bot.run()
    except KeyboardInterrupt:
        bot.running = False
        bot.save_state()
        print("\nPoly.Bot stopped gracefully")
    finally:
        _release_lock()


if __name__ == '__main__':
    main()
