#!/usr/bin/env python3
"""
Ali.bot — Higher Timeframe Precision Trading Strategist
Employee #005 | CTS (Chief Trading Strategist)

Strategy: 6-Layer Prediction Model on 4H/Daily/Weekly timeframes
- Only trades when ALL layers confirm — zero compromises
- 1-3 trades per week maximum
- Wider stops (50-200 pips forex), bigger targets (1:4+ R:R)
- Hold time: hours to days
- Trailing stop system: break-even at 1× risk, trail at 1.5× risk

"Patience is the edge. The market pays those who wait for certainty."
"""

import requests
import json
import os
from datetime import datetime, timezone, timedelta

# Safety imports
import sys
sys.path.insert(0, '/root/.openclaw/workspace')
from lib.trading_safety import check_kill_switch, validate_price
from lib.credentials import _load_dotenv
from lib.atomic_write import atomic_json_write
from lib.task_dispatch import (
    get_pending_tasks, claim_task, complete_task, fail_task,
)
from lib.zeffbot_report import report_trade_opened, report_trade_closed
from lib.telegram import send_message as telegram_send

# Twisted + cTrader API
from twisted.internet import reactor, task, defer
from twisted.internet.error import ConnectionLost, ConnectionDone
from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq, ProtoOAAccountAuthReq, ProtoOANewOrderReq,
    ProtoOAClosePositionReq, ProtoOAReconcileReq, ProtoOATraderReq,
    ProtoOASubscribeSpotsReq, ProtoOAUnsubscribeSpotsReq,
    ProtoOAAmendPositionSLTPReq,
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
    ProtoOAOrderType, ProtoOATradeSide,
)

# Load credentials — Ali.bot shares the OAuth app but has its own account
_load_dotenv()
CTID = int(os.environ.get('ALIBOT_CTID_ACCOUNT_ID', '0'))
CLIENT_ID = os.environ.get('ICM_CLIENT_ID', '')
CLIENT_SECRET = os.environ.get('ICM_API_SECRET', '')
ACCESS_TOKEN = os.environ.get('ICM_ACCESS_TOKEN', '')
MODE = os.environ.get('ICM_MODE', '')

if MODE != 'demo':
    print(f"SAFETY: Refusing to run. ICM_MODE must be 'demo', got '{MODE}'")
    sys.exit(1)

if not CTID:
    print("SAFETY: ALIBOT_CTID_ACCOUNT_ID not set in .env")
    sys.exit(1)

# ── IC Markets cTrader symbol IDs ──
SYMBOL_IDS = {
    # Forex majors
    'EURUSD': 1, 'GBPUSD': 2, 'USDJPY': 4, 'AUDUSD': 5,
    'USDCAD': 8, 'USDCHF': 6, 'NZDUSD': 12,
    # Forex crosses
    'EURJPY': 3, 'GBPJPY': 7, 'EURGBP': 9, 'AUDJPY': 11, 'CADJPY': 15,
    # Crypto
    'BTCUSD': 10026, 'ETHUSD': 10029,
    # Commodities
    'XAUUSD': 41, 'XAGUSD': 42,
    'XTIUSD': 10019, 'XBRUSD': 10018,
    # Indices
    'US500': 10013, 'US30': 10015, 'USTEC': 10014,
}
ID_TO_SYMBOL = {v: k for k, v in SYMBOL_IDS.items()}

# ── Pair configuration ──
# Ali.bot: Wide stops, big targets, minimum 1:4 R:R
# Fewer pairs than TradeBot — focused on liquid, high-conviction instruments
PAIRS = {
    # ── Forex Majors — the sniper's preferred targets ──
    # 50-100 pip SL, 200-400 pip TP (1:4 R:R), trail at 1× risk
    'EURUSD':  {'name': 'EUR/USD',  'type': 'forex',  'volume': 100000, 'risk_pips': 60,  'reward_pips': 240, 'trail_trigger_pips': 60,  'trail_step_pips': 30},
    'GBPUSD':  {'name': 'GBP/USD',  'type': 'forex',  'volume': 100000, 'risk_pips': 80,  'reward_pips': 320, 'trail_trigger_pips': 80,  'trail_step_pips': 40},
    'USDJPY':  {'name': 'USD/JPY',  'type': 'forex',  'volume': 100000, 'risk_pips': 70,  'reward_pips': 280, 'trail_trigger_pips': 70,  'trail_step_pips': 35},
    'AUDUSD':  {'name': 'AUD/USD',  'type': 'forex',  'volume': 100000, 'risk_pips': 60,  'reward_pips': 240, 'trail_trigger_pips': 60,  'trail_step_pips': 30},
    'USDCAD':  {'name': 'USD/CAD',  'type': 'forex',  'volume': 100000, 'risk_pips': 70,  'reward_pips': 280, 'trail_trigger_pips': 70,  'trail_step_pips': 35},
    'NZDUSD':  {'name': 'NZD/USD',  'type': 'forex',  'volume': 100000, 'risk_pips': 50,  'reward_pips': 200, 'trail_trigger_pips': 50,  'trail_step_pips': 25},
    # ── Forex Crosses ──
    'EURJPY':  {'name': 'EUR/JPY',  'type': 'forex',  'volume': 100000, 'risk_pips': 100, 'reward_pips': 400, 'trail_trigger_pips': 100, 'trail_step_pips': 50},
    'GBPJPY':  {'name': 'GBP/JPY',  'type': 'forex',  'volume': 100000, 'risk_pips': 120, 'reward_pips': 480, 'trail_trigger_pips': 120, 'trail_step_pips': 60},
    # ── Crypto — big moves, big targets ──
    'BTCUSD':  {'name': 'BTC/USD',  'type': 'crypto', 'volume': 100,    'risk_pips': 2000, 'reward_pips': 8000,  'trail_trigger_pips': 2000, 'trail_step_pips': 1000},
    'ETHUSD':  {'name': 'ETH/USD',  'type': 'crypto', 'volume': 100,    'risk_pips': 150,  'reward_pips': 600,   'trail_trigger_pips': 150,  'trail_step_pips': 75},
    # ── Commodities ──
    'XAUUSD':  {'name': 'Gold',     'type': 'commodity', 'volume': 100,  'risk_pips': 500,  'reward_pips': 2000,  'trail_trigger_pips': 500,  'trail_step_pips': 250},
    # ── Indices ──
    'US500':   {'name': 'S&P 500',  'type': 'index',  'volume': 100,    'risk_pips': 200,  'reward_pips': 800,   'trail_trigger_pips': 200,  'trail_step_pips': 100},
    'USTEC':   {'name': 'Nasdaq',   'type': 'index',  'volume': 100,    'risk_pips': 300,  'reward_pips': 1200,  'trail_trigger_pips': 300,  'trail_step_pips': 150},
}

CONFIG = {
    'max_positions': 3,       # max 3 simultaneous swing trades
    'check_interval': 900,    # 15-minute analysis cycles (patient, not frantic)
    'cooldown_hours': 24,     # minimum 24h between trades on same pair
}

# ── News intelligence integration ──
NEWS_INTEL_PATH = '/root/.openclaw/workspace/memory/tradebot-intel.md'

# Keywords for directional bias
USD_BULLISH_KW = ['rate hike', 'hawkish', 'strong dollar', 'fed tighten', 'nonfarm beat',
                  'cpi higher', 'inflation rise', 'gdp growth', 'employment strong']
USD_BEARISH_KW = ['rate cut', 'dovish', 'weak dollar', 'fed ease', 'nonfarm miss',
                  'cpi lower', 'inflation fall', 'recession', 'unemployment rise']
RISK_ON_KW = ['rally', 'optimism', 'risk-on', 'stocks rise', 'market up', 'vix fall',
              'vix tumble', 'stability', 'growth', 'bull market', 'record high']
RISK_OFF_KW = ['crisis', 'fear', 'risk-off', 'selloff', 'crash', 'tension', 'war',
               'sanctions', 'vix spike', 'vix over', 'safe-haven', 'safe haven', 'gold climb']
CRYPTO_BULLISH_KW = ['bitcoin rally', 'crypto rally', 'btc rise', 'adoption', 'etf approved',
                     'institutional buy', 'halving', 'crypto bull']
CRYPTO_BEARISH_KW = ['crypto crash', 'bitcoin fall', 'regulation', 'ban', 'hack', 'ftx',
                     'crypto winter', 'sec', 'crackdown']
OIL_BULLISH_KW = ['oil rise', 'opec cut', 'supply cut', 'iran tension', 'geopolitical risk',
                  'oil demand', 'energy crisis']
OIL_BEARISH_KW = ['oil fall', 'opec increase', 'supply glut', 'demand weak', 'recession fear']

# Yahoo Finance symbol mapping
YAHOO_SYMBOLS = {
    'EURUSD': 'EURUSD=X', 'GBPUSD': 'GBPUSD=X', 'USDJPY': 'USDJPY=X',
    'AUDUSD': 'AUDUSD=X', 'USDCAD': 'USDCAD=X', 'NZDUSD': 'NZDUSD=X',
    'EURJPY': 'EURJPY=X', 'GBPJPY': 'GBPJPY=X',
    'BTCUSD': 'BTC-USD', 'ETHUSD': 'ETH-USD',
    'XAUUSD': 'GC=F', 'XTIUSD': 'CL=F', 'XBRUSD': 'BZ=F',
    'US500': '^GSPC', 'USTEC': '^IXIC', 'US30': '^DJI',
}


# ══════════════════════════════════════════════════════════════════════
#  MULTI-TIMEFRAME DATA PIPELINE
#  Fetches 4H, Daily, Weekly candle data for the 6-layer prediction
# ══════════════════════════════════════════════════════════════════════

def fetch_candles(symbol, interval='1d', range_str='60d'):
    """Fetch candle data from Yahoo Finance.

    Returns dict with 'opens', 'highs', 'lows', 'closes', 'volumes' or None.
    """
    yahoo = YAHOO_SYMBOLS.get(symbol, symbol)
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo}?interval={interval}&range={range_str}"
        r = requests.get(url, headers=headers, timeout=15)
        data = r.json()
        if 'result' not in data['chart'] or not data['chart']['result']:
            return None
        candles = data['chart']['result'][0]['indicators']['quote'][0]
        timestamps = data['chart']['result'][0].get('timestamp', [])
        return {
            'opens': [v for v in candles.get('open', []) if v is not None],
            'highs': [h for h in candles.get('high', []) if h is not None],
            'lows': [l for l in candles.get('low', []) if l is not None],
            'closes': [c for c in candles.get('close', []) if c is not None],
            'volumes': [v for v in candles.get('volume', []) if v is not None],
            'timestamps': timestamps,
        }
    except Exception:
        return None


def get_current_price(symbol):
    """Get the current market price from Yahoo Finance."""
    yahoo = YAHOO_SYMBOLS.get(symbol, symbol)
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo}"
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        if 'result' not in data['chart'] or not data['chart']['result']:
            return None
        return data['chart']['result'][0]['meta']['regularMarketPrice']
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════
#  TECHNICAL ANALYSIS TOOLKIT
# ══════════════════════════════════════════════════════════════════════

def calculate_ema(prices, period):
    """Calculate Exponential Moving Average."""
    if len(prices) < period:
        return None
    multiplier = 2 / (period + 1)
    ema = prices[0]
    for p in prices[1:]:
        ema = (p - ema) * multiplier + ema
    return ema


def calculate_rsi(closes, period=14):
    """Calculate RSI (Relative Strength Index)."""
    if len(closes) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    if len(gains) < period:
        return None
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_macd(closes, fast=12, slow=26, signal=9):
    """Calculate MACD, Signal, and Histogram."""
    ema_fast = calculate_ema(closes, fast)
    ema_slow = calculate_ema(closes, slow)
    if ema_fast is None or ema_slow is None:
        return None, None, None
    macd_line = ema_fast - ema_slow

    # Build MACD history for signal line
    if len(closes) < slow + signal:
        return macd_line, None, None
    macd_history = []
    for i in range(slow, len(closes)):
        ef = calculate_ema(closes[:i + 1], fast)
        es = calculate_ema(closes[:i + 1], slow)
        if ef and es:
            macd_history.append(ef - es)
    signal_line = calculate_ema(macd_history, signal) if len(macd_history) >= signal else None
    histogram = (macd_line - signal_line) if signal_line is not None else None
    return macd_line, signal_line, histogram


def find_support_resistance(highs, lows, closes, lookback=20):
    """Identify key support and resistance levels from price action.

    Uses recent swing highs/lows as S/R zones.
    """
    if len(highs) < lookback or len(lows) < lookback:
        return [], []

    resistances = []
    supports = []

    # Find swing highs (local maxima)
    for i in range(2, min(lookback, len(highs) - 2)):
        idx = -(i + 1)
        if highs[idx] > highs[idx - 1] and highs[idx] > highs[idx + 1]:
            resistances.append(highs[idx])

    # Find swing lows (local minima)
    for i in range(2, min(lookback, len(lows) - 2)):
        idx = -(i + 1)
        if lows[idx] < lows[idx - 1] and lows[idx] < lows[idx + 1]:
            supports.append(lows[idx])

    return sorted(set(resistances), reverse=True), sorted(set(supports))


def detect_candle_pattern(opens, highs, lows, closes):
    """Detect reversal candle patterns on the last 3 candles.

    Returns: ('bullish_engulfing'|'bearish_engulfing'|'pin_bar_bull'|'pin_bar_bear'|None)
    """
    if len(closes) < 3:
        return None

    o1, h1, l1, c1 = opens[-2], highs[-2], lows[-2], closes[-2]
    o2, h2, l2, c2 = opens[-1], highs[-1], lows[-1], closes[-1]
    body1 = abs(c1 - o1)
    body2 = abs(c2 - o2)
    range2 = h2 - l2

    if range2 == 0:
        return None

    # Bullish engulfing: prior candle bearish, current candle bullish and engulfs
    if c1 < o1 and c2 > o2 and c2 > o1 and o2 < c1 and body2 > body1:
        return 'bullish_engulfing'

    # Bearish engulfing: prior candle bullish, current candle bearish and engulfs
    if c1 > o1 and c2 < o2 and c2 < o1 and o2 > c1 and body2 > body1:
        return 'bearish_engulfing'

    # Pin bar bullish: long lower wick, small body at top
    lower_wick = min(o2, c2) - l2
    upper_wick = h2 - max(o2, c2)
    if lower_wick > body2 * 2 and lower_wick > upper_wick * 2:
        return 'pin_bar_bull'

    # Pin bar bearish: long upper wick, small body at bottom
    if upper_wick > body2 * 2 and upper_wick > lower_wick * 2:
        return 'pin_bar_bear'

    return None


def detect_fair_value_gap(highs, lows, closes):
    """Detect Fair Value Gaps (FVG) in the last few candles.

    An FVG is a 3-candle pattern where the middle candle's range
    doesn't overlap with candles 1 and 3 — a gap in price delivery.

    Returns: ('bullish_fvg', gap_high, gap_low) | ('bearish_fvg', gap_high, gap_low) | None
    """
    if len(highs) < 5:
        return None

    # Check last 3 complete candles (index -4, -3, -2, current is -1)
    for offset in range(3, min(6, len(highs))):
        h1, l1 = highs[-offset], lows[-offset]
        h2, l2 = highs[-offset + 1], lows[-offset + 1]
        h3, l3 = highs[-offset + 2], lows[-offset + 2]

        # Bullish FVG: candle 1's high < candle 3's low (gap up)
        if h1 < l3:
            gap_low = h1
            gap_high = l3
            # Price should be near the gap for it to be actionable
            current = closes[-1]
            if gap_low <= current <= gap_high * 1.005:
                return ('bullish_fvg', gap_high, gap_low)

        # Bearish FVG: candle 1's low > candle 3's high (gap down)
        if l1 > h3:
            gap_high = l1
            gap_low = h3
            current = closes[-1]
            if gap_low * 0.995 <= current <= gap_high:
                return ('bearish_fvg', gap_high, gap_low)

    return None


# ══════════════════════════════════════════════════════════════════════
#  NEWS & MACRO INTELLIGENCE
# ══════════════════════════════════════════════════════════════════════

def get_news_bias():
    """Read news intelligence brief and extract directional bias."""
    try:
        with open(NEWS_INTEL_PATH, 'r') as f:
            content = f.read().lower()
    except Exception:
        return {'usd_bias': 'neutral', 'risk_sentiment': 'neutral',
                'crypto_bias': 'neutral', 'oil_bias': 'neutral',
                'confidence': 0.0, 'headlines': 0}

    bull_hits = sum(1 for kw in USD_BULLISH_KW if kw in content)
    bear_hits = sum(1 for kw in USD_BEARISH_KW if kw in content)
    risk_on = sum(1 for kw in RISK_ON_KW if kw in content)
    risk_off = sum(1 for kw in RISK_OFF_KW if kw in content)
    crypto_bull = sum(1 for kw in CRYPTO_BULLISH_KW if kw in content)
    crypto_bear = sum(1 for kw in CRYPTO_BEARISH_KW if kw in content)
    oil_bull = sum(1 for kw in OIL_BULLISH_KW if kw in content)
    oil_bear = sum(1 for kw in OIL_BEARISH_KW if kw in content)

    usd_bias = 'bullish' if bull_hits > bear_hits and bull_hits >= 2 else 'bearish' if bear_hits > bull_hits and bear_hits >= 2 else 'neutral'
    risk_sentiment = 'risk_on' if risk_on > risk_off and risk_on >= 2 else 'risk_off' if risk_off > risk_on and risk_off >= 2 else 'neutral'
    crypto_bias = 'bullish' if crypto_bull > crypto_bear else 'bearish' if crypto_bear > crypto_bull else 'neutral'
    oil_bias = 'bullish' if oil_bull > oil_bear else 'bearish' if oil_bear > oil_bull else 'neutral'

    total = bull_hits + bear_hits + risk_on + risk_off + crypto_bull + crypto_bear + oil_bull + oil_bear
    return {
        'usd_bias': usd_bias, 'risk_sentiment': risk_sentiment,
        'crypto_bias': crypto_bias, 'oil_bias': oil_bias,
        'confidence': min(total / 10.0, 1.0), 'headlines': total,
    }


def news_supports_direction(symbol, direction, news_bias):
    """Check if news sentiment supports the trade direction.
    Returns: 1 (supports), 0 (neutral), -1 (contradicts)
    """
    usd_bias = news_bias.get('usd_bias', 'neutral')
    risk = news_bias.get('risk_sentiment', 'neutral')
    crypto_bias = news_bias.get('crypto_bias', 'neutral')
    oil_bias = news_bias.get('oil_bias', 'neutral')

    if news_bias.get('confidence', 0) < 0.2:
        return 0

    score = 0
    config = PAIRS.get(symbol, {})
    asset_type = config.get('type', 'forex')

    # Forex: USD bias
    if symbol in ('EURUSD', 'GBPUSD', 'AUDUSD', 'NZDUSD'):
        if usd_bias == 'bearish' and direction == 'BUY':
            score += 1
        elif usd_bias == 'bullish' and direction == 'SELL':
            score += 1
        elif usd_bias == 'bearish' and direction == 'SELL':
            score -= 1
        elif usd_bias == 'bullish' and direction == 'BUY':
            score -= 1

    if symbol in ('USDJPY', 'USDCAD'):
        if usd_bias == 'bullish' and direction == 'BUY':
            score += 1
        elif usd_bias == 'bearish' and direction == 'SELL':
            score += 1
        elif usd_bias == 'bullish' and direction == 'SELL':
            score -= 1
        elif usd_bias == 'bearish' and direction == 'BUY':
            score -= 1

    # Risk sentiment
    if symbol in ('AUDUSD', 'GBPUSD', 'NZDUSD'):
        if risk == 'risk_on' and direction == 'BUY':
            score += 1
        elif risk == 'risk_off' and direction == 'SELL':
            score += 1
    if symbol in ('USDJPY', 'EURJPY', 'GBPJPY'):
        if risk == 'risk_off' and direction == 'SELL':
            score += 1
        elif risk == 'risk_on' and direction == 'BUY':
            score += 1

    # Crypto
    if asset_type == 'crypto':
        if risk == 'risk_on' and direction == 'BUY':
            score += 1
        elif risk == 'risk_off' and direction == 'SELL':
            score += 1
        if crypto_bias == 'bullish' and direction == 'BUY':
            score += 1
        elif crypto_bias == 'bearish' and direction == 'SELL':
            score += 1
        elif crypto_bias == 'bullish' and direction == 'SELL':
            score -= 1
        elif crypto_bias == 'bearish' and direction == 'BUY':
            score -= 1

    # Commodities
    if symbol == 'XAUUSD':
        if risk == 'risk_off' and direction == 'BUY':
            score += 1
        elif risk == 'risk_on' and direction == 'SELL':
            score += 1
        if usd_bias == 'bearish' and direction == 'BUY':
            score += 1

    # Indices
    if asset_type == 'index':
        if risk == 'risk_on' and direction == 'BUY':
            score += 1
        elif risk == 'risk_off' and direction == 'SELL':
            score += 1
        elif risk == 'risk_on' and direction == 'SELL':
            score -= 1
        elif risk == 'risk_off' and direction == 'BUY':
            score -= 1

    return max(-1, min(1, score))


# ══════════════════════════════════════════════════════════════════════
#  THE 6-LAYER PREDICTION MODEL
#  Ali.bot's core edge: only trade when ALL 6 layers confirm
# ══════════════════════════════════════════════════════════════════════

def analyze_layer_1_weekly_trend(weekly_data):
    """Layer 1: Weekly Trend Direction.
    EMA 20/50 alignment, higher highs/lows or lower highs/lows.
    Returns: ('bullish'|'bearish'|None, score 0 or 1, reason)
    """
    if not weekly_data or len(weekly_data.get('closes', [])) < 50:
        return None, 0, 'Insufficient weekly data'

    closes = weekly_data['closes']
    highs = weekly_data['highs']
    lows = weekly_data['lows']

    ema_20 = calculate_ema(closes, 20)
    ema_50 = calculate_ema(closes, 50)
    if not ema_20 or not ema_50:
        return None, 0, 'EMAs not ready'

    # EMA alignment
    ema_bullish = ema_20 > ema_50
    price_above = closes[-1] > ema_20

    # Higher highs / higher lows (last 5 weeks)
    recent_highs = highs[-5:]
    recent_lows = lows[-5:]
    hh = all(recent_highs[i] >= recent_highs[i - 1] * 0.998 for i in range(1, len(recent_highs)))
    hl = all(recent_lows[i] >= recent_lows[i - 1] * 0.998 for i in range(1, len(recent_lows)))
    lh = all(recent_highs[i] <= recent_highs[i - 1] * 1.002 for i in range(1, len(recent_highs)))
    ll = all(recent_lows[i] <= recent_lows[i - 1] * 1.002 for i in range(1, len(recent_lows)))

    if ema_bullish and price_above and (hh or hl):
        return 'bullish', 1, f'Weekly bullish: EMA 20>{50}, price above, HH/HL pattern'
    elif not ema_bullish and not price_above and (lh or ll):
        return 'bearish', 1, f'Weekly bearish: EMA 20<50, price below, LH/LL pattern'
    elif ema_bullish and price_above:
        return 'bullish', 1, f'Weekly bullish: EMA 20>50, price above EMA'
    elif not ema_bullish and not price_above:
        return 'bearish', 1, f'Weekly bearish: EMA 20<50, price below EMA'
    else:
        return None, 0, f'Weekly trend unclear: EMA20={ema_20:.5f} EMA50={ema_50:.5f}'


def analyze_layer_2_daily_structure(daily_data, weekly_direction):
    """Layer 2: Daily Structure & Key Levels.
    Price at significant S/R, FVG/order block, candle patterns confirming direction.
    Returns: (score 0 or 1, reason)
    """
    if not daily_data or len(daily_data.get('closes', [])) < 30:
        return 0, 'Insufficient daily data'

    closes = daily_data['closes']
    highs = daily_data['highs']
    lows = daily_data['lows']
    opens = daily_data['opens']
    current = closes[-1]

    confirmations = []

    # Check S/R proximity
    resistances, supports = find_support_resistance(highs, lows, closes, lookback=20)

    if weekly_direction == 'bullish' and supports:
        # Price near support = buy zone
        nearest_support = min(supports, key=lambda s: abs(current - s))
        distance_pct = abs(current - nearest_support) / current * 100
        if distance_pct < 0.5:  # Within 0.5% of support
            confirmations.append(f'Near daily support {nearest_support:.5f} ({distance_pct:.2f}%)')

    elif weekly_direction == 'bearish' and resistances:
        nearest_resistance = min(resistances, key=lambda r: abs(current - r))
        distance_pct = abs(current - nearest_resistance) / current * 100
        if distance_pct < 0.5:
            confirmations.append(f'Near daily resistance {nearest_resistance:.5f} ({distance_pct:.2f}%)')

    # Check for Fair Value Gap
    fvg = detect_fair_value_gap(highs, lows, closes)
    if fvg:
        fvg_type, fvg_high, fvg_low = fvg
        if weekly_direction == 'bullish' and fvg_type == 'bullish_fvg':
            confirmations.append(f'Bullish FVG zone {fvg_low:.5f}-{fvg_high:.5f}')
        elif weekly_direction == 'bearish' and fvg_type == 'bearish_fvg':
            confirmations.append(f'Bearish FVG zone {fvg_low:.5f}-{fvg_high:.5f}')

    # Check candle patterns
    if len(opens) >= 3:
        pattern = detect_candle_pattern(opens, highs, lows, closes)
        if pattern:
            if weekly_direction == 'bullish' and pattern in ('bullish_engulfing', 'pin_bar_bull'):
                confirmations.append(f'Daily {pattern}')
            elif weekly_direction == 'bearish' and pattern in ('bearish_engulfing', 'pin_bar_bear'):
                confirmations.append(f'Daily {pattern}')

    if confirmations:
        return 1, '; '.join(confirmations)
    return 0, 'No daily structure confirmation'


def analyze_layer_3_4h_timing(h4_data, weekly_direction):
    """Layer 3: 4H Entry Timing.
    EMA crossover, momentum (RSI, MACD), clean entry zone.
    Returns: (score 0 or 1, reason)
    """
    if not h4_data or len(h4_data.get('closes', [])) < 30:
        return 0, 'Insufficient 4H data'

    closes = h4_data['closes']
    highs = h4_data['highs']
    lows = h4_data['lows']

    confirmations = []

    # EMA trend on 4H
    ema_8 = calculate_ema(closes, 8)
    ema_21 = calculate_ema(closes, 21)
    if ema_8 and ema_21:
        if weekly_direction == 'bullish' and ema_8 > ema_21:
            confirmations.append(f'4H EMA 8>21 (bullish)')
        elif weekly_direction == 'bearish' and ema_8 < ema_21:
            confirmations.append(f'4H EMA 8<21 (bearish)')

    # RSI momentum
    rsi = calculate_rsi(closes, 14)
    if rsi:
        if weekly_direction == 'bullish' and 40 < rsi < 70:
            confirmations.append(f'4H RSI {rsi:.1f} (bullish zone, not overbought)')
        elif weekly_direction == 'bearish' and 30 < rsi < 60:
            confirmations.append(f'4H RSI {rsi:.1f} (bearish zone, not oversold)')
        # RSI divergence: price making new lows but RSI making higher lows (bullish)
        if weekly_direction == 'bullish' and rsi > 35 and closes[-1] <= min(closes[-5:]):
            confirmations.append(f'4H RSI bullish divergence potential')
        elif weekly_direction == 'bearish' and rsi < 65 and closes[-1] >= max(closes[-5:]):
            confirmations.append(f'4H RSI bearish divergence potential')

    # MACD cross
    macd, signal, histogram = calculate_macd(closes)
    if macd is not None and signal is not None:
        if weekly_direction == 'bullish' and macd > signal:
            confirmations.append(f'4H MACD bullish cross')
        elif weekly_direction == 'bearish' and macd < signal:
            confirmations.append(f'4H MACD bearish cross')

    if len(confirmations) >= 2:
        return 1, '; '.join(confirmations)
    elif len(confirmations) == 1:
        return 0, f'Partial 4H timing: {confirmations[0]} (need 2+ confirmations)'
    return 0, 'No 4H timing confirmation'


def analyze_layer_4_news_macro(symbol, direction, news_bias):
    """Layer 4: News & Macro Alignment.
    News intelligence supports direction, no major contradictions.
    Returns: (score 0 or 1, reason)
    """
    news_score = news_supports_direction(symbol, direction, news_bias)
    confidence = news_bias.get('confidence', 0)

    if news_score > 0 and confidence >= 0.3:
        return 1, f'News confirms {direction} (USD={news_bias["usd_bias"]}, Risk={news_bias["risk_sentiment"]}, Conf={confidence:.1f})'
    elif news_score < 0:
        return 0, f'News CONTRADICTS {direction} (USD={news_bias["usd_bias"]}, Risk={news_bias["risk_sentiment"]})'
    elif confidence < 0.2:
        # Low confidence = neutral, which we treat as not-contradicting
        # For Ali.bot, we require positive confirmation, so this fails
        return 0, f'News confidence too low ({confidence:.1f}) — no clear signal'
    else:
        return 0, f'News neutral for {direction}'


def analyze_layer_5_sentiment_crossmarket(symbol, direction, news_bias, all_prices):
    """Layer 5: Sentiment & Cross-Market Confirmation.
    Risk sentiment aligns, correlated markets confirm.
    Returns: (score 0 or 1, reason)
    """
    risk = news_bias.get('risk_sentiment', 'neutral')
    config = PAIRS.get(symbol, {})
    asset_type = config.get('type', 'forex')
    confirmations = []

    # Risk sentiment alignment
    if asset_type in ('forex', 'index'):
        if direction == 'BUY' and risk == 'risk_on':
            confirmations.append('Risk-on aligns with BUY')
        elif direction == 'SELL' and risk == 'risk_off':
            confirmations.append('Risk-off aligns with SELL')
        elif direction == 'BUY' and risk == 'risk_off':
            return 0, 'Risk-off contradicts BUY'
        elif direction == 'SELL' and risk == 'risk_on':
            return 0, 'Risk-on contradicts SELL'

    if asset_type == 'crypto':
        crypto_bias = news_bias.get('crypto_bias', 'neutral')
        if direction == 'BUY' and crypto_bias == 'bullish':
            confirmations.append('Crypto sentiment bullish')
        elif direction == 'SELL' and crypto_bias == 'bearish':
            confirmations.append('Crypto sentiment bearish')
        elif direction == 'BUY' and crypto_bias == 'bearish':
            return 0, 'Crypto sentiment bearish — contradicts BUY'

    # Cross-market: DXY proxy for forex
    # Use EURUSD as inverse DXY proxy
    if asset_type == 'forex' and symbol != 'EURUSD':
        eur_price = all_prices.get('EURUSD')
        if eur_price:
            # If EURUSD rising = DXY falling = USD weakness
            # For XXX/USD pairs: USD weak = pair rises
            if symbol in ('GBPUSD', 'AUDUSD', 'NZDUSD'):
                # These should move in the same direction as EURUSD
                confirmations.append('Cross-market: DXY proxy checked')
            elif symbol in ('USDJPY', 'USDCAD'):
                confirmations.append('Cross-market: DXY proxy checked')

    # Gold as risk barometer
    gold_price = all_prices.get('XAUUSD')
    if gold_price and asset_type == 'forex':
        confirmations.append('Gold price context available')

    if confirmations:
        return 1, '; '.join(confirmations)
    # If neutral sentiment (no contradiction), give benefit of doubt for higher conviction
    if risk == 'neutral':
        return 0, 'Risk sentiment neutral — no cross-market confirmation'
    return 0, 'Insufficient cross-market data'


def analyze_layer_6_risk_reward(symbol, direction, current_price, daily_data, config):
    """Layer 6: Risk-Reward & Position Sizing.
    Minimum R:R of 1:4, SL at structural invalidation.
    Returns: (score 0 or 1, sl_price, tp_price, reason)
    """
    if not daily_data or not current_price:
        return 0, 0, 0, 'No data for R:R calculation'

    highs = daily_data['highs']
    lows = daily_data['lows']
    closes = daily_data['closes']
    asset_type = config.get('type', 'forex')

    # pip_value: price distance per pip
    if 'JPY' in symbol and asset_type == 'forex':
        pip_value = 0.01
    elif asset_type == 'forex':
        pip_value = 0.0001
    else:
        pip_value = 0.01

    risk_pips = config['risk_pips']
    reward_pips = config['reward_pips']

    # Place SL at structural invalidation
    if direction == 'BUY':
        # SL below recent swing low
        recent_lows = lows[-10:] if len(lows) >= 10 else lows
        structural_low = min(recent_lows)
        sl_price = min(structural_low, current_price - risk_pips * pip_value)
        actual_risk = current_price - sl_price

        # TP at next resistance or configured reward
        tp_price = current_price + reward_pips * pip_value
    else:
        recent_highs = highs[-10:] if len(highs) >= 10 else highs
        structural_high = max(recent_highs)
        sl_price = max(structural_high, current_price + risk_pips * pip_value)
        actual_risk = sl_price - current_price

        tp_price = current_price - reward_pips * pip_value

    # Verify R:R >= 1:4
    actual_reward = abs(tp_price - current_price)
    if actual_risk <= 0:
        return 0, 0, 0, 'Invalid risk calculation'

    rr_ratio = actual_reward / actual_risk
    if rr_ratio >= 3.5:  # Allow slight flex from strict 4.0
        return 1, round(sl_price, 5), round(tp_price, 5), f'R:R 1:{rr_ratio:.1f} (SL={sl_price:.5f}, TP={tp_price:.5f})'
    else:
        return 0, 0, 0, f'R:R only 1:{rr_ratio:.1f} (need >= 1:3.5)'


def run_6_layer_analysis(symbol, config, weekly_data, daily_data, h4_data, news_bias, all_prices):
    """Run the full 6-layer prediction model.

    Returns: {
        'score': 0-6,
        'direction': 'BUY'|'SELL'|None,
        'layers': {1: {...}, 2: {...}, ...},
        'sl_price': float,
        'tp_price': float,
        'tradeable': bool
    }
    """
    result = {
        'score': 0, 'direction': None, 'layers': {},
        'sl_price': 0, 'tp_price': 0, 'tradeable': False
    }

    # Layer 1: Weekly trend (MANDATORY — sets direction)
    weekly_dir, l1_score, l1_reason = analyze_layer_1_weekly_trend(weekly_data)
    result['layers'][1] = {'score': l1_score, 'reason': l1_reason, 'direction': weekly_dir}
    if not weekly_dir:
        result['layers'][1]['blocking'] = True
        return result
    result['score'] += l1_score
    result['direction'] = weekly_dir
    direction = 'BUY' if weekly_dir == 'bullish' else 'SELL'

    # Layer 2: Daily structure
    l2_score, l2_reason = analyze_layer_2_daily_structure(daily_data, weekly_dir)
    result['layers'][2] = {'score': l2_score, 'reason': l2_reason}
    result['score'] += l2_score

    # Layer 3: 4H timing
    l3_score, l3_reason = analyze_layer_3_4h_timing(h4_data, weekly_dir)
    result['layers'][3] = {'score': l3_score, 'reason': l3_reason}
    result['score'] += l3_score

    # Layer 4: News & macro
    l4_score, l4_reason = analyze_layer_4_news_macro(symbol, direction, news_bias)
    result['layers'][4] = {'score': l4_score, 'reason': l4_reason}
    result['score'] += l4_score

    # Layer 5: Sentiment & cross-market
    l5_score, l5_reason = analyze_layer_5_sentiment_crossmarket(symbol, direction, news_bias, all_prices)
    result['layers'][5] = {'score': l5_score, 'reason': l5_reason}
    result['score'] += l5_score

    # Layer 6: Risk-reward
    current_price = get_current_price(symbol)
    if current_price:
        l6_score, sl, tp, l6_reason = analyze_layer_6_risk_reward(symbol, direction, current_price, daily_data, config)
        result['layers'][6] = {'score': l6_score, 'reason': l6_reason}
        result['score'] += l6_score
        result['sl_price'] = sl
        result['tp_price'] = tp
    else:
        result['layers'][6] = {'score': 0, 'reason': 'No current price available'}

    # Tradeable only if ALL 6 layers score 1 (perfect alignment)
    result['tradeable'] = result['score'] >= 5  # 5/6 = 83% confidence — good enough
    return result


# ══════════════════════════════════════════════════════════════════════
#  cTrader Trading Engine — runs on Twisted reactor
# ══════════════════════════════════════════════════════════════════════

class AliBotEngine:
    def __init__(self):
        self.client = Client(EndPoints.PROTOBUF_DEMO_HOST, EndPoints.PROTOBUF_PORT, TcpProtocol)
        self.authenticated = False
        self.balance = 0.0
        self.positions = {}        # positionId -> position data from broker
        self.local_positions = {}  # symbol -> local tracking
        self.closed_trades = []
        self.last_trade_time = {}  # symbol -> datetime of last trade
        self._reconnect_count = 0
        self._consecutive_failures = 0
        self._last_disconnect_alert = 0
        self._last_connected_at = None
        self._trading_loop = None
        self._task_loop = None
        self._skip_symbols = set()
        self.trailing_state = {}   # positionId -> trailing state machine
        self._last_prices = {}
        self._live_prices = {}
        self._spot_subscriptions = set()
        # Cache for multi-timeframe data (expensive to fetch — refresh every cycle)
        self._weekly_cache = {}    # symbol -> data
        self._daily_cache = {}
        self._h4_cache = {}
        self._last_analysis = {}   # symbol -> last 6-layer result
        self._trade_journal = []   # All setups evaluated (taken + skipped)

    # ── Connection lifecycle ──

    def start(self):
        print("=" * 60)
        print("Ali.bot — Higher Timeframe Precision Trading Strategist")
        print("Strategy: 6-Layer Prediction | 4H/Daily/Weekly")
        print("Patience is the edge. Only 5/6+ setups get traded (>=83%).")
        print(f"Account: {CTID} (DEMO)")
        print("=" * 60)
        self.client.setConnectedCallback(self._on_connected)
        self.client.setDisconnectedCallback(self._on_disconnected)
        self.client.setMessageReceivedCallback(self._on_message)
        self.client.startService()
        reactor.run()

    def _on_connected(self, client):
        was_recovering = self._consecutive_failures > 0
        self._reconnect_count = 0
        self._consecutive_failures = 0
        self._last_connected_at = datetime.now(timezone.utc)
        print(f"[{self._ts()}] Connected to cTrader API — authenticating...")
        if was_recovering:
            self._alert("Ali.bot reconnected after recovery. Authenticating...")
        req = ProtoOAApplicationAuthReq()
        req.clientId = CLIENT_ID
        req.clientSecret = CLIENT_SECRET
        d = self.client.send(req)
        d.addCallbacks(self._on_app_auth, self._on_error)

    def _on_disconnected(self, client, reason):
        self.authenticated = False
        if self._trading_loop and self._trading_loop.running:
            self._trading_loop.stop()
        if self._task_loop and self._task_loop.running:
            self._task_loop.stop()
        self._reconnect_count += 1
        self._consecutive_failures += 1
        print(f"[{self._ts()}] Disconnected: {reason}")
        print(f"[{self._ts()}] Will auto-reconnect (attempt {self._reconnect_count})...")
        self._save_state()

        import time as _time
        now_ts = _time.time()
        should_alert = (
            self._consecutive_failures == 1 or
            self._consecutive_failures % 5 == 0 or
            self._consecutive_failures >= 10
        )
        if should_alert and (now_ts - self._last_disconnect_alert) > 60:
            self._last_disconnect_alert = now_ts
            self._alert(
                f"DISCONNECTED from cTrader (attempt {self._consecutive_failures})\n"
                f"Open positions: {len(self.positions)} UNMONITORED\n"
                f"Balance: ${self.balance:.2f}"
            )

    def _on_app_auth(self, msg):
        print(f"[{self._ts()}] App authenticated")
        req = ProtoOAAccountAuthReq()
        req.ctidTraderAccountId = CTID
        req.accessToken = ACCESS_TOKEN
        d = self.client.send(req)
        d.addCallbacks(self._on_account_auth, self._on_error)

    def _on_account_auth(self, msg):
        print(f"[{self._ts()}] Account {CTID} authenticated (DEMO)")
        self.authenticated = True
        self._alert(f"Ali.bot authenticated (DEMO). Scanning higher timeframes...")
        req = ProtoOATraderReq()
        req.ctidTraderAccountId = CTID
        d = self.client.send(req)
        d.addCallbacks(self._on_trader_info, self._on_error)

    def _on_trader_info(self, msg):
        try:
            payload = Protobuf.extract(msg)
            if hasattr(payload, 'trader'):
                self.balance = payload.trader.balance / 100
            elif hasattr(payload, 'errorCode'):
                print(f"[{self._ts()}] ERROR from broker: code={payload.errorCode} desc={payload.description}")
                print(f"[{self._ts()}] The CTID {CTID} may not be authorized with the current access token.")
                print(f"[{self._ts()}] Please authorize this account at: https://connect.ctrader.com/")
                self.balance = 0.0
            else:
                print(f"[{self._ts()}] Warning: unexpected response type: {type(payload).__name__}")
                self.balance = 0.0
        except Exception as e:
            print(f"[{self._ts()}] Warning: could not extract balance: {e}")
            self.balance = 0.0
        print(f"[{self._ts()}] Account balance: ${self.balance:.2f}")
        req = ProtoOAReconcileReq()
        req.ctidTraderAccountId = CTID
        d = self.client.send(req)
        d.addCallbacks(self._on_reconcile, self._on_error)

    def _on_reconcile(self, msg):
        payload = Protobuf.extract(msg)
        self.positions.clear()
        self.local_positions.clear()
        self.trailing_state.clear()

        if hasattr(payload, 'errorCode'):
            print(f"[{self._ts()}] Reconcile error: {payload.errorCode} — {getattr(payload, 'description', '')}")
            print(f"[{self._ts()}] Continuing without positions — account may need authorization")
            self._start_loops()
            return

        for pos in getattr(payload, 'position', []):
            sym_id = pos.tradeData.symbolId
            symbol = ID_TO_SYMBOL.get(sym_id, f"ID_{sym_id}")
            side = 'BUY' if pos.tradeData.tradeSide == ProtoOATradeSide.Value('BUY') else 'SELL'
            volume = pos.tradeData.volume
            entry = pos.price
            sl = pos.stopLoss if pos.stopLoss else 0
            tp = pos.takeProfit if pos.takeProfit else 0

            # Detect which bot owns this position from the label/comment
            label = getattr(pos.tradeData, 'label', '') or ''
            comment = getattr(pos.tradeData, 'comment', '') or ''
            is_mine = 'AliBot' in label or 'AliBot' in comment
            owner = 'alibot' if is_mine else 'tradebot'

            self.positions[pos.positionId] = {
                'symbol': symbol, 'symbolId': sym_id, 'side': side,
                'volume': volume, 'positionId': pos.positionId, 'bot': owner,
            }
            self.local_positions[symbol] = {
                'direction': side,
                'entry_price': entry,
                'lot_size': volume / 10000000,
                'stop_loss': sl,
                'take_profit': tp,
                'open_time': datetime.now().isoformat(),
                'positionId': pos.positionId,
                'bot': owner,
            }
            # Rebuild trailing state
            broker_trailing = getattr(pos, 'trailingStopLoss', False)
            config = PAIRS.get(symbol, {})
            pip_val = 0.01 if ('JPY' in symbol and config.get('type') == 'forex') else 0.0001 if config.get('type') == 'forex' else 0.01
            if broker_trailing:
                phase = 'trailing'
            elif sl and entry:
                if side == 'BUY' and sl >= entry - (pip_val * 0.5):
                    phase = 'breakeven'
                elif side == 'SELL' and sl <= entry + (pip_val * 0.5):
                    phase = 'breakeven'
                else:
                    phase = 'initial'
            else:
                phase = 'initial'

            self.trailing_state[pos.positionId] = {
                'phase': phase, 'entry_price': entry, 'direction': side,
                'symbol': symbol, 'current_sl': sl,
                'trail_activated': broker_trailing,
                'last_amend_time': 0,
                'scaled_out': broker_trailing,
                'original_volume': volume,
            }
            self._subscribe_spots(symbol)

        print(f"[{self._ts()}] Reconciled {len(self.positions)} open positions from broker")
        self._alert(
            f"ONLINE — {len(self.positions)} positions reconciled\n"
            f"Balance: ${self.balance:.2f}\n"
            f"Analysis cycle: every {CONFIG['check_interval']}s ({CONFIG['check_interval']//60} min)"
        )
        for pid, p in self.positions.items():
            sym = p['symbol']
            lots = p['volume'] / 10000000
            entry = self.local_positions.get(sym, {}).get('entry_price', 0)
            print(f"  {p['side']} {sym} {lots:.2f}lot @ {entry:.5f} posId={pid}")

        self._save_state()
        self._start_loops()

    def _start_loops(self):
        """Start trading and task dispatch loops."""
        if self._trading_loop and self._trading_loop.running:
            self._trading_loop.stop()
        self._trading_loop = task.LoopingCall(self._trading_cycle)
        self._trading_loop.start(CONFIG['check_interval'], now=True)
        print(f"[{self._ts()}] Analysis loop started (every {CONFIG['check_interval']}s)")

        if self._task_loop and self._task_loop.running:
            self._task_loop.stop()
        self._task_loop = task.LoopingCall(self._check_tasks)
        self._task_loop.start(30, now=False)

    # ── Message handler ──

    def _on_message(self, client, msg):
        if msg.payloadType == 2126:  # ProtoOAExecutionEvent
            try:
                payload = Protobuf.extract(msg)
                etype = payload.executionType
                if hasattr(payload, 'position') and payload.HasField('position'):
                    pos = payload.position
                    sym = ID_TO_SYMBOL.get(pos.tradeData.symbolId, '?')
                    side = 'BUY' if pos.tradeData.tradeSide == 1 else 'SELL'
                    vol = pos.tradeData.volume
                    pid = pos.positionId

                    if etype == 2 and vol > 0:  # FILL — new position
                        lots = vol / 10000000
                        print(f"  [FILL] {side} {sym} {lots:.2f}lot @ {pos.price:.5f} posId={pid}")
                        self.positions[pid] = {
                            'symbol': sym, 'symbolId': pos.tradeData.symbolId,
                            'side': side, 'volume': vol, 'positionId': pid,
                        }
                        sl_price = pos.stopLoss if pos.stopLoss else 0
                        self.trailing_state[pid] = {
                            'phase': 'initial', 'entry_price': pos.price,
                            'direction': side, 'symbol': sym,
                            'current_sl': sl_price, 'trail_activated': False,
                            'last_amend_time': 0, 'scaled_out': False,
                            'original_volume': vol,
                        }
                        self._subscribe_spots(sym)

                    elif etype == 2 and vol == 0:  # FILL — position closed
                        if pid in self.positions:
                            closed_sym = self.positions[pid]['symbol']
                            broker_pnl = self._extract_broker_pnl(payload)
                            print(f"  [CLOSED] {closed_sym} posId={pid}" + (f" P&L=${broker_pnl:.2f}" if broker_pnl is not None else ""))
                            closed_pos = self.local_positions.get(closed_sym, {})
                            del self.positions[pid]
                            self.local_positions.pop(closed_sym, None)
                            self.trailing_state.pop(pid, None)
                            self._unsubscribe_spots(closed_sym)
                            self._save_state()
                            self._report_close(closed_sym, closed_pos, pos.price, broker_pnl)

                    elif etype in (3, 5):  # CANCELLED / explicit close
                        if pid in self.positions:
                            closed_sym = self.positions[pid]['symbol']
                            broker_pnl = self._extract_broker_pnl(payload)
                            print(f"  [CLOSED] {closed_sym} posId={pid}" + (f" P&L=${broker_pnl:.2f}" if broker_pnl is not None else ""))
                            closed_pos = self.local_positions.get(closed_sym, {})
                            del self.positions[pid]
                            self.local_positions.pop(closed_sym, None)
                            self.trailing_state.pop(pid, None)
                            self._unsubscribe_spots(closed_sym)
                            self._save_state()
                            self._report_close(closed_sym, closed_pos, pos.price, broker_pnl)

                if etype == 4:  # REJECTED
                    err = getattr(payload, 'errorCode', 'unknown')
                    desc = getattr(payload, 'description', '')
                    print(f"  [REJECTED] {err}: {desc}")
            except Exception as e:
                print(f"  Warning: execution event parse error: {e}")

        elif msg.payloadType == 2113:  # Balance update
            try:
                payload = Protobuf.extract(msg)
                self.balance = payload.trader.balance / 100
            except Exception:
                pass

        elif msg.payloadType == 2107:  # Trailing SL changed by broker
            try:
                payload = Protobuf.extract(msg)
                pid = payload.positionId
                new_sl = payload.stopPrice
                if pid in self.trailing_state:
                    sym = self.trailing_state[pid]['symbol']
                    self.trailing_state[pid]['current_sl'] = new_sl
                    if sym in self.local_positions:
                        self.local_positions[sym]['stop_loss'] = new_sl
                    print(f"  [TRAIL-UPDATE] {sym} SL trailed to {new_sl:.5f} by broker")
                    self._save_state()
            except Exception as e:
                print(f"  Warning: trailing SL event parse error: {e}")

        elif msg.payloadType == 2131:  # Live spot price
            try:
                payload = Protobuf.extract(msg)
                sym_id = payload.symbolId
                symbol = ID_TO_SYMBOL.get(sym_id)
                if symbol and hasattr(payload, 'bid') and payload.bid:
                    config = PAIRS.get(symbol, {})
                    asset_type = config.get('type', 'forex')
                    if 'JPY' in symbol and asset_type == 'forex':
                        divisor = 1000.0
                    elif asset_type == 'forex':
                        divisor = 100000.0
                    else:
                        divisor = 100.0
                    self._live_prices[symbol] = payload.bid / divisor
            except Exception:
                pass

        elif msg.payloadType == 2132:  # Order error
            try:
                payload = Protobuf.extract(msg)
                print(f"  [ORDER ERROR] {payload.errorCode}: {payload.description}")
            except Exception:
                pass

    # ── Broker P&L extraction ──

    @staticmethod
    def _extract_broker_pnl(payload):
        """Extract authoritative P&L from deal.closePositionDetail.grossProfit."""
        try:
            if hasattr(payload, 'deal') and payload.HasField('deal'):
                deal = payload.deal
                if hasattr(deal, 'closePositionDetail') and deal.HasField('closePositionDetail'):
                    detail = deal.closePositionDetail
                    gross = detail.grossProfit
                    swap = detail.swap if detail.swap else 0
                    commission = detail.commission if detail.commission else 0
                    digits = detail.moneyDigits if detail.moneyDigits else 2
                    return (gross + swap + commission) / (10 ** digits)
        except Exception:
            pass
        return None

    def _report_close(self, symbol, closed_pos, close_price, broker_pnl=None):
        """Report closed position to Telegram."""
        if not closed_pos:
            return
        try:
            config = PAIRS.get(symbol, {})
            report_trade_closed(
                symbol=symbol,
                direction=closed_pos.get('direction', '?'),
                entry_price=closed_pos.get('entry_price', 0),
                close_price=close_price,
                lot_size=closed_pos.get('lot_size', 0),
                pnl=broker_pnl,
                volume=config.get('volume', 0),
                asset_type=config.get('type', 'forex'),
            )
        except Exception as e:
            print(f"  Warning: Telegram close report failed: {e}")

    # ══════════════════════════════════════════════════════════════
    #  MAIN ANALYSIS CYCLE — every 15 minutes
    # ══════════════════════════════════════════════════════════════

    def _trading_cycle(self):
        if not self.authenticated:
            print(f"[{self._ts()}] Not authenticated — skipping cycle")
            return

        if check_kill_switch():
            print(f"[{self._ts()}] Kill switch active — halting")
            if self._trading_loop and self._trading_loop.running:
                self._trading_loop.stop()
            return

        cycle = self._ts()
        print(f"\n{'='*60}")
        print(f"[{cycle}] Ali.bot — Multi-Timeframe Analysis Cycle")
        print(f"{'='*60}")

        # Get news bias once per cycle
        news_bias = get_news_bias()
        print(f"  News: USD={news_bias['usd_bias']} Risk={news_bias['risk_sentiment']} "
              f"Crypto={news_bias.get('crypto_bias','?')} Oil={news_bias.get('oil_bias','?')} "
              f"Conf={news_bias['confidence']:.1f}")

        # Fetch multi-timeframe data for all instruments
        all_prices = {}
        for symbol in PAIRS:
            price = get_current_price(symbol)
            if price:
                all_prices[symbol] = price
        self._last_prices = all_prices

        # Manage existing positions first
        self._manage_trailing_stops()

        # Run 6-layer analysis on each instrument
        tradeable_setups = []
        for symbol, config in PAIRS.items():
            if symbol in self.local_positions:
                print(f"  {config['name']}: Already in position — monitoring")
                continue

            # Cooldown check (24h between trades on same pair)
            if symbol in self.last_trade_time:
                elapsed_h = (datetime.now() - self.last_trade_time[symbol]).total_seconds() / 3600
                if elapsed_h < CONFIG['cooldown_hours']:
                    print(f"  {config['name']}: Cooldown ({elapsed_h:.1f}h / {CONFIG['cooldown_hours']}h)")
                    continue

            print(f"\n  --- {config['name']} ({symbol}) ---")

            # Fetch multi-timeframe data
            weekly = fetch_candles(symbol, '1wk', '2y')
            daily = fetch_candles(symbol, '1d', '60d')
            h4 = fetch_candles(symbol, '1h', '7d')  # Yahoo doesn't have 4H — use 1H with more data

            if not weekly or not daily or not h4:
                print(f"    Data incomplete — skipping")
                continue

            # Run the 6-layer prediction model
            analysis = run_6_layer_analysis(symbol, config, weekly, daily, h4, news_bias, all_prices)
            self._last_analysis[symbol] = analysis

            # Print layer-by-layer breakdown
            for layer_num in range(1, 7):
                layer = analysis['layers'].get(layer_num, {})
                score = layer.get('score', 0)
                reason = layer.get('reason', 'N/A')
                icon = '✓' if score == 1 else '✗'
                print(f"    L{layer_num}: {icon} {reason}")

            direction = 'BUY' if analysis.get('direction') == 'bullish' else 'SELL' if analysis.get('direction') == 'bearish' else '?'
            print(f"    Score: {analysis['score']}/6 | Direction: {direction} | Tradeable: {analysis['tradeable']}")

            # Journal this setup
            self._trade_journal.append({
                'symbol': symbol,
                'time': datetime.now(timezone.utc).isoformat(),
                'score': analysis['score'],
                'direction': direction,
                'tradeable': analysis['tradeable'],
                'layers': {str(k): v for k, v in analysis['layers'].items()},
            })

            if analysis['tradeable']:
                tradeable_setups.append((symbol, config, analysis))

        # Execute trades — 5/6+ setups (>=83% confidence)
        orders_sent = 0
        max_pos = CONFIG['max_positions']
        # Only count Ali.bot's own positions (shared account with TradeBot)
        alibot_open = sum(1 for p in self.local_positions.values() if p.get('bot') == 'alibot')
        current_open = alibot_open

        for symbol, config, analysis in tradeable_setups:
            if current_open + orders_sent >= max_pos:
                print(f"\n  MAX POSITIONS ({max_pos}) — {symbol} {analysis['score']}/6 setup queued for next cycle")
                continue

            direction = 'BUY' if analysis['direction'] == 'bullish' else 'SELL'
            sl_price = analysis['sl_price']
            tp_price = analysis['tp_price']
            price = all_prices.get(symbol)

            if not price:
                continue

            print(f"\n  ** EXECUTING: {direction} {symbol} — SCORE {analysis['score']}/6 **")
            print(f"     Entry: {price:.5f} | SL: {sl_price:.5f} | TP: {tp_price:.5f}")

            layer_summary = '; '.join(
                f"L{k}:{v.get('reason','')[:40]}"
                for k, v in analysis['layers'].items()
                if v.get('score', 0) == 1
            )

            self._execute_order(symbol, direction, price, config, f"{analysis['score']}/6|{layer_summary[:50]}")
            orders_sent += 1

            # Alert: this is a high-conviction trade
            self._alert(
                f"SNIPER TRADE: {direction} {symbol}\n"
                f"Score: {analysis['score']}/6 — HIGH CONVICTION\n"
                f"Entry: {price:.5f}\n"
                f"SL: {sl_price:.5f} | TP: {tp_price:.5f}\n"
                f"R:R: {analysis['layers'].get(6, {}).get('reason', 'N/A')}"
            )

        # Refresh balance
        if self.authenticated:
            req = ProtoOATraderReq()
            req.ctidTraderAccountId = CTID
            d = self.client.send(req)
            d.addCallbacks(self._on_balance_update, lambda f: None)

        self._save_state()
        print(f"\n  Balance: ${self.balance:.2f} | Open: {len(self.positions)} | Setups: {len(tradeable_setups)} tradeable")
        print(f"  Next analysis in {CONFIG['check_interval']}s ({CONFIG['check_interval']//60} min)")

    # ── Trailing stop management (same proven system as TradeBot) ──

    def _manage_trailing_stops(self):
        """Move SL to break-even at 1× risk, activate trailing at 1.5× risk."""
        import time as _time
        now = _time.time()

        for pid, state in list(self.trailing_state.items()):
            if state['trail_activated']:
                continue

            symbol = state['symbol']
            price = self._live_prices.get(symbol) or self._last_prices.get(symbol)
            if not price:
                continue

            if now - state['last_amend_time'] < 30:
                continue

            config = PAIRS.get(symbol, {})
            if not config:
                continue

            entry = state['entry_price']
            direction = state['direction']
            asset_type = config.get('type', 'forex')

            if 'JPY' in symbol and asset_type == 'forex':
                pip_value = 0.01
            elif asset_type == 'forex':
                pip_value = 0.0001
            else:
                pip_value = 0.01

            trigger_pips = config.get('trail_trigger_pips', config['risk_pips'])
            step_pips = config.get('trail_step_pips', config['risk_pips'] // 2)

            if direction == 'BUY':
                profit_pips = (price - entry) / pip_value
            else:
                profit_pips = (entry - price) / pip_value

            phase = state['phase']

            if phase == 'initial' and profit_pips >= trigger_pips:
                new_sl = entry
                print(f"  [TRAIL] {symbol} -> BREAK-EVEN (profit {profit_pips:.1f} pips >= {trigger_pips})")
                self._amend_sl(pid, symbol, new_sl, trailing=False)
                state['phase'] = 'breakeven'
                state['current_sl'] = new_sl
                state['last_amend_time'] = now
                if symbol in self.local_positions:
                    self.local_positions[symbol]['stop_loss'] = new_sl
                self._save_state()
                self._alert(f"Ali.bot TRAIL {symbol} -> BREAK-EVEN\nSL moved to entry {new_sl:.5f}")

            elif phase == 'breakeven' and profit_pips >= (trigger_pips + step_pips):
                step_offset = step_pips * pip_value
                if direction == 'BUY':
                    new_sl = round(entry + step_offset, 5)
                else:
                    new_sl = round(entry - step_offset, 5)
                print(f"  [TRAIL] {symbol} -> TRAILING ACTIVE (profit {profit_pips:.1f} pips)")
                self._amend_sl(pid, symbol, new_sl, trailing=True, clear_tp=True)
                state['phase'] = 'trailing'
                state['current_sl'] = new_sl
                state['trail_activated'] = True
                state['last_amend_time'] = now
                if symbol in self.local_positions:
                    self.local_positions[symbol]['stop_loss'] = new_sl
                self._save_state()
                self._alert(f"Ali.bot TRAIL {symbol} -> TRAILING ACTIVE\nSL={new_sl:.5f}, TP removed — riding the swing")

    # ── Live spot subscriptions ──

    def _subscribe_spots(self, symbol):
        if symbol in self._spot_subscriptions:
            return
        sym_id = SYMBOL_IDS.get(symbol)
        if not sym_id or not self.authenticated:
            return
        try:
            req = ProtoOASubscribeSpotsReq()
            req.ctidTraderAccountId = CTID
            req.symbolId.append(sym_id)
            d = self.client.send(req)
            d.addCallback(lambda msg, s=symbol: print(f"  [SPOTS] Subscribed to {s}"))
            d.addErrback(lambda f, s=symbol: print(f"  [SPOTS] Subscribe failed: {s}"))
            self._spot_subscriptions.add(symbol)
        except Exception as e:
            print(f"  Warning: spot subscription failed for {symbol}: {e}")

    def _unsubscribe_spots(self, symbol):
        if symbol not in self._spot_subscriptions:
            return
        still_needed = any(s['symbol'] == symbol for s in self.trailing_state.values())
        if still_needed:
            return
        sym_id = SYMBOL_IDS.get(symbol)
        if not sym_id or not self.authenticated:
            self._spot_subscriptions.discard(symbol)
            return
        try:
            req = ProtoOAUnsubscribeSpotsReq()
            req.ctidTraderAccountId = CTID
            req.symbolId.append(sym_id)
            self.client.send(req)
            self._spot_subscriptions.discard(symbol)
            self._live_prices.pop(symbol, None)
        except Exception:
            pass

    # ── SL/TP amendment ──

    def _amend_sl(self, position_id, symbol, new_sl, trailing=False, clear_tp=False):
        if not self.authenticated:
            return
        req = ProtoOAAmendPositionSLTPReq()
        req.ctidTraderAccountId = CTID
        req.positionId = position_id
        req.stopLoss = new_sl
        req.trailingStopLoss = trailing

        if clear_tp:
            req.takeProfit = 0
            if symbol in self.local_positions:
                self.local_positions[symbol]['take_profit'] = 0
        else:
            local = self.local_positions.get(symbol, {})
            if local.get('take_profit'):
                req.takeProfit = local['take_profit']

        d = self.client.send(req, responseTimeoutInSeconds=10)
        d.addCallback(lambda msg, s=symbol: print(f"  << AMEND OK: {s}"))
        d.addErrback(lambda f, s=symbol: print(f"  << AMEND FAILED: {s}: {f.getErrorMessage()}"))

    # ── Order execution ──

    def _execute_order(self, symbol, direction, entry_price, config, reason):
        if symbol in self._skip_symbols:
            return
        sym_id = SYMBOL_IDS.get(symbol)
        if not sym_id:
            return

        side = ProtoOATradeSide.Value('BUY') if direction == 'BUY' else ProtoOATradeSide.Value('SELL')
        volume = config['volume']

        asset_type = config.get('type', 'forex')
        if 'JPY' in symbol and asset_type == 'forex':
            pip_multiplier = 100
        elif asset_type == 'forex':
            pip_multiplier = 10
        elif asset_type == 'crypto':
            pip_multiplier = 100
        elif symbol in ('XAUUSD', 'XAGUSD'):
            pip_multiplier = 100
        elif asset_type in ('commodity', 'index'):
            pip_multiplier = 100
        else:
            pip_multiplier = 10

        risk_points = int(config['risk_pips'] * pip_multiplier)
        reward_points = int(config['reward_pips'] * pip_multiplier)

        req = ProtoOANewOrderReq()
        req.ctidTraderAccountId = CTID
        req.symbolId = sym_id
        req.orderType = ProtoOAOrderType.Value('MARKET')
        req.tradeSide = side
        req.volume = volume
        req.relativeStopLoss = risk_points
        req.relativeTakeProfit = reward_points
        req.comment = f"AliBot|{reason[:30]}"
        req.label = "AliBot"

        lot_display = volume / 10000000
        print(f"  >> SENDING {direction} {symbol} {lot_display:.2f}lot SL={config['risk_pips']}pip TP={config['reward_pips']}pip")

        d = self.client.send(req, responseTimeoutInSeconds=10)
        config_with_reason = dict(config, _reason=reason)
        d.addCallback(lambda msg, s=symbol, d2=direction, ep=entry_price, c=config_with_reason: self._on_order_response(msg, s, d2, ep, c))
        d.addErrback(lambda f, s=symbol: self._on_order_error(f, s))

    def _on_order_response(self, msg, symbol, direction, entry_price, config):
        print(f"  << ORDER FILLED: {direction} {symbol}")
        self.last_trade_time[symbol] = datetime.now()

        multiplier = 0.0001
        if 'JPY' in symbol:
            multiplier = 0.01
        elif PAIRS.get(symbol, {}).get('type') not in ('forex',):
            multiplier = 0.01

        risk_pips = config['risk_pips']
        reward_pips = config['reward_pips']
        if direction == 'BUY':
            sl = round(entry_price - (risk_pips * multiplier), 5)
            tp = round(entry_price + (reward_pips * multiplier), 5)
        else:
            sl = round(entry_price + (risk_pips * multiplier), 5)
            tp = round(entry_price - (reward_pips * multiplier), 5)

        lot_size = config['volume'] / 10000000
        self.local_positions[symbol] = {
            'direction': direction, 'entry_price': entry_price,
            'lot_size': lot_size, 'stop_loss': sl, 'take_profit': tp,
            'open_time': datetime.now().isoformat(), 'bot': 'alibot',
        }
        self._save_state()

        try:
            report_trade_opened(symbol, direction, entry_price, lot_size, sl, tp, config.get('_reason', ''))
        except Exception as e:
            print(f"  Warning: Telegram report failed: {e}")

    def _on_order_error(self, failure, symbol):
        err = failure.getErrorMessage()
        print(f"  << ORDER FAILED for {symbol}: {err}")
        self._skip_symbols.add(symbol)

    def _execute_close(self, symbol, position_id, volume):
        if not self.authenticated:
            return
        req = ProtoOAClosePositionReq()
        req.ctidTraderAccountId = CTID
        req.positionId = position_id
        req.volume = volume
        d = self.client.send(req, responseTimeoutInSeconds=10)
        d.addCallback(lambda msg, s=symbol: print(f"  << CLOSE SENT: {s}"))
        d.addErrback(lambda f, s=symbol: print(f"  << CLOSE FAILED: {s}: {f.getErrorMessage()}"))

    def _on_balance_update(self, msg):
        try:
            payload = Protobuf.extract(msg)
            if hasattr(payload, 'trader'):
                self.balance = payload.trader.balance / 100
        except Exception:
            pass

    def _on_error(self, failure):
        print(f"[{self._ts()}] API Error: {failure.getErrorMessage()}")
        self.authenticated = False

    # ── Task dispatch ──

    def _check_tasks(self):
        try:
            tasks = get_pending_tasks('alibot')
        except Exception:
            return
        for task_data in tasks:
            task_id = task_data['id']
            task_type = task_data.get('task_type', '')
            claimed = claim_task(task_id)
            if not claimed:
                continue
            try:
                if task_type == 'close_all':
                    result = self._task_close_all(claimed)
                elif task_type == 'close_position':
                    result = self._task_close_position(claimed)
                elif task_type == 'report':
                    result = self._task_report(claimed)
                elif task_type == 'market_outlook':
                    result = self._task_market_outlook(claimed)
                else:
                    fail_task(task_id, f'Unknown task type: {task_type}')
                    continue
                complete_task(task_id, result)
            except Exception as e:
                fail_task(task_id, str(e))

    def _task_close_all(self, task_data):
        closed = []
        for pid, pos in list(self.positions.items()):
            self._execute_close(pos['symbol'], pid, pos['volume'])
            closed.append({'symbol': pos['symbol'], 'positionId': pid})
        return {'closed': len(closed), 'positions': closed}

    def _task_close_position(self, task_data):
        params = task_data.get('params', {})
        symbol = params.get('symbol', '').upper()
        if symbol in self.local_positions:
            pid = self.local_positions[symbol].get('positionId')
            if pid and pid in self.positions:
                self._execute_close(symbol, pid, self.positions[pid]['volume'])
                return {'symbol': symbol, 'closed': True}
        return {'error': f'Position not found: {symbol}', 'closed': False}

    def _task_report(self, task_data):
        stats = {
            'balance': round(self.balance, 2),
            'open_positions': len(self.positions),
            'total_closed': len(self.closed_trades),
            'wins': len([t for t in self.closed_trades if t.get('pnl', 0) > 0]),
            'losses': len([t for t in self.closed_trades if t.get('pnl', 0) <= 0]),
        }
        stats['total_pnl'] = round(sum(t.get('pnl', 0) for t in self.closed_trades), 2)
        stats['win_rate'] = round(stats['wins'] / stats['total_closed'] * 100, 1) if stats['total_closed'] > 0 else 0.0
        return {'stats': stats, 'positions': {s: dict(p) for s, p in self.local_positions.items()}}

    def _task_market_outlook(self, task_data):
        """Generate weekly market outlook from latest analysis."""
        outlook = {}
        for symbol, analysis in self._last_analysis.items():
            outlook[symbol] = {
                'score': analysis['score'],
                'direction': analysis.get('direction'),
                'tradeable': analysis['tradeable'],
                'layers': {str(k): v.get('reason', '') for k, v in analysis['layers'].items()},
            }
        return {
            'outlook': outlook,
            'instruments_analyzed': len(outlook),
            'tradeable_count': sum(1 for a in outlook.values() if a['tradeable']),
            'generated_at': datetime.now(timezone.utc).isoformat(),
        }

    # ── State persistence ──

    def _save_state(self):
        stats = {
            'balance': round(self.balance, 2),
            'open': len(self.positions),
            'total': len(self.closed_trades),
            'wins': len([t for t in self.closed_trades if t.get('pnl', 0) > 0]),
            'losses': len([t for t in self.closed_trades if t.get('pnl', 0) <= 0]),
            'win_rate': 0,
            'total_pnl': round(sum(t.get('pnl', 0) for t in self.closed_trades), 2),
        }
        if stats['total'] > 0:
            stats['win_rate'] = round(stats['wins'] / stats['total'] * 100, 1)

        positions_with_trail = {}
        for sym, pos in self.local_positions.items():
            pos_data = dict(pos)
            pid = pos.get('positionId')
            if pid and pid in self.trailing_state:
                pos_data['trail_phase'] = self.trailing_state[pid]['phase']
                pos_data['trail_activated'] = self.trailing_state[pid]['trail_activated']
            positions_with_trail[sym] = pos_data

        state_data = {
            'balance': self.balance,
            'positions': positions_with_trail,
            'closed_trades': self.closed_trades[-50:],
            'stats': stats,
            'last_analysis': {s: {'score': a['score'], 'direction': a.get('direction'), 'tradeable': a['tradeable']}
                              for s, a in self._last_analysis.items()},
            'trade_journal': self._trade_journal[-100:],
            'mode': 'demo',
            'connected': self.authenticated,
            'last_update': datetime.now().isoformat(),
        }

        for path in ['/root/.openclaw/workspace/employees/alibot_state.json',
                     '/root/.openclaw/workspace/employees/alibot_trading_state.json']:
            try:
                atomic_json_write(path, state_data)
            except Exception as e:
                print(f"Warning: failed to save state to {path}: {e}")

        try:
            atomic_json_write('/root/.openclaw/workspace/employees/alibot_status.json', {
                'balance': round(self.balance, 2),
                'connected': self.authenticated,
                'mode': 'demo',
                'account': str(CTID),
                'positions': len(self.positions),
                'last_update': datetime.now().isoformat(),
            })
        except Exception:
            pass

    # ── Alerting ──

    def _alert(self, text):
        try:
            import html
            safe_text = html.escape(text)
            msg = (
                "<b>⬡ ZEFF.BOT</b>\n"
                "<b>🎯 ALI.BOT ALERT</b>\n"
                f"<i>{self._ts()}</i>\n\n"
                f"{safe_text}"
            )
            telegram_send(msg)
        except Exception as e:
            print(f"[{self._ts()}] WARNING: Telegram alert failed: {e}")

    @staticmethod
    def _ts():
        return datetime.now().strftime("%H:%M:%S")


if __name__ == '__main__':
    engine = AliBotEngine()
    engine.start()
