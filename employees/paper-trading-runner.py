#!/usr/bin/env python3
"""
TradeBot - Institutional Strategy: Liquidity Sweep + Volume Profile + VWAP + Order Flow
Risk:Reward 1:3 + Trailing Stop | Focus on market opens
Executes real trades on IC Markets cTrader Demo account via Open API
"""

import requests
import json
import os
import time as _time
from datetime import datetime, timezone, timedelta

# Safety imports
import sys
sys.path.insert(0, '/root/.openclaw/workspace')
from lib.trading_safety import check_kill_switch, validate_price, pre_trade_checks, estimate_dollar_risk, validate_rr, MIN_RR_RATIO
from lib.credentials import get_icm_credentials
from lib.atomic_write import atomic_json_write
from lib.task_dispatch import (
    get_pending_tasks, claim_task, complete_task, fail_task,
)
from lib.zeffbot_report import report_trade_opened, report_trade_closed
from lib.telegram import send_message as telegram_send, send_premium_signal

# Twisted + cTrader API
from twisted.internet import reactor, task, defer, threads
from twisted.internet.error import ConnectionLost, ConnectionDone
from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq, ProtoOAAccountAuthReq, ProtoOANewOrderReq,
    ProtoOAClosePositionReq, ProtoOAReconcileReq, ProtoOATraderReq,
    ProtoOASubscribeSpotsReq, ProtoOAUnsubscribeSpotsReq,
    ProtoOAGetPositionUnrealizedPnLReq,
    ProtoOAAmendPositionSLTPReq,
    ProtoOAGetTrendbarsReq,
    ProtoOASubscribeDepthQuotesReq,
    ProtoOADealListReq,
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
    ProtoOAOrderType, ProtoOATradeSide, ProtoOATrendbarPeriod,
)

# Load credentials
_creds = get_icm_credentials()
CTID = _creds['ctid_trader_account_id']
CLIENT_ID = _creds['client_id']
CLIENT_SECRET = _creds['api_secret']
ACCESS_TOKEN = _creds['access_token']
MODE = _creds['mode']

if MODE != 'demo':
    print(f"SAFETY: Refusing to run. ICM_MODE must be 'demo', got '{MODE}'")
    sys.exit(1)

# ── IC Markets cTrader symbol IDs ──
SYMBOL_IDS = {
    # Forex majors
    'EURUSD': 1, 'GBPUSD': 2, 'USDJPY': 4, 'AUDUSD': 5,
    'USDCAD': 8, 'USDCHF': 6, 'NZDUSD': 12,
    # Forex crosses
    'EURJPY': 3, 'GBPJPY': 7, 'EURGBP': 9, 'AUDJPY': 11, 'CADJPY': 15,
    # Crypto
    'BTCUSD': 10026, 'ETHUSD': 10029, 'LTCUSD': 10030,
    'XRPUSD': 10126, 'SOLUSD': 10132, 'ADAUSD': 10120,
    'DOGEUSD': 10122, 'DOTUSD': 10129, 'AVXUSD': 10121,
    'LNKUSD': 10130,
    # Commodities
    'XAUUSD': 41, 'XAGUSD': 42,
    'XTIUSD': 10019, 'XBRUSD': 10018,   # WTI & Brent crude oil
    'XNGUSD': 10020,                      # Natural gas
    'XPTUSD': 10017, 'XPDUSD': 10016,   # Platinum & Palladium
    # Indices
    'US500': 10013, 'US30': 10015, 'USTEC': 10014, 'US2000': 10012,
    'UK100': 10011, 'DE30': 10003, 'JP225': 10006,
    'AUS200': 10000, 'STOXX50': 10001, 'F40': 10002, 'HK50': 10004,
}

# Reverse lookup
ID_TO_SYMBOL = {v: k for k, v in SYMBOL_IDS.items()}

# ── Pair configuration ──
# Tight stops, trailing targets — lose small, win big (1:3 R:R + trailing stop)
# volume = cTrader units. Forex: 100000 = 0.01 lot. CFDs vary.
PAIRS = {
    # ── Forex Majors ──
    # Volumes target ~4% of balance ($18) risk per trade. _calc_safe_volume adjusts dynamically.
    # R:R 1:3 + trailing stop. trail_trigger = 1× risk, trail_step = 0.5× risk.
    # est_spread_pips = estimated spread deducted from TP to model real execution cost.
    'EURUSD':  {'name': 'EUR/USD',  'type': 'forex',  'volume': 1500000, 'risk_pips': 10, 'reward_pips': 30, 'trail_trigger_pips': 10, 'trail_step_pips': 5, 'est_spread_pips': 1},
    'GBPUSD':  {'name': 'GBP/USD',  'type': 'forex',  'volume': 1500000, 'risk_pips': 12, 'reward_pips': 36, 'trail_trigger_pips': 12, 'trail_step_pips': 4, 'est_spread_pips': 2},
    'USDJPY':  {'name': 'USD/JPY',  'type': 'forex',  'volume': 2300000, 'risk_pips': 12, 'reward_pips': 36, 'trail_trigger_pips': 12, 'trail_step_pips': 4, 'est_spread_pips': 2},
    'AUDUSD':  {'name': 'AUD/USD',  'type': 'forex',  'volume': 1500000, 'risk_pips': 10, 'reward_pips': 30, 'trail_trigger_pips': 10, 'trail_step_pips': 5, 'est_spread_pips': 2},
    'USDCAD':  {'name': 'USD/CAD',  'type': 'forex',  'volume': 1500000, 'risk_pips': 12, 'reward_pips': 36, 'trail_trigger_pips': 12, 'trail_step_pips': 4, 'est_spread_pips': 2},
    'USDCHF':  {'name': 'USD/CHF',  'type': 'forex',  'volume': 1500000, 'risk_pips': 12, 'reward_pips': 36, 'trail_trigger_pips': 12, 'trail_step_pips': 4, 'est_spread_pips': 2},
    'NZDUSD':  {'name': 'NZD/USD',  'type': 'forex',  'volume': 1500000, 'risk_pips': 10, 'reward_pips': 30, 'trail_trigger_pips': 10, 'trail_step_pips': 5, 'est_spread_pips': 2},
    # ── Forex Crosses ──
    'EURJPY':  {'name': 'EUR/JPY',  'type': 'forex',  'volume': 1100000, 'risk_pips': 20, 'reward_pips': 60, 'trail_trigger_pips': 20, 'trail_step_pips': 10, 'est_spread_pips': 3},
    'GBPJPY':  {'name': 'GBP/JPY',  'type': 'forex',  'volume': 900000,  'risk_pips': 25, 'reward_pips': 75, 'trail_trigger_pips': 25, 'trail_step_pips': 12, 'est_spread_pips': 4},
    'EURGBP':  {'name': 'EUR/GBP',  'type': 'forex',  'volume': 1200000, 'risk_pips': 10, 'reward_pips': 30, 'trail_trigger_pips': 10, 'trail_step_pips': 5, 'est_spread_pips': 2},
    # ── Crypto ──
    # cTrader CFD: volume / 100 = contract units (100 vol = 1.0 unit). Min 100 vol.
    # Volumes target ~4% risk ($18) per trade. pip_val = 0.01 for all crypto.
    'BTCUSD':  {'name': 'BTC/USD',  'type': 'crypto', 'volume': 400,     'risk_pips': 500, 'reward_pips': 1500, 'trail_trigger_pips': 500, 'trail_step_pips': 250, 'est_spread_pips': 50},
    'ETHUSD':  {'name': 'ETH/USD',  'type': 'crypto', 'volume': 6000,    'risk_pips': 30,  'reward_pips': 90,   'trail_trigger_pips': 30,  'trail_step_pips': 15, 'est_spread_pips': 5},
    'SOLUSD':  {'name': 'SOL/USD',  'type': 'crypto', 'volume': 900,     'risk_pips': 200, 'reward_pips': 600,  'trail_trigger_pips': 200, 'trail_step_pips': 100, 'est_spread_pips': 20},
    'XRPUSD':  {'name': 'XRP/USD',  'type': 'crypto', 'volume': 3600,    'risk_pips': 50,  'reward_pips': 150,  'trail_trigger_pips': 50,  'trail_step_pips': 25, 'est_spread_pips': 5},
    'LTCUSD':  {'name': 'LTC/USD',  'type': 'crypto', 'volume': 900,     'risk_pips': 200, 'reward_pips': 600,  'trail_trigger_pips': 200, 'trail_step_pips': 100, 'est_spread_pips': 20},
    'ADAUSD':  {'name': 'ADA/USD',  'type': 'crypto', 'volume': 3600,    'risk_pips': 50,  'reward_pips': 150,  'trail_trigger_pips': 50,  'trail_step_pips': 25, 'est_spread_pips': 5},
    'DOGEUSD': {'name': 'DOGE/USD', 'type': 'crypto', 'volume': 9000,    'risk_pips': 20,  'reward_pips': 60,   'trail_trigger_pips': 20,  'trail_step_pips': 10, 'est_spread_pips': 3},
    'LNKUSD':  {'name': 'LINK/USD', 'type': 'crypto', 'volume': 1800,    'risk_pips': 100, 'reward_pips': 300,  'trail_trigger_pips': 100, 'trail_step_pips': 50, 'est_spread_pips': 10},
    # ── Commodities ──
    # pip_val = 0.01 (metals, oil), 0.001 (nat gas)
    'XAUUSD':  {'name': 'Gold',     'type': 'commodity', 'volume': 900,  'risk_pips': 200, 'reward_pips': 600, 'trail_trigger_pips': 200, 'trail_step_pips': 100, 'est_spread_pips': 30},
    'XAGUSD':  {'name': 'Silver',   'type': 'commodity', 'volume': 6000, 'risk_pips': 30,  'reward_pips': 90,  'trail_trigger_pips': 30,  'trail_step_pips': 15, 'est_spread_pips': 3},
    # 'XTIUSD' disabled — 0W/3L, -$6.00 (worst dollar loser)
    'XBRUSD':  {'name': 'Brent Oil','type': 'commodity', 'volume': 6000, 'risk_pips': 30,  'reward_pips': 90,  'trail_trigger_pips': 30,  'trail_step_pips': 15, 'est_spread_pips': 5},
    'XNGUSD':  {'name': 'Nat Gas',  'type': 'commodity', 'volume': 90000,'risk_pips': 20,  'reward_pips': 60,  'trail_trigger_pips': 20,  'trail_step_pips': 10, 'est_spread_pips': 5},
    # ── Indices ──
    # pip_val = 1.0 (JP225, US30), 0.1 (all others). Min broker vol = 100.
    # US30/JP225 at 100 vol risk ~$80 (broker minimum, can't reduce).
    'US500':   {'name': 'S&P 500',  'type': 'index', 'volume': 400,     'risk_pips': 50,  'reward_pips': 150, 'trail_trigger_pips': 50,  'trail_step_pips': 25, 'est_spread_pips': 5},
    'US30':    {'name': 'Dow Jones', 'type': 'index', 'volume': 100,     'risk_pips': 80,  'reward_pips': 240, 'trail_trigger_pips': 80,  'trail_step_pips': 40, 'est_spread_pips': 10},
    'USTEC':   {'name': 'Nasdaq',    'type': 'index', 'volume': 300,     'risk_pips': 70,  'reward_pips': 210, 'trail_trigger_pips': 70,  'trail_step_pips': 35, 'est_spread_pips': 10},
    'UK100':   {'name': 'FTSE 100',  'type': 'index', 'volume': 500,     'risk_pips': 40,  'reward_pips': 120, 'trail_trigger_pips': 40,  'trail_step_pips': 20, 'est_spread_pips': 5},
    'DE30':    {'name': 'DAX',       'type': 'index', 'volume': 400,     'risk_pips': 50,  'reward_pips': 150, 'trail_trigger_pips': 50,  'trail_step_pips': 25, 'est_spread_pips': 5},
    'JP225':   {'name': 'Nikkei',    'type': 'index', 'volume': 100,     'risk_pips': 80,  'reward_pips': 240, 'trail_trigger_pips': 80,  'trail_step_pips': 40, 'est_spread_pips': 10},
    'AUS200':  {'name': 'ASX 200',   'type': 'index', 'volume': 600,     'risk_pips': 30,  'reward_pips': 90,  'trail_trigger_pips': 30,  'trail_step_pips': 15, 'est_spread_pips': 5},
}

CONFIG = {
    'max_positions': 5,       # max 5 simultaneous trades
    'max_bonus_positions': 0, # disabled — no bonus trades
    'check_interval': 30,     # 30s cycles — faster for 1M entries
    'cooldown_minutes': 15,   # 15 min cooldown — prevents rapid re-entry into losing pairs
}

# Multi-timeframe cache TTL (seconds) — reduces Yahoo Finance requests
MTF_CACHE_TTL = {'15m': 300, '5m': 120, '1m': 30}  # 15M=5min, 5M=2min, 1M=30s

# ── News intelligence integration ──
NEWS_INTEL_PATH = '/root/.openclaw/workspace/memory/tradebot-intel.md'

# Keywords that signal directional bias from news
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

# Market session hours (UTC)
HIGH_VOLATILITY = {
    'tokyo_open': 0, 'london_open': 8, 'london_close': 17,
    'ny_open': 13, 'ny_close': 21,
}

# ── Price fetching (Yahoo Finance for multi-timeframe analysis) ──

yahoo_symbols = {
    # Forex majors
    'EURUSD': 'EURUSD=X', 'GBPUSD': 'GBPUSD=X', 'USDJPY': 'USDJPY=X',
    'AUDUSD': 'AUDUSD=X', 'USDCAD': 'USDCAD=X', 'USDCHF': 'USDCHF=X',
    'NZDUSD': 'NZDUSD=X',
    # Forex crosses
    'EURJPY': 'EURJPY=X', 'GBPJPY': 'GBPJPY=X',
    'EURGBP': 'EURGBP=X', 'AUDJPY': 'AUDJPY=X', 'CADJPY': 'CADJPY=X',
    # Crypto
    'BTCUSD': 'BTC-USD', 'ETHUSD': 'ETH-USD', 'SOLUSD': 'SOL-USD',
    'XRPUSD': 'XRP-USD', 'LTCUSD': 'LTC-USD', 'ADAUSD': 'ADA-USD',
    'DOGEUSD': 'DOGE-USD', 'LNKUSD': 'LINK-USD',
    # Commodities
    'XAUUSD': 'GC=F', 'XAGUSD': 'SI=F',
    'XTIUSD': 'CL=F', 'XBRUSD': 'BZ=F', 'XNGUSD': 'NG=F',
    # Indices
    'US500': '^GSPC', 'US30': '^DJI', 'USTEC': '^IXIC',
    'UK100': '^FTSE', 'DE30': '^GDAXI', 'JP225': '^N225',
    'AUS200': '^AXJO',
}

# Module-level MTF cache: symbol -> {tf: {'data': ..., 'fetched_at': timestamp}}
_mtf_cache = {}

# ── Signal archival ──
SIGNAL_HISTORY_PATH = '/root/.openclaw/workspace/employees/signal_history.jsonl'

def archive_signal(symbol, signal, score, layers, price, session_name):
    """Append a non-HOLD signal to the signal history JSONL file."""
    try:
        entry = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'symbol': symbol,
            'signal': signal,
            'score': score,
            'layers': layers,
            'price': price,
            'session': session_name,
        }
        with open(SIGNAL_HISTORY_PATH, 'a') as f:
            f.write(json.dumps(entry) + '\n')
    except Exception as e:
        print(f"  [ARCHIVE] Failed to write signal: {e}")


# ── cTrader trendbar cache (populated by reactor thread, read by worker thread) ──
# Maps: (symbol, period_str) -> {'data': {...}, 'fetched_at': timestamp}
_ctrader_trendbar_cache = {}

# cTrader trendbar period map (interval string -> protobuf enum value)
_CTRADER_PERIOD_MAP = {
    '1m': 1,   # M1
    '5m': 5,   # M5
    '15m': 7,  # M15
}


from concurrent.futures import ThreadPoolExecutor, as_completed

# Shared requests session — reuses TCP+TLS connections across all Yahoo calls
_yahoo_session = requests.Session()
_yahoo_session.headers.update({'User-Agent': 'Mozilla/5.0'})


def _fetch_candles(yahoo, interval, range_str):
    """Fetch OHLCV candle data from Yahoo Finance for a given interval/range.
    Returns {'opens': [...], 'highs': [...], 'lows': [...], 'closes': [...], 'volumes': [...]} or None.
    """
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo}?interval={interval}&range={range_str}"
        r = _yahoo_session.get(url, timeout=10)
        data = r.json()
        if 'result' not in data['chart'] or not data['chart']['result']:
            return None
        candles = data['chart']['result'][0]['indicators']['quote'][0]
        opens = [o for o in candles.get('open', []) if o is not None]
        highs = [h for h in candles.get('high', []) if h is not None]
        lows = [l for l in candles.get('low', []) if l is not None]
        closes = [c for c in candles.get('close', []) if c is not None]
        if not closes:
            return None
        # Extract volume data (tick volume for forex — well-established proxy)
        raw_vols = candles.get('volume', [])
        volumes = [v if v is not None else 0 for v in raw_vols]
        # Pad volumes to match closes length if some are missing
        while len(volumes) < len(closes):
            volumes.append(0)
        volumes = volumes[:len(closes)]
        return {'opens': opens, 'highs': highs, 'lows': lows, 'closes': closes, 'volumes': volumes}
    except Exception:
        return None


def get_mtf_data(symbol, live_prices=None):
    """Fetch multi-timeframe candle data: 15M, 5M, 1M with caching.

    Uses cTrader live price if available, then cTrader trendbar cache for candles,
    falling back to Yahoo Finance only when needed.

    Returns: (current_price, tf_15m, tf_5m, tf_1m) where each tf is
    {'opens': [...], 'highs': [...], 'lows': [...], 'closes': [...]} or None.
    """
    yahoo = yahoo_symbols.get(symbol, symbol)

    # Get current price — prefer cTrader live price (no HTTP call needed)
    price = None
    if live_prices:
        price = live_prices.get(symbol)

    # Fallback: Yahoo Finance for current price
    if price is None:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo}"
            r = _yahoo_session.get(url, timeout=10)
            data = r.json()
            if 'result' not in data['chart'] or not data['chart']['result']:
                return None, None, None, None
            price = data['chart']['result'][0]['meta']['regularMarketPrice']
        except Exception:
            return None, None, None, None

    now = _time.time()
    if symbol not in _mtf_cache:
        _mtf_cache[symbol] = {}
    cache = _mtf_cache[symbol]

    # Timeframe configs: (interval, range, cache_key)
    tf_configs = [
        ('15m', '5d', '15m'),   # ~480 candles for EMA/structure
        ('5m', '2d', '5m'),     # ~480 candles for momentum
        ('1m', '1d', '1m'),     # ~390 candles for entry timing
    ]

    results = {}
    for interval, range_str, key in tf_configs:
        ttl = MTF_CACHE_TTL.get(key, 0)
        cached = cache.get(key)
        if cached and ttl > 0 and (now - cached['fetched_at']) < ttl:
            results[key] = cached['data']
            continue

        # Try cTrader trendbar cache first
        ct_key = (symbol, key)
        ct_cached = _ctrader_trendbar_cache.get(ct_key)
        if ct_cached and (now - ct_cached['fetched_at']) < max(ttl, 30):
            results[key] = ct_cached['data']
            cache[key] = {'data': ct_cached['data'], 'fetched_at': ct_cached['fetched_at']}
            continue

        # Fallback: Yahoo Finance
        tf_data = _fetch_candles(yahoo, interval, range_str)
        cache[key] = {'data': tf_data, 'fetched_at': now}
        results[key] = tf_data

    return price, results.get('15m'), results.get('5m'), results.get('1m')


# ══════════════════════════════════════════════════════════════════════
#  NEWS & SENTIMENT ANALYSIS
#  Philosophy: Lose small, win big. Trade WITH smart money and the news.
#  - Tight SL (10-12 pips) so losses are tiny
#  - TP at 3× risk (1:3 R:R) + trailing stop to lock in gains
#  - Break-even at 1× risk, broker auto-trail at 1.5× risk
#  - News bias tips the scale — hard block if news contradicts direction
#  - Liquidity sweep + volume profile + order flow confirm entry timing
# ══════════════════════════════════════════════════════════════════════


def get_news_bias():
    """Read the news intelligence brief and extract directional bias.

    Returns dict: {
        'usd_bias': 'bullish' | 'bearish' | 'neutral',
        'risk_sentiment': 'risk_on' | 'risk_off' | 'neutral',
        'confidence': 0.0-1.0,
        'headlines': int,
    }
    """
    try:
        with open(NEWS_INTEL_PATH, 'r') as f:
            content = f.read().lower()
    except Exception:
        return {'usd_bias': 'neutral', 'risk_sentiment': 'neutral', 'confidence': 0.0, 'headlines': 0}

    # Count headline matches
    bull_hits = sum(1 for kw in USD_BULLISH_KW if kw in content)
    bear_hits = sum(1 for kw in USD_BEARISH_KW if kw in content)
    risk_on_hits = sum(1 for kw in RISK_ON_KW if kw in content)
    risk_off_hits = sum(1 for kw in RISK_OFF_KW if kw in content)
    crypto_bull = sum(1 for kw in CRYPTO_BULLISH_KW if kw in content)
    crypto_bear = sum(1 for kw in CRYPTO_BEARISH_KW if kw in content)
    oil_bull = sum(1 for kw in OIL_BULLISH_KW if kw in content)
    oil_bear = sum(1 for kw in OIL_BEARISH_KW if kw in content)

    # USD bias
    if bull_hits > bear_hits and bull_hits >= 2:
        usd_bias = 'bullish'
    elif bear_hits > bull_hits and bear_hits >= 2:
        usd_bias = 'bearish'
    else:
        usd_bias = 'neutral'

    # Risk sentiment
    if risk_on_hits > risk_off_hits and risk_on_hits >= 2:
        risk_sentiment = 'risk_on'
    elif risk_off_hits > risk_on_hits and risk_off_hits >= 2:
        risk_sentiment = 'risk_off'
    else:
        risk_sentiment = 'neutral'

    # Crypto bias
    if crypto_bull > crypto_bear:
        crypto_bias = 'bullish'
    elif crypto_bear > crypto_bull:
        crypto_bias = 'bearish'
    else:
        crypto_bias = 'neutral'

    # Oil bias
    if oil_bull > oil_bear:
        oil_bias = 'bullish'
    elif oil_bear > oil_bull:
        oil_bias = 'bearish'
    else:
        oil_bias = 'neutral'

    total_hits = (bull_hits + bear_hits + risk_on_hits + risk_off_hits +
                  crypto_bull + crypto_bear + oil_bull + oil_bear)
    confidence = min(total_hits / 10.0, 1.0)

    return {
        'usd_bias': usd_bias,
        'risk_sentiment': risk_sentiment,
        'crypto_bias': crypto_bias,
        'oil_bias': oil_bias,
        'confidence': confidence,
        'headlines': total_hits,
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

    # ── Forex: USD bias ──
    # XXX/USD pairs — USD weakness = pair rises
    if symbol in ('EURUSD', 'GBPUSD', 'AUDUSD', 'NZDUSD'):
        if usd_bias == 'bearish' and direction == 'BUY':
            score += 1
        elif usd_bias == 'bullish' and direction == 'SELL':
            score += 1
        elif usd_bias == 'bearish' and direction == 'SELL':
            score -= 1
        elif usd_bias == 'bullish' and direction == 'BUY':
            score -= 1

    # USD/XXX pairs — USD strength = pair rises
    if symbol in ('USDJPY', 'USDCAD', 'USDCHF'):
        if usd_bias == 'bullish' and direction == 'BUY':
            score += 1
        elif usd_bias == 'bearish' and direction == 'SELL':
            score += 1
        elif usd_bias == 'bullish' and direction == 'SELL':
            score -= 1
        elif usd_bias == 'bearish' and direction == 'BUY':
            score -= 1

    # ── Forex: Risk sentiment ──
    if symbol in ('AUDUSD', 'GBPUSD', 'NZDUSD'):
        if risk == 'risk_on' and direction == 'BUY':
            score += 1
        elif risk == 'risk_off' and direction == 'SELL':
            score += 1
    if symbol in ('USDJPY', 'EURJPY', 'GBPJPY'):  # JPY safe-haven
        if risk == 'risk_off' and direction == 'SELL':
            score += 1
        elif risk == 'risk_on' and direction == 'BUY':
            score += 1

    # ── Crypto: risk-on asset + crypto-specific news ──
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

    # ── Commodities ──
    if symbol in ('XAUUSD', 'XAGUSD'):  # Precious metals = safe-haven
        if risk == 'risk_off' and direction == 'BUY':
            score += 1  # Gold/silver rally in risk-off
        elif risk == 'risk_on' and direction == 'SELL':
            score += 1
        if usd_bias == 'bearish' and direction == 'BUY':
            score += 1  # Metals priced in USD — weak USD = metals up
    if symbol in ('XTIUSD', 'XBRUSD', 'XNGUSD'):  # Energy
        if oil_bias == 'bullish' and direction == 'BUY':
            score += 1
        elif oil_bias == 'bearish' and direction == 'SELL':
            score += 1
        elif oil_bias == 'bullish' and direction == 'SELL':
            score -= 1
        elif oil_bias == 'bearish' and direction == 'BUY':
            score -= 1

    # ── Indices: risk-on assets ──
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


def calculate_ema(prices, period):
    if len(prices) < period:
        return None
    multiplier = 2 / (period + 1)
    ema = prices[0]
    for p in prices[1:]:
        ema = (p - ema) * multiplier + ema
    return ema


# ══════════════════════════════════════════════════════════════════════
#  INSTITUTIONAL STRATEGY — Pure Functions
#  Liquidity Sweep + Volume Profile + Anchored VWAP
# ══════════════════════════════════════════════════════════════════════

def find_swing_points(highs, lows, lookback=5):
    """Find swing highs and swing lows using a lookback window.
    A swing high is a candle whose high is the highest in [i-lookback, i+lookback].
    Returns: (swing_highs: [(index, price)], swing_lows: [(index, price)])
    """
    swing_highs = []
    swing_lows = []
    n = len(highs)
    if n < lookback * 2 + 1:
        return swing_highs, swing_lows
    for i in range(lookback, n - lookback):
        # Swing high: this candle's high is the max in the window
        window_highs = highs[i - lookback:i + lookback + 1]
        if highs[i] == max(window_highs) and window_highs.count(highs[i]) == 1:
            swing_highs.append((i, highs[i]))
        # Swing low: this candle's low is the min in the window
        window_lows = lows[i - lookback:i + lookback + 1]
        if lows[i] == min(window_lows) and window_lows.count(lows[i]) == 1:
            swing_lows.append((i, lows[i]))
    return swing_highs, swing_lows


def detect_liquidity_sweep(highs, lows, closes, opens, lookback=5, n_recent_candles=3):
    """Detect if recent candles swept past a swing high/low and reversed.

    Bullish sweep: wick below swing low, close above → stop hunt reversal up.
    Bearish sweep: wick above swing high, close below → stop hunt reversal down.

    Score 0-2: +1 for sweep occurred, +1 for strong reversal (body > 50% of range).
    Returns: {direction, sweep_level, sweep_depth, reversal_strength, score} or None.
    """
    n = len(closes)
    if n < lookback * 2 + 1 + n_recent_candles:
        return None

    # Find swing points excluding the most recent candles (they are the "sweep" candidates)
    swing_highs, swing_lows = find_swing_points(
        highs[:n - n_recent_candles], lows[:n - n_recent_candles], lookback)

    if not swing_highs and not swing_lows:
        return None

    best_result = None
    best_score = 0

    # Check recent candles for bullish sweep (sweep below swing low, close above)
    for idx, swing_low_price in swing_lows[-5:]:  # Check last 5 swing lows
        for i in range(n - n_recent_candles, n):
            if lows[i] < swing_low_price and closes[i] > swing_low_price:
                # Sweep detected — wick went below swing low but closed above
                sweep_depth = swing_low_price - lows[i]
                candle_range = highs[i] - lows[i]
                body = abs(closes[i] - opens[i])
                reversal_strength = body / candle_range if candle_range > 0 else 0
                score = 1  # +1 for sweep occurred
                if reversal_strength > 0.5:
                    score += 1  # +1 for strong reversal (body > 50% of range)
                if score > best_score:
                    best_score = score
                    best_result = {
                        'direction': 'BUY',
                        'sweep_level': swing_low_price,
                        'sweep_depth': sweep_depth,
                        'reversal_strength': round(reversal_strength, 3),
                        'score': score,
                    }

    # Check recent candles for bearish sweep (sweep above swing high, close below)
    for idx, swing_high_price in swing_highs[-5:]:  # Check last 5 swing highs
        for i in range(n - n_recent_candles, n):
            if highs[i] > swing_high_price and closes[i] < swing_high_price:
                sweep_depth = highs[i] - swing_high_price
                candle_range = highs[i] - lows[i]
                body = abs(closes[i] - opens[i])
                reversal_strength = body / candle_range if candle_range > 0 else 0
                score = 1
                if reversal_strength > 0.5:
                    score += 1
                if score > best_score:
                    best_score = score
                    best_result = {
                        'direction': 'SELL',
                        'sweep_level': swing_high_price,
                        'sweep_depth': sweep_depth,
                        'reversal_strength': round(reversal_strength, 3),
                        'score': score,
                    }

    return best_result


def build_volume_profile(highs, lows, closes, volumes, n_bins=50):
    """Build a volume profile from OHLCV data.

    Distributes volume across price bins (60% even, 40% weighted to close).
    Finds POC (highest volume bin), Value Area (70% volume range expanding from POC).
    Returns: {poc, va_high, va_low, hvn: [top 3 prices], lvn: [bottom 3 prices], profile}
    """
    if not highs or not lows or not closes or not volumes or len(closes) < 10:
        return None

    price_min = min(lows)
    price_max = max(highs)
    if price_max <= price_min:
        return None

    bin_size = (price_max - price_min) / n_bins
    if bin_size <= 0:
        return None

    # Initialize volume bins
    profile = [0.0] * n_bins

    # Distribute volume across bins
    for i in range(len(closes)):
        vol = volumes[i] if i < len(volumes) else 0
        if vol <= 0:
            continue
        h = highs[i] if i < len(highs) else closes[i]
        l = lows[i] if i < len(lows) else closes[i]
        c = closes[i]

        # 60% distributed evenly across the candle's range
        low_bin = max(0, int((l - price_min) / bin_size))
        high_bin = min(n_bins - 1, int((h - price_min) / bin_size))
        n_range_bins = high_bin - low_bin + 1
        even_vol = vol * 0.6 / n_range_bins if n_range_bins > 0 else 0
        for b in range(low_bin, high_bin + 1):
            profile[b] += even_vol

        # 40% weighted to the close price bin
        close_bin = min(n_bins - 1, max(0, int((c - price_min) / bin_size)))
        profile[close_bin] += vol * 0.4

    # Find POC (Point of Control = highest volume bin)
    poc_bin = max(range(n_bins), key=lambda b: profile[b])
    poc = price_min + (poc_bin + 0.5) * bin_size

    # Value Area: 70% of total volume, expanding outward from POC
    total_vol = sum(profile)
    if total_vol <= 0:
        return None

    va_target = total_vol * 0.70
    va_vol = profile[poc_bin]
    va_low_bin = poc_bin
    va_high_bin = poc_bin

    while va_vol < va_target and (va_low_bin > 0 or va_high_bin < n_bins - 1):
        expand_low = profile[va_low_bin - 1] if va_low_bin > 0 else 0
        expand_high = profile[va_high_bin + 1] if va_high_bin < n_bins - 1 else 0
        if expand_low >= expand_high and va_low_bin > 0:
            va_low_bin -= 1
            va_vol += expand_low
        elif va_high_bin < n_bins - 1:
            va_high_bin += 1
            va_vol += expand_high
        else:
            va_low_bin -= 1
            va_vol += expand_low

    va_low = price_min + va_low_bin * bin_size
    va_high = price_min + (va_high_bin + 1) * bin_size

    # HVN (High Volume Nodes) — top 3 bins by volume
    sorted_bins = sorted(range(n_bins), key=lambda b: profile[b], reverse=True)
    hvn = [price_min + (b + 0.5) * bin_size for b in sorted_bins[:3]]

    # LVN (Low Volume Nodes) — bottom 3 non-zero bins
    non_zero_bins = [b for b in sorted_bins if profile[b] > 0]
    lvn_bins = non_zero_bins[-3:] if len(non_zero_bins) >= 3 else non_zero_bins
    lvn = [price_min + (b + 0.5) * bin_size for b in lvn_bins]

    return {
        'poc': poc,
        'va_high': va_high,
        'va_low': va_low,
        'hvn': hvn,
        'lvn': lvn,
        'profile': profile,
        'bin_size': bin_size,
        'price_min': price_min,
    }


def calculate_vwap(highs, lows, closes, volumes, anchor_index=0):
    """Calculate VWAP from anchor_index to the end of the data.
    VWAP = cumulative(typical_price * volume) / cumulative(volume).
    Returns: float (current VWAP value) or None.
    """
    if not closes or not volumes or anchor_index >= len(closes):
        return None

    cum_tp_vol = 0.0
    cum_vol = 0.0
    for i in range(anchor_index, len(closes)):
        h = highs[i] if i < len(highs) else closes[i]
        l = lows[i] if i < len(lows) else closes[i]
        c = closes[i]
        v = volumes[i] if i < len(volumes) else 0
        tp = (h + l + c) / 3.0
        cum_tp_vol += tp * v
        cum_vol += v

    if cum_vol <= 0:
        return None
    return cum_tp_vol / cum_vol


def get_session_vwap_anchors(interval_minutes=1):
    """Calculate anchor indices for London open (08:00 UTC) and NY open (13:00 UTC).
    Based on current UTC time and candle interval.
    Returns: {session_name: candles_ago} or empty dict.
    """
    now = datetime.now(timezone.utc)
    current_minutes = now.hour * 60 + now.minute

    anchors = {}
    # London open = 08:00 UTC = 480 minutes
    london_minutes_ago = current_minutes - 480
    if london_minutes_ago > 0:
        anchors['london'] = london_minutes_ago // interval_minutes

    # NY open = 13:00 UTC = 780 minutes
    ny_minutes_ago = current_minutes - 780
    if ny_minutes_ago > 0:
        anchors['ny'] = ny_minutes_ago // interval_minutes

    return anchors


def is_market_open():
    current_hour = datetime.now(timezone.utc).hour
    for market, open_hour in HIGH_VOLATILITY.items():
        if abs(current_hour - open_hour) <= 1:
            return True, market
    if 8 <= current_hour <= 17:
        return True, "london_session"
    if 13 <= current_hour <= 21:
        return True, "ny_session"
    return False, "outside_sessions"


def get_advanced_signal(symbol, price, tf_15m, tf_5m, tf_1m, news_bias, depth_analysis=None):
    """Advanced signal engine: Liquidity Sweep + Volume Profile + VWAP + Order Flow.

    10-point scoring system:
      VP (0-2)  — Price at key volume level (POC, VA edge, LVN)
      LS (0-3)  — Sweep quality + reversal strength + MTF confluence
      VW (0-2)  — Price vs session VWAP + VWAP bounce detection
      OF (0-2)  — Delta trend + absorption + enhanced imbalance (capped)
      News (0-1) — News sentiment (hard block on contradiction)

    Entry: score >= 7 with LS >= 2, VP >= 1, OF >= 1
    Returns: (signal, reason, score, layer_scores)
    """
    if news_bias is None:
        news_bias = get_news_bias()
    layers = {'vp': 0, 'ls': 0, 'vw': 0, 'of': 0, 'news': 0}

    # ── Data validation ──
    if not tf_15m or len(tf_15m.get('closes', [])) < 50:
        return 'HOLD', 'Insufficient 15M data', 0, layers
    if not tf_5m or len(tf_5m.get('closes', [])) < 30:
        return 'HOLD', 'Insufficient 5M data', 0, layers

    # ── VP LAYER: Volume Profile (from 15M data) ──
    vp = build_volume_profile(
        tf_15m['highs'], tf_15m['lows'], tf_15m['closes'],
        tf_15m.get('volumes', []))

    vp_score = 0
    vp_near_level = None
    if vp:
        # Check price proximity to key VP levels
        poc_dist = abs(price - vp['poc']) / price if price > 0 else 1
        va_high_dist = abs(price - vp['va_high']) / price if price > 0 else 1
        va_low_dist = abs(price - vp['va_low']) / price if price > 0 else 1

        # Near POC (within 0.1%) = 2 points
        if poc_dist < 0.001:
            vp_score = 2
            vp_near_level = 'POC'
        # Near VA edge (within 0.15%) = 1 point
        elif va_high_dist < 0.0015 or va_low_dist < 0.0015:
            vp_score = 1
            vp_near_level = 'VA_edge'
        else:
            # Check LVN proximity (within 0.15%)
            for lvn_price in vp.get('lvn', []):
                if abs(price - lvn_price) / price < 0.0015:
                    vp_score = 1
                    vp_near_level = 'LVN'
                    break

    # ── LS LAYER: Liquidity Sweep (primary on 5M, confluence on 15M) ──
    sweep_5m = detect_liquidity_sweep(
        tf_5m['highs'], tf_5m['lows'], tf_5m['closes'], tf_5m['opens'])

    sweep_15m = detect_liquidity_sweep(
        tf_15m['highs'], tf_15m['lows'], tf_15m['closes'], tf_15m['opens'])

    ls_score_buy = 0
    ls_score_sell = 0
    sweep_direction = None

    if sweep_5m:
        if sweep_5m['direction'] == 'BUY':
            ls_score_buy += sweep_5m['score']  # 0-2 from 5M sweep
            # MTF confluence: 15M also shows bullish sweep
            if sweep_15m and sweep_15m['direction'] == 'BUY':
                ls_score_buy += 1
            # Bonus: sweep happened near a VP key level
            if vp and vp_near_level:
                ls_score_buy = min(ls_score_buy + 1, 3)
        elif sweep_5m['direction'] == 'SELL':
            ls_score_sell += sweep_5m['score']
            if sweep_15m and sweep_15m['direction'] == 'SELL':
                ls_score_sell += 1
            if vp and vp_near_level:
                ls_score_sell = min(ls_score_sell + 1, 3)

    ls_score_buy = min(ls_score_buy, 3)
    ls_score_sell = min(ls_score_sell, 3)

    # ── VW LAYER: Anchored VWAP (from 1M data) ──
    vw_score_buy = 0
    vw_score_sell = 0

    if tf_1m and len(tf_1m.get('closes', [])) >= 30:
        # Get session anchors
        anchors = get_session_vwap_anchors(interval_minutes=1)
        n_candles = len(tf_1m['closes'])

        # Use the most relevant session anchor (prefer NY if available, then London)
        best_anchor_idx = 0
        for session in ('ny', 'london'):
            if session in anchors:
                candles_ago = anchors[session]
                idx = max(0, n_candles - candles_ago)
                if idx < n_candles - 10:  # Need at least 10 candles after anchor
                    best_anchor_idx = idx
                    break

        vwap_val = calculate_vwap(
            tf_1m['highs'], tf_1m['lows'], tf_1m['closes'],
            tf_1m.get('volumes', []), anchor_index=best_anchor_idx)

        if vwap_val and vwap_val > 0:
            vwap_dist = (price - vwap_val) / vwap_val

            # Point 1: Price position vs VWAP
            if vwap_dist > 0.0003:  # Above VWAP = bullish bias
                vw_score_buy += 1
            elif vwap_dist < -0.0003:  # Below VWAP = bearish bias
                vw_score_sell += 1

            # Point 2: VWAP bounce detection (price touched VWAP recently and bounced)
            recent_closes = tf_1m['closes'][-5:]
            recent_lows = tf_1m['lows'][-5:] if len(tf_1m['lows']) >= 5 else tf_1m['lows']
            recent_highs = tf_1m['highs'][-5:] if len(tf_1m['highs']) >= 5 else tf_1m['highs']

            # Bullish bounce: recent low touched VWAP (within 0.03%) and price closed above
            for low in recent_lows:
                if abs(low - vwap_val) / vwap_val < 0.0003 and price > vwap_val:
                    vw_score_buy = min(vw_score_buy + 1, 2)
                    break
            # Bearish bounce: recent high touched VWAP and price closed below
            for high in recent_highs:
                if abs(high - vwap_val) / vwap_val < 0.0003 and price < vwap_val:
                    vw_score_sell = min(vw_score_sell + 1, 2)
                    break

    # ── OF LAYER: Order Flow (pre-computed) ──
    of_score_buy = 0
    of_score_sell = 0

    if depth_analysis and symbol in depth_analysis:
        of_buy = depth_analysis[symbol].get('buy', {})
        of_sell = depth_analysis[symbol].get('sell', {})
        of_score_buy = min(of_buy.get('score', 0), 2)   # Cap at 2
        of_score_sell = min(of_sell.get('score', 0), 2)

    # ── NEWS LAYER ──
    in_session, session_name = is_market_open()
    news_buy = news_supports_direction(symbol, 'BUY', news_bias)
    news_sell = news_supports_direction(symbol, 'SELL', news_bias)
    news_score_buy = 1 if news_buy > 0 else 0
    news_score_sell = 1 if news_sell > 0 else 0

    # ── Compile scores ──
    total_buy = vp_score + ls_score_buy + vw_score_buy + of_score_buy + news_score_buy
    total_sell = vp_score + ls_score_sell + vw_score_sell + of_score_sell + news_score_sell

    # ── Decision ──
    # Entry: score >= 7 with LS >= 2, VP >= 1, OF >= 1
    # News contradiction = hard block

    if total_buy >= 7 and total_buy >= total_sell:
        if ls_score_buy >= 2 and vp_score >= 1 and of_score_buy >= 1:
            if news_buy < 0:
                layers = {'vp': vp_score, 'ls': ls_score_buy, 'vw': vw_score_buy,
                          'of': of_score_buy, 'news': 0}
                return 'HOLD', f'News blocks BUY ({news_bias["usd_bias"]})', total_buy, layers
            layers = {'vp': vp_score, 'ls': ls_score_buy, 'vw': vw_score_buy,
                      'of': of_score_buy, 'news': news_score_buy}
            reason = f'ADV BUY (score {total_buy}/10) {session_name}'
            if vp_near_level:
                reason += f' VP:{vp_near_level}'
            if sweep_5m:
                reason += f' sweep@{sweep_5m["sweep_level"]:.5f}'
            if news_score_buy:
                reason += f' +news({news_bias["usd_bias"]})'
            return 'BUY', reason, total_buy, layers

    if total_sell >= 7 and total_sell > total_buy:
        if ls_score_sell >= 2 and vp_score >= 1 and of_score_sell >= 1:
            if news_sell < 0:
                layers = {'vp': vp_score, 'ls': ls_score_sell, 'vw': vw_score_sell,
                          'of': of_score_sell, 'news': 0}
                return 'HOLD', f'News blocks SELL ({news_bias["usd_bias"]})', total_sell, layers
            layers = {'vp': vp_score, 'ls': ls_score_sell, 'vw': vw_score_sell,
                      'of': of_score_sell, 'news': news_score_sell}
            reason = f'ADV SELL (score {total_sell}/10) {session_name}'
            if vp_near_level:
                reason += f' VP:{vp_near_level}'
            if sweep_5m:
                reason += f' sweep@{sweep_5m["sweep_level"]:.5f}'
            if news_score_sell:
                reason += f' +news({news_bias["usd_bias"]})'
            return 'SELL', reason, total_sell, layers

    # No entry — report the better side for logging
    if total_buy >= total_sell:
        layers = {'vp': vp_score, 'ls': ls_score_buy, 'vw': vw_score_buy,
                  'of': of_score_buy, 'news': news_score_buy}
    else:
        layers = {'vp': vp_score, 'ls': ls_score_sell, 'vw': vw_score_sell,
                  'of': of_score_sell, 'news': news_score_sell}
    best = max(total_buy, total_sell)
    return 'HOLD', f'No setup (best {best}/10)', best, layers


# ══════════════════════════════════════════════════════════════════════
#  cTrader Trading Engine — runs on Twisted reactor
# ══════════════════════════════════════════════════════════════════════

class TradeBotEngine:
    def __init__(self):
        self.client = Client(EndPoints.PROTOBUF_DEMO_HOST, EndPoints.PROTOBUF_PORT, TcpProtocol)
        self.authenticated = False
        self.balance = 0.0
        self._starting_balance = 0.0  # Set once on first broker auth — used for drawdown checks
        self.positions = {}        # positionId -> position data from broker
        self.local_positions = {}  # symbol -> local tracking (for dashboard)
        self.closed_trades = []
        self.last_trade_time = {}
        self.consecutive_losses = {}  # symbol -> count; reset on win, >=2 triggers 60min lockout
        self.pair_trade_results = {}  # symbol -> list of last N (bool: True=win) for rolling WR
        self.pair_disabled_until = {}  # symbol -> datetime; auto-disable if WR < 30% over 10 trades
        self._reconnect_count = 0
        self._consecutive_failures = 0
        self._last_disconnect_alert = 0  # timestamp of last Telegram alert
        self._last_connected_at = None
        self._last_authenticated_at = None  # tracks when we last had a working session
        self._trading_loop = None
        self._task_loop = None
        self._watchdog_loop = None
        self._skip_symbols = set()  # symbols that errored — skip for rest of session
        self._pending_order_configs = {}  # symbol -> {direction, entry_price, config} awaiting fill
        self.trailing_state = {}   # positionId -> {phase, entry_price, direction, symbol, current_sl, trail_activated, last_amend_time, scaled_out, original_volume}
        self._saved_trailing_state = self._load_trailing_state()  # Restored from disk
        self._last_prices = {}     # symbol -> latest price from cycle
        self._last_candles = {}    # symbol -> candle data (highs, lows, closes) for reversal detection
        self._live_prices = {}     # symbol -> real-time bid/ask from cTrader spot subscription
        self._spot_subscriptions = set()  # symbols currently subscribed to spot prices
        self._depth_history = {}       # symbol -> deque of depth snapshots (~10 min rolling)
        self._cumulative_delta = {}    # symbol -> deque of (timestamp, delta) for order flow

    # ── Connection lifecycle ──

    def start(self):
        print("=" * 60)
        print("TradeBot - IC Markets cTrader Demo")
        print("Strategy: Liquidity Sweep + Volume Profile + VWAP + Order Flow | R:R 1:3 + Trailing Stop")
        print("=" * 60)

        # ── Startup R:R validation — catch config errors before any trade fires ──
        print("[STARTUP] Validating R:R for all pairs...")
        for sym, cfg in PAIRS.items():
            rr_ok, eff_rr, rr_reason = validate_rr(
                cfg['risk_pips'], cfg['reward_pips'], cfg.get('est_spread_pips', 0))
            if not rr_ok:
                print(f"  [RR-WARN] {sym}: WOULD FAIL — {rr_reason}")
            else:
                print(f"  [RR-OK] {sym}: effective R:R = {eff_rr:.2f}:1")

        self.client.setConnectedCallback(self._on_connected)
        self.client.setDisconnectedCallback(self._on_disconnected)
        self.client.setMessageReceivedCallback(self._on_message)
        self.client.startService()

        # Start watchdog — runs every 30s regardless of connection state
        self._watchdog_loop = task.LoopingCall(self._watchdog)
        self._watchdog_loop.start(30, now=False)

        reactor.run()

    def _on_connected(self, client):
        was_recovering = self._consecutive_failures > 0
        self._reconnect_count = 0
        self._consecutive_failures = 0
        self._last_connected_at = datetime.now(timezone.utc)
        print(f"[{self._ts()}] Connected to cTrader API — authenticating...")
        if was_recovering:
            self._alert(f"TradeBot reconnected after recovery. Authenticating...")
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

        # Alert on disconnect — throttled: first disconnect, then every 5th failure
        import time as _time
        now_ts = _time.time()
        should_alert = (
            self._consecutive_failures == 1 or          # First disconnect
            self._consecutive_failures % 5 == 0 or      # Every 5th failure
            self._consecutive_failures >= 10             # Every attempt after 10
        )
        # Throttle to max 1 alert per 60 seconds
        if should_alert and (now_ts - self._last_disconnect_alert) > 60:
            self._last_disconnect_alert = now_ts
            open_pos = len(self.positions)
            self._alert(
                f"DISCONNECTED from cTrader (attempt {self._consecutive_failures})\n"
                f"Open positions: {open_pos} UNMONITORED\n"
                f"Balance: ${self.balance:.2f}\n"
                f"Reason: {str(reason)[:100]}"
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
        self._last_authenticated_at = datetime.now(timezone.utc)
        self._alert(f"Account authenticated (DEMO). Reconciling positions...")
        # Get account balance
        req = ProtoOATraderReq()
        req.ctidTraderAccountId = CTID
        d = self.client.send(req)
        d.addCallbacks(self._on_trader_info, self._on_error)

    def _on_trader_info(self, msg):
        payload = Protobuf.extract(msg)
        self.balance = payload.trader.balance / 100
        if self._starting_balance == 0.0:
            self._starting_balance = self.balance  # Lock starting balance for drawdown tracking
        print(f"[{self._ts()}] Account balance: ${self.balance:.2f} (starting: ${self._starting_balance:.2f})")
        # Reconcile existing positions from broker
        req = ProtoOAReconcileReq()
        req.ctidTraderAccountId = CTID
        d = self.client.send(req)
        d.addCallbacks(self._on_reconcile, self._on_error)

    def _on_reconcile(self, msg):
        payload = Protobuf.extract(msg)
        self.positions.clear()
        self.local_positions.clear()
        self.trailing_state.clear()
        for pos in payload.position:
            sym_id = pos.tradeData.symbolId
            symbol = ID_TO_SYMBOL.get(sym_id, f"ID_{sym_id}")
            side = 'BUY' if pos.tradeData.tradeSide == ProtoOATradeSide.Value('BUY') else 'SELL'
            volume = pos.tradeData.volume

            # cTrader Open API returns prices as floats (already correct)
            entry = pos.price
            sl = pos.stopLoss if pos.stopLoss else 0
            tp = pos.takeProfit if pos.takeProfit else 0

            self.positions[pos.positionId] = {
                'symbol': symbol, 'symbolId': sym_id, 'side': side,
                'volume': volume, 'positionId': pos.positionId,
                'entry_price': entry, 'stop_loss': sl, 'take_profit': tp,
                'lot_size': volume / 10000000,
                'open_time': datetime.now().isoformat(),
            }
            self.local_positions[symbol] = {
                'direction': side,
                'entry_price': entry,
                'lot_size': volume / 10000000,
                'stop_loss': sl,
                'take_profit': tp,
                'open_time': datetime.now().isoformat(),
                'positionId': pos.positionId,
                'bot': 'tradebot',
            }
            # Rebuild trailing state from broker position (or restore from saved state)
            saved = self._saved_trailing_state.get(str(pos.positionId))
            # Sanity check: if broker SL is wildly wrong (>10x risk from entry), it's corrupted
            config = PAIRS.get(symbol, {})
            pip_val = self._get_pip_value(symbol, config.get('type', 'forex'))
            max_sane_distance = config.get('risk_pips', 100) * pip_val * 10
            sl_distance = abs(sl - entry) if sl and entry else 0
            sl_is_corrupted = sl and entry and sl_distance > max_sane_distance
            if sl_is_corrupted:
                print(f"  [SL-SANITY] {symbol} posId={pos.positionId}: broker SL={sl:.5f} is {sl_distance/pip_val:.0f} pips from entry={entry:.5f} — CORRUPTED, will recalculate")
            if sl_is_corrupted:
                # SL is corrupted — recalculate from entry using correct pip_value
                risk_pips = config.get('risk_pips', 20)
                if side == 'BUY':
                    corrected_sl = round(entry - risk_pips * pip_val, 5)
                else:
                    corrected_sl = round(entry + risk_pips * pip_val, 5)
                print(f"  [SL-SANITY] Correcting SL: {sl:.5f} -> {corrected_sl:.5f} (entry={entry:.5f}, {risk_pips} pips risk)")
                sl = corrected_sl
                # Update local position with corrected SL
                self.local_positions[symbol] = {
                    'direction': side, 'entry_price': entry,
                    'lot_size': volume / 10000000, 'stop_loss': sl,
                    'take_profit': tp, 'open_time': datetime.now().isoformat(),
                    'positionId': pos.positionId, 'bot': 'tradebot',
                }
                # Amend SL on broker
                self._amend_sl(pos.positionId, symbol, corrected_sl)
                # Reset trailing state to initial
                self.trailing_state[pos.positionId] = {
                    'phase': 'initial', 'entry_price': entry, 'direction': side,
                    'symbol': symbol, 'current_sl': corrected_sl,
                    'trail_activated': False, 'last_amend_time': 0,
                    'scaled_out': False, 'original_volume': volume,
                }
                print(f"  [SL-SANITY] {symbol} posId={pos.positionId} trailing state reset to initial")
            elif saved:
                # Restore persisted trailing state from disk
                self.trailing_state[pos.positionId] = saved
                self.trailing_state[pos.positionId]['current_sl'] = sl  # sync with broker
                print(f"  Restored trail state for {symbol} posId={pos.positionId}: "
                      f"phase={saved['phase']}, scaled_out={saved.get('scaled_out', False)}")
            else:
                broker_trailing = getattr(pos, 'trailingStopLoss', False)
                tp_val = tp if tp else 0
                if broker_trailing:
                    phase = 'trailing'
                    trail_active = True
                elif sl and entry:
                    if side == 'BUY':
                        sl_vs_entry = (sl - entry) / pip_val
                    else:
                        sl_vs_entry = (entry - sl) / pip_val
                    if sl_vs_entry > 0.5:
                        phase = 'trailing'
                        trail_active = (tp_val == 0)
                    elif sl_vs_entry >= -0.5:
                        phase = 'breakeven'
                        trail_active = False
                    else:
                        phase = 'initial'
                        trail_active = False
                else:
                    phase = 'initial'
                    trail_active = False
                self.trailing_state[pos.positionId] = {
                    'phase': phase,
                    'entry_price': entry,
                    'direction': side,
                    'symbol': symbol,
                    'current_sl': sl,
                    'trail_activated': trail_active,
                    'last_amend_time': 0,
                    'scaled_out': False,
                    'original_volume': volume,
                }
            # Subscribe to live spot prices + depth data for open positions
            self._subscribe_spots(symbol)
            self._subscribe_depth(symbol)
        print(f"[{self._ts()}] Reconciled {len(self.positions)} open positions from broker")
        self._alert(
            f"ONLINE — {len(self.positions)} positions reconciled\n"
            f"Balance: ${self.balance:.2f}"
        )
        for pid, p in self.positions.items():
            sym = p['symbol']
            lots = p['volume'] / 10000000
            entry = self.local_positions.get(sym, {}).get('entry_price', 0)
            print(f"  {p['side']} {sym} vol={p['volume']} ({lots:g}lot) @ {entry:.5f} posId={pid}")

        self._save_state()

        # Subscribe to depth data for ALL pairs (order flow needs history from cycle 1)
        for sym in PAIRS:
            self._subscribe_depth(sym)

        # Fetch deal history for analytics (Phase 2C)
        self._fetch_deal_history(days=7)

        # Start the trading loop
        if self._trading_loop and self._trading_loop.running:
            self._trading_loop.stop()
        self._trading_loop = task.LoopingCall(self._trading_cycle)
        self._trading_loop.start(CONFIG['check_interval'], now=True)
        print(f"[{self._ts()}] Trading loop started (every {CONFIG['check_interval']}s)")

        # Start task polling loop (every 30s, separate from trading)
        if self._task_loop and self._task_loop.running:
            self._task_loop.stop()
        self._task_loop = task.LoopingCall(self._check_tasks)
        self._task_loop.start(30, now=False)
        print(f"[{self._ts()}] Task dispatch loop started (every 30s)")

    # ── cTrader Trendbar Fetching (Phase 2A) ──

    def _fetch_ctrader_trendbars(self):
        """Fetch 15M, 5M, 1M candle data from cTrader native API for all active pairs.
        Populates the module-level _ctrader_trendbar_cache so the worker thread can use it.
        """
        if not self.authenticated:
            return

        now_ms = int(_time.time() * 1000)
        period_configs = [
            ('15m', _CTRADER_PERIOD_MAP['15m'], 5 * 24 * 3600 * 1000),   # 5 days
            ('5m', _CTRADER_PERIOD_MAP['5m'], 2 * 24 * 3600 * 1000),     # 2 days
            ('1m', _CTRADER_PERIOD_MAP['1m'], 24 * 3600 * 1000),         # 1 day
        ]

        # Only fetch for pairs with active positions or top-priority pairs
        priority_symbols = list(self.local_positions.keys())
        # Add forex majors as always-fetch
        for sym in ('EURUSD', 'GBPUSD', 'USDJPY', 'XAUUSD', 'BTCUSD', 'US500'):
            if sym not in priority_symbols and sym in SYMBOL_IDS:
                priority_symbols.append(sym)

        for symbol in priority_symbols[:10]:  # Limit to 10 symbols to avoid API overload
            sym_id = SYMBOL_IDS.get(symbol)
            if not sym_id:
                continue
            for period_str, period_enum, lookback_ms in period_configs:
                try:
                    req = ProtoOAGetTrendbarsReq()
                    req.ctidTraderAccountId = CTID
                    req.symbolId = sym_id
                    req.period = period_enum
                    req.fromTimestamp = now_ms - lookback_ms
                    req.toTimestamp = now_ms
                    d = self.client.send(req, responseTimeoutInSeconds=10)
                    d.addCallback(self._on_trendbar_response, symbol, period_str)
                    d.addErrback(lambda f, s=symbol, p=period_str:
                                 print(f"  [TRENDBAR] Failed {s} {p}: {f.getErrorMessage()}"))
                except Exception as e:
                    print(f"  [TRENDBAR] Error requesting {symbol} {period_str}: {e}")

    def _on_trendbar_response(self, msg, symbol, period_str):
        """Process trendbar response and populate cache."""
        try:
            payload = Protobuf.extract(msg)
            bars = getattr(payload, 'trendbar', [])
            if not bars:
                return

            opens, highs, lows, closes = [], [], [], []
            for bar in bars:
                # cTrader trendbars: low is the base, others are deltas from low
                low = bar.low / 100000.0 if hasattr(bar, 'low') else 0
                delta_open = bar.deltaOpen / 100000.0 if hasattr(bar, 'deltaOpen') else 0
                delta_high = bar.deltaHigh / 100000.0 if hasattr(bar, 'deltaHigh') else 0
                delta_close = bar.deltaClose / 100000.0 if hasattr(bar, 'deltaClose') else 0
                opens.append(low + delta_open)
                highs.append(low + delta_high)
                lows.append(low)
                closes.append(low + delta_close)

            if closes:
                _ctrader_trendbar_cache[(symbol, period_str)] = {
                    'data': {'opens': opens, 'highs': highs, 'lows': lows, 'closes': closes},
                    'fetched_at': _time.time(),
                }
        except Exception as e:
            print(f"  [TRENDBAR] Parse error {symbol} {period_str}: {e}")

    # ── Depth Data (Phase 2B) ──

    _depth_data = {}  # symbol -> {'bids': [...], 'asks': [...], 'imbalance': float}
    _depth_subscriptions = set()

    def _subscribe_depth(self, symbol):
        """Subscribe to Level 2 depth quotes for a symbol."""
        if symbol in self._depth_subscriptions or not self.authenticated:
            return
        sym_id = SYMBOL_IDS.get(symbol)
        if not sym_id:
            return
        try:
            req = ProtoOASubscribeDepthQuotesReq()
            req.ctidTraderAccountId = CTID
            req.symbolId.append(sym_id)
            d = self.client.send(req, responseTimeoutInSeconds=10)
            d.addCallback(lambda _: self._depth_subscriptions.add(symbol))
            d.addErrback(lambda f: print(f"  [DEPTH] Subscribe failed {symbol}: {f.getErrorMessage()}"))
        except Exception as e:
            print(f"  [DEPTH] Error subscribing {symbol}: {e}")

    def _process_depth_update(self, payload, symbol):
        """Process depth quote update, calculate order book imbalance, and accumulate history."""
        from collections import deque
        try:
            bids = [(q.price, q.size) for q in getattr(payload, 'bid', [])]
            asks = [(q.price, q.size) for q in getattr(payload, 'ask', [])]
            total_bid = sum(size for _, size in bids) if bids else 0
            total_ask = sum(size for _, size in asks) if asks else 0
            total = total_bid + total_ask
            imbalance = (total_bid - total_ask) / total if total > 0 else 0.0
            now = _time.time()

            self._depth_data[symbol] = {
                'bids': bids[:5],
                'asks': asks[:5],
                'bid_volume': total_bid,
                'ask_volume': total_ask,
                'imbalance': round(imbalance, 3),
                'updated_at': now,
            }

            # Accumulate rolling depth history (~10 min at ~1 update/sec)
            if symbol not in self._depth_history:
                self._depth_history[symbol] = deque(maxlen=600)
            self._depth_history[symbol].append({
                'ts': now,
                'bid_vol': total_bid,
                'ask_vol': total_ask,
                'imbalance': imbalance,
                'best_bid': bids[0][0] if bids else 0,
                'best_ask': asks[0][0] if asks else 0,
            })

            # Track cumulative delta (bid_vol - ask_vol per tick)
            if symbol not in self._cumulative_delta:
                self._cumulative_delta[symbol] = deque(maxlen=600)
            delta = total_bid - total_ask
            self._cumulative_delta[symbol].append((now, delta))
        except Exception:
            pass

    def get_depth_score(self, symbol, direction):
        """Get Layer D score (0-1) based on order book imbalance.
        BUY: positive imbalance (more bids) = 1 point.
        SELL: negative imbalance (more asks) = 1 point.
        """
        depth = self._depth_data.get(symbol)
        if not depth or (_time.time() - depth.get('updated_at', 0)) > 60:
            return 0  # No data or stale
        imb = depth['imbalance']
        if direction == 'BUY' and imb > 0.2:
            return 1
        elif direction == 'SELL' and imb < -0.2:
            return 1
        return 0

    # ── Advanced Order Flow Analysis ──

    def analyze_order_flow(self, symbol, direction):
        """Analyze order flow from depth history for a given symbol and direction.

        Uses cumulative delta, delta divergence, absorption detection, and enhanced imbalance.
        Score 0-3: +1 delta trend matches, +1 absorption detected, +1 enhanced imbalance,
                   -1 if delta divergence detected.
        Returns: {cumulative_delta, delta_trend, delta_divergence, absorption_detected,
                  enhanced_imbalance, score}
        """
        now = _time.time()
        history = self._depth_history.get(symbol, [])
        deltas = self._cumulative_delta.get(symbol, [])

        result = {
            'cumulative_delta': 0.0,
            'delta_trend': 'neutral',
            'delta_divergence': False,
            'absorption_detected': False,
            'enhanced_imbalance': 0.0,
            'score': 0,
        }

        if len(history) < 30 or len(deltas) < 30:
            return result  # Not enough data

        # ── Cumulative delta (5-min window) ──
        five_min_ago = now - 300
        recent_deltas = [(ts, d) for ts, d in deltas if ts >= five_min_ago]
        if recent_deltas:
            cum_delta = sum(d for _, d in recent_deltas)
            # Normalize by count to get average delta direction
            avg_delta = cum_delta / len(recent_deltas)
            result['cumulative_delta'] = round(avg_delta, 2)
            if avg_delta > 0:
                result['delta_trend'] = 'bullish'
            elif avg_delta < 0:
                result['delta_trend'] = 'bearish'

        # ── Delta divergence (compare recent 2-min vs previous 2-min) ──
        two_min_ago = now - 120
        four_min_ago = now - 240
        recent_2m = [d for ts, d in deltas if ts >= two_min_ago]
        prev_2m = [d for ts, d in deltas if four_min_ago <= ts < two_min_ago]
        if recent_2m and prev_2m:
            recent_avg = sum(recent_2m) / len(recent_2m)
            prev_avg = sum(prev_2m) / len(prev_2m)
            # Divergence: delta was trending one way but recently reversed
            if direction == 'BUY' and prev_avg > 0 and recent_avg < prev_avg * 0.3:
                result['delta_divergence'] = True
            elif direction == 'SELL' and prev_avg < 0 and recent_avg > prev_avg * 0.3:
                result['delta_divergence'] = True

        # ── Absorption detection ──
        # High volume at a price level without price moving (smart money accumulation)
        recent_history = [h for h in history if h['ts'] >= five_min_ago]
        if len(recent_history) >= 10:
            total_volumes = [h['bid_vol'] + h['ask_vol'] for h in recent_history]
            avg_vol = sum(total_volumes) / len(total_volumes) if total_volumes else 0
            # Check for absorption: high volume (>1.5x avg) with tight price range
            high_vol_ticks = [h for h, v in zip(recent_history, total_volumes) if v > avg_vol * 1.5]
            if high_vol_ticks and len(high_vol_ticks) >= 3:
                best_bids = [h['best_bid'] for h in high_vol_ticks if h['best_bid'] > 0]
                if best_bids:
                    bid_range = max(best_bids) - min(best_bids)
                    avg_bid = sum(best_bids) / len(best_bids)
                    # If price range during high volume is tight (<0.02%), absorption detected
                    if avg_bid > 0 and bid_range / avg_bid < 0.0002:
                        result['absorption_detected'] = True

        # ── Enhanced imbalance (time-weighted decay over 5 minutes) ──
        if recent_history:
            weighted_imb = 0.0
            total_weight = 0.0
            for h in recent_history:
                age = now - h['ts']
                weight = max(0, 1.0 - age / 300.0)  # Linear decay over 5 min
                weighted_imb += h['imbalance'] * weight
                total_weight += weight
            if total_weight > 0:
                result['enhanced_imbalance'] = round(weighted_imb / total_weight, 3)

        # ── Score calculation ──
        score = 0
        # +1 if delta trend matches direction
        if direction == 'BUY' and result['delta_trend'] == 'bullish':
            score += 1
        elif direction == 'SELL' and result['delta_trend'] == 'bearish':
            score += 1
        # +1 if absorption detected
        if result['absorption_detected']:
            score += 1
        # +1 if enhanced imbalance supports direction
        if direction == 'BUY' and result['enhanced_imbalance'] > 0.15:
            score += 1
        elif direction == 'SELL' and result['enhanced_imbalance'] < -0.15:
            score += 1
        # -1 if delta divergence detected (weakening momentum)
        if result['delta_divergence']:
            score -= 1

        result['score'] = max(0, score)
        return result

    def _compute_all_depth_analyses(self):
        """Pre-compute order flow analysis for all pairs (runs on reactor thread).
        Returns: {symbol: {'buy': {...}, 'sell': {...}}}
        """
        analyses = {}
        for symbol in PAIRS:
            if symbol in self._depth_history and len(self._depth_history[symbol]) >= 30:
                analyses[symbol] = {
                    'buy': self.analyze_order_flow(symbol, 'BUY'),
                    'sell': self.analyze_order_flow(symbol, 'SELL'),
                }
        return analyses

    # ── Deal History (Phase 2C) ──

    def _fetch_deal_history(self, days=7):
        """Fetch historical deals from broker for better P&L analytics."""
        if not self.authenticated:
            return
        now_ms = int(_time.time() * 1000)
        from_ms = now_ms - (days * 24 * 3600 * 1000)
        try:
            req = ProtoOADealListReq()
            req.ctidTraderAccountId = CTID
            req.fromTimestamp = from_ms
            req.toTimestamp = now_ms
            req.maxRows = 1000
            d = self.client.send(req, responseTimeoutInSeconds=15)
            d.addCallback(self._on_deal_history)
            d.addErrback(lambda f: print(f"  [DEALS] Failed: {f.getErrorMessage()}"))
        except Exception as e:
            print(f"  [DEALS] Error: {e}")

    def _on_deal_history(self, msg):
        """Process deal history and write to trade_history.jsonl."""
        try:
            payload = Protobuf.extract(msg)
            deals = getattr(payload, 'deal', [])
            if not deals:
                return

            history_path = '/root/.openclaw/workspace/employees/trade_history.jsonl'
            # Read existing deal IDs to avoid duplicates
            existing_ids = set()
            try:
                with open(history_path) as f:
                    for line in f:
                        entry = json.loads(line.strip())
                        existing_ids.add(entry.get('deal_id'))
            except FileNotFoundError:
                pass

            new_deals = 0
            with open(history_path, 'a') as f:
                for deal in deals:
                    deal_id = deal.dealId
                    if deal_id in existing_ids:
                        continue
                    symbol = ID_TO_SYMBOL.get(deal.symbolId, f'ID_{deal.symbolId}')
                    entry = {
                        'deal_id': deal_id,
                        'symbol': symbol,
                        'side': 'BUY' if deal.tradeSide == 1 else 'SELL',
                        'volume': deal.volume,
                        'entry_price': deal.executionPrice,
                        'close_pnl': deal.closePositionDetail.grossProfit / 100 if deal.HasField('closePositionDetail') else None,
                        'commission': deal.commission / 100 if deal.commission else 0,
                        'timestamp': deal.executionTimestamp,
                        'deal_status': deal.dealStatus,
                    }
                    f.write(json.dumps(entry) + '\n')
                    new_deals += 1

            if new_deals:
                print(f"  [DEALS] Archived {new_deals} new deals from broker")
        except Exception as e:
            print(f"  [DEALS] Parse error: {e}")

    # ── Message handler for execution reports ──

    def _on_message(self, client, msg):
        # Execution events (fills, closes, rejects)
        if msg.payloadType == 2126:  # ProtoOAExecutionEvent
            try:
                payload = Protobuf.extract(msg)
                etype = payload.executionType
                # executionType: 2=ORDER_FILLED, 3=ORDER_CANCELLED, 4=ORDER_REJECTED, 6=SWAP etc.
                if hasattr(payload, 'position') and payload.HasField('position'):
                    pos = payload.position
                    sym = ID_TO_SYMBOL.get(pos.tradeData.symbolId, '?')
                    side = 'BUY' if pos.tradeData.tradeSide == 1 else 'SELL'
                    vol = pos.tradeData.volume
                    pid = pos.positionId

                    if etype == 2 and vol > 0:  # ORDER_FILLED with volume > 0
                        lots = vol / 10000000

                        # ── Detect PARTIAL CLOSE (scale-out) vs NEW OPEN ──
                        # If position already exists and volume decreased, this is a partial close fill
                        existing = self.positions.get(pid)
                        if existing and vol < existing.get('volume', 0):
                            old_vol = existing['volume']
                            closed_vol = old_vol - vol
                            closed_lots = closed_vol / 10000000
                            print(f"  [SCALE-OUT FILL] {sym} posId={pid} partial close confirmed: "
                                  f"{closed_lots:g}lot closed, {lots:g}lot remaining")
                            # Update volume in all state dicts
                            existing['volume'] = vol
                            existing['lot_size'] = lots
                            if sym in self.local_positions:
                                self.local_positions[sym]['lot_size'] = lots
                            # Mark scale-out as confirmed on FILL (not on ACK)
                            state = self.trailing_state.get(pid)
                            if state:
                                state['scaled_out'] = True
                                state.pop('_scale_out_pending', None)
                            self._save_state()

                            # Calculate profit for alert
                            profit_display = ''
                            price = self._live_prices.get(sym) or self._last_prices.get(sym)
                            if price and state:
                                entry = state['entry_price']
                                config = PAIRS.get(sym, {})
                                asset_type = config.get('type', 'forex')
                                pv = self._get_pip_value(sym, asset_type)
                                pp = (price - entry) / pv if state['direction'] == 'BUY' else (entry - price) / pv
                                profit_display = f" at +{pp:.0f} pips"

                            self._alert(
                                f"SCALE-OUT: {sym}\n"
                                f"Closed {closed_lots:g}lot{profit_display}\n"
                                f"Remaining {lots:g}lot trailing"
                            )
                        else:
                            # ── NEW POSITION OPEN ──
                            print(f"  [FILL] {side} {sym} vol={vol} ({lots:g}lot) @ {pos.price:.5f} posId={pid}")
                            # Get SL/TP from broker fill, fall back to pending config
                            sl_price = pos.stopLoss if pos.stopLoss else 0
                            tp_price = pos.takeProfit if pos.takeProfit else 0
                            pending = self._pending_order_configs.pop(sym, None)

                            # LAYER 1 SL-GUARD: If broker didn't return SL/TP, compute from pending config
                            if pending and (not sl_price or not tp_price):
                                cfg = pending['config']
                                ep = pos.price
                                asset_type = cfg.get('type', 'forex')
                                pip_val = self._get_pip_value(sym, asset_type)
                                # Use spread-adjusted reward for TP computation
                                eff_reward = cfg['reward_pips'] - cfg.get('est_spread_pips', 0)
                                if not sl_price:
                                    if side == 'BUY':
                                        sl_price = round(ep - cfg['risk_pips'] * pip_val, 5)
                                    else:
                                        sl_price = round(ep + cfg['risk_pips'] * pip_val, 5)
                                if not tp_price:
                                    if side == 'BUY':
                                        tp_price = round(ep + eff_reward * pip_val, 5)
                                    else:
                                        tp_price = round(ep - eff_reward * pip_val, 5)
                                # Validate R:R of computed SL/TP
                                rr_ok, eff_rr, _ = validate_rr(cfg['risk_pips'], cfg['reward_pips'], cfg.get('est_spread_pips', 0))
                                rr_tag = f" R:R={eff_rr:.1f}:1" if rr_ok else f" R:R={eff_rr:.1f}:1 WARNING"
                                print(f"  [SL-GUARD] Broker returned SL=0 — computed SL={sl_price:.5f} TP={tp_price:.5f}{rr_tag}")

                            self.positions[pid] = {
                                'symbol': sym, 'symbolId': pos.tradeData.symbolId,
                                'side': side, 'volume': vol, 'positionId': pid,
                                'entry_price': pos.price, 'stop_loss': sl_price,
                                'take_profit': tp_price, 'lot_size': lots,
                                'open_time': datetime.now().isoformat(),
                            }
                            self.local_positions[sym] = {
                                'direction': side,
                                'entry_price': pos.price,
                                'lot_size': lots,
                                'stop_loss': sl_price,
                                'take_profit': tp_price,
                                'open_time': datetime.now().isoformat(),
                                'positionId': pid,
                                'bot': 'tradebot',
                            }
                            self._save_state()

                            # SAFETY NET: If SL is missing on broker, force-amend it
                            if not pos.stopLoss and sl_price:
                                print(f"  [SL-GUARD] Amending SL onto {sym} posId={pid}")
                                self._amend_sl(pid, sym, sl_price)

                            # Report to Telegram
                            if pending:
                                reason = pending['config'].get('_reason', '')
                                try:
                                    report_trade_opened(sym, side, pos.price, lots, sl_price, tp_price, reason)
                                except Exception as e:
                                    print(f"  Warning: Telegram report failed: {e}")
                            # Initialize trailing stop state for this position
                            self.trailing_state[pid] = {
                                'phase': 'initial',
                                'entry_price': pos.price,
                                'direction': side,
                                'symbol': sym,
                                'current_sl': sl_price,
                                'trail_activated': False,
                                'last_amend_time': 0,
                                'scaled_out': False,
                                'original_volume': vol,
                            }
                            # Set cooldown on confirmed FILL (not order ACK)
                            self.last_trade_time[sym] = datetime.now()
                            # Subscribe to live spot prices for this symbol
                            self._subscribe_spots(sym)
                    elif etype == 2 and vol == 0:  # FILLED with 0 volume = position closed
                        if pid in self.positions:
                            closed_sym = self.positions[pid]['symbol']
                            broker_pnl = self._extract_broker_pnl(payload)
                            print(f"  [CLOSED] {closed_sym} posId={pid} P&L=${broker_pnl:.2f}" if broker_pnl is not None else f"  [CLOSED] {closed_sym} posId={pid}")
                            closed_pos = self.local_positions.get(closed_sym, {})
                            # Record the closed trade for stats tracking
                            self._record_closed_trade(closed_sym, closed_pos, pos.price, broker_pnl)
                            del self.positions[pid]
                            if closed_sym in self.local_positions:
                                del self.local_positions[closed_sym]
                            self.trailing_state.pop(pid, None)
                            self._unsubscribe_spots(closed_sym)
                            self._save_state()
                            self._report_close(closed_sym, closed_pos, pos.price, broker_pnl)
                    elif etype in (3, 5):  # CANCELLED / explicit close
                        if pid in self.positions:
                            closed_sym = self.positions[pid]['symbol']
                            broker_pnl = self._extract_broker_pnl(payload)
                            print(f"  [CLOSED] {closed_sym} posId={pid} P&L=${broker_pnl:.2f}" if broker_pnl is not None else f"  [CLOSED] {closed_sym} posId={pid}")
                            closed_pos = self.local_positions.get(closed_sym, {})
                            # Record the closed trade for stats tracking
                            self._record_closed_trade(closed_sym, closed_pos, pos.price, broker_pnl)
                            del self.positions[pid]
                            if closed_sym in self.local_positions:
                                del self.local_positions[closed_sym]
                            self.trailing_state.pop(pid, None)
                            self._unsubscribe_spots(closed_sym)
                            self._save_state()
                            self._report_close(closed_sym, closed_pos, pos.price, broker_pnl)

                if etype == 4:  # ORDER_REJECTED
                    err = getattr(payload, 'errorCode', 'unknown')
                    desc = getattr(payload, 'description', '')
                    print(f"  [REJECTED] {err}: {desc}")
            except Exception as e:
                print(f"  Warning: execution event parse error: {e}")

        # Trader update (balance change)
        elif msg.payloadType == 2113:  # ProtoOATraderUpdatedEvent
            try:
                payload = Protobuf.extract(msg)
                self.balance = payload.trader.balance / 100
            except Exception:
                pass

        # Trailing SL changed by broker (cTrader auto-trail)
        elif msg.payloadType == 2107:  # ProtoOATrailingSLChangedEvent
            try:
                payload = Protobuf.extract(msg)
                pid = payload.positionId
                new_sl = payload.stopPrice
                if pid in self.trailing_state:
                    sym = self.trailing_state[pid]['symbol']
                    self.trailing_state[pid]['current_sl'] = new_sl
                    if pid in self.positions:
                        self.positions[pid]['stop_loss'] = new_sl
                    if sym in self.local_positions:
                        self.local_positions[sym]['stop_loss'] = new_sl
                    print(f"  [TRAIL-UPDATE] {sym} SL trailed to {new_sl:.5f} by broker")
                    self._save_state()
            except Exception as e:
                print(f"  Warning: trailing SL event parse error: {e}")

        # Live spot price update from cTrader
        elif msg.payloadType == 2131:  # ProtoOASpotEvent
            try:
                payload = Protobuf.extract(msg)
                sym_id = payload.symbolId
                symbol = ID_TO_SYMBOL.get(sym_id)
                if symbol and hasattr(payload, 'bid') and payload.bid:
                    # cTrader sends prices as integers — divisor depends on symbol digits
                    config = PAIRS.get(symbol, {})
                    asset_type = config.get('type', 'forex')
                    if 'JPY' in symbol and asset_type == 'forex':
                        divisor = 1000.0       # 3 decimal places (e.g., 151.234)
                    elif asset_type == 'forex':
                        divisor = 100000.0     # 5 decimal places (e.g., 1.12345)
                    elif asset_type == 'crypto':
                        divisor = 100.0        # 2 decimal places
                    elif symbol in ('XAUUSD', 'XAGUSD'):
                        divisor = 100.0        # 2 decimal places
                    elif symbol == 'XNGUSD':
                        divisor = 100000.0     # 5 digits precision (raw 300200 = 3.00200)
                    elif symbol == 'JP225':
                        divisor = 1.0          # whole numbers (e.g., 39000)
                    elif asset_type in ('commodity', 'index'):
                        divisor = 100.0        # 2 decimal places
                    else:
                        divisor = 100000.0
                    self._live_prices[symbol] = payload.bid / divisor
            except Exception:
                pass

        # Depth quote update from cTrader (Level 2 data)
        elif msg.payloadType == 2155:  # ProtoOADepthEvent
            try:
                payload = Protobuf.extract(msg)
                sym_id = payload.symbolId
                symbol = ID_TO_SYMBOL.get(sym_id)
                if symbol:
                    self._process_depth_update(payload, symbol)
            except Exception:
                pass

        # Order error event
        elif msg.payloadType == 2132:  # ProtoOAOrderErrorEvent
            try:
                payload = Protobuf.extract(msg)
                err = str(payload.errorCode)
                desc = str(payload.description)
                print(f"  [ORDER ERROR] {err}: {desc}")
            except Exception:
                pass

    # ── Trade close reporting ──

    @staticmethod
    def _extract_broker_pnl(payload):
        """Extract the broker-calculated P&L from a close execution event.

        The deal.closePositionDetail.grossProfit is the authoritative P&L
        from cTrader — no manual pip/lot math needed.
        """
        try:
            if hasattr(payload, 'deal') and payload.HasField('deal'):
                deal = payload.deal
                if hasattr(deal, 'closePositionDetail') and deal.HasField('closePositionDetail'):
                    detail = deal.closePositionDetail
                    gross = detail.grossProfit
                    swap = detail.swap if detail.swap else 0
                    commission = detail.commission if detail.commission else 0
                    # moneyDigits: number of decimal places (usually 2 = cents)
                    digits = detail.moneyDigits if detail.moneyDigits else 2
                    divisor = 10 ** digits
                    net_pnl = (gross + swap + commission) / divisor
                    return net_pnl
        except Exception:
            pass
        return None

    def _record_closed_trade(self, symbol, closed_pos, close_price, broker_pnl=None):
        """Record a closed trade for stats tracking. Must be called BEFORE deleting from positions."""
        trade_record = {
            'symbol': symbol,
            'direction': closed_pos.get('direction', '?'),
            'entry_price': closed_pos.get('entry_price', 0),
            'close_price': close_price,
            'lot_size': closed_pos.get('lot_size', 0),
            'pnl': broker_pnl if broker_pnl is not None else 0.0,
            'open_time': closed_pos.get('open_time', ''),
            'close_time': datetime.now().isoformat(),
            'positionId': closed_pos.get('positionId', 0),
            'asset_type': PAIRS.get(symbol, {}).get('type', 'forex'),
        }
        self.closed_trades.append(trade_record)
        # Persist every trade to JSONL for full history (not just last 50)
        try:
            with open('/root/.openclaw/workspace/employees/trade_history.jsonl', 'a') as _fh:
                _fh.write(json.dumps(trade_record) + '\n')
        except Exception as _e:
            print(f"  Warning: failed to append trade history: {_e}")
        pnl_val = broker_pnl if broker_pnl is not None else 0.0
        result = 'WIN' if pnl_val > 0 else 'LOSS'
        # Track consecutive losses per symbol for lockout logic
        if pnl_val > 0:
            self.consecutive_losses[symbol] = 0
        else:
            self.consecutive_losses[symbol] = self.consecutive_losses.get(symbol, 0) + 1
        # Track rolling win rate per pair (last 10 trades)
        if symbol not in self.pair_trade_results:
            self.pair_trade_results[symbol] = []
        self.pair_trade_results[symbol].append(pnl_val > 0)
        self.pair_trade_results[symbol] = self.pair_trade_results[symbol][-10:]  # keep last 10
        # Auto-disable pair for 24h if WR < 30% over 10+ trades
        results = self.pair_trade_results[symbol]
        if len(results) >= 10:
            wr = sum(results) / len(results)
            if wr < 0.30:
                self.pair_disabled_until[symbol] = datetime.now() + timedelta(hours=24)
                print(f"  [AUTO-DISABLE] {symbol} — win rate {wr*100:.0f}% over last {len(results)} trades, disabled for 24h")

        print(f"  [RECORD] {result} {symbol} {closed_pos.get('direction','?')} "
              f"P&L=${pnl_val:.2f} "
              f"(total: {len(self.closed_trades)} trades, consec_losses={self.consecutive_losses.get(symbol, 0)})")

    def _report_close(self, symbol, closed_pos, close_price, broker_pnl=None):
        """Report a closed position to Zeff.bot → Telegram."""
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

    # ── Trading cycle ──

    @staticmethod
    def _fetch_all_signals(pairs_dict, live_prices=None, depth_analyses=None):
        """Blocking worker: fetch MTF data + compute signals for all pairs.

        Runs in a thread via deferToThread so the Twisted reactor stays free
        for spot price updates, execution reports, and trailing stop management.

        Uses ThreadPoolExecutor to fetch all pairs in parallel (~6s total
        instead of ~10min sequential).

        Returns: (prices, candles, signals, news_bias, log_lines)
        """
        news_bias = get_news_bias()
        in_session, session_name = is_market_open()

        prices = {}
        candles = {}
        signals = {}
        log_lines = []

        log_lines.append(
            f"  Strategy: LS+VP+VWAP+OF | News: USD={news_bias['usd_bias']} Risk={news_bias['risk_sentiment']} "
            f"Crypto={news_bias.get('crypto_bias','?')} Oil={news_bias.get('oil_bias','?')} "
            f"Conf={news_bias['confidence']:.1f} | Session={session_name}"
        )

        # Fetch all pairs in parallel (8 workers keeps Yahoo happy, 29 pairs finish in ~20s worst case)
        def _fetch_one(symbol):
            return symbol, get_mtf_data(symbol, live_prices=live_prices)

        pair_data = {}
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(_fetch_one, sym): sym for sym in pairs_dict}
            for future in as_completed(futures):
                try:
                    symbol, result = future.result(timeout=30)
                    pair_data[symbol] = result
                except Exception:
                    pass  # skip pairs that error

        # Process results in original order for consistent log output
        for symbol, config in pairs_dict.items():
            if symbol not in pair_data:
                continue
            price, tf_15m, tf_5m, tf_1m = pair_data[symbol]
            if price and (tf_15m or tf_5m or tf_1m):
                if not validate_price(price, symbol):
                    continue
                prices[symbol] = price
                if tf_5m:
                    candles[symbol] = tf_5m

                signal, reason, score, layers = get_advanced_signal(
                    symbol, price, tf_15m, tf_5m, tf_1m, news_bias, depth_analyses)
                signals[symbol] = (signal, reason, score, layers)
                log_lines.append(
                    f"  {config['name']}: {price:.5f} | {signal} "
                    f"(VP:{layers['vp']} LS:{layers['ls']} VW:{layers['vw']} "
                    f"OF:{layers['of']} N:{layers['news']}) {reason}"
                )

                # Archive non-HOLD signals for history API + paid channel
                if signal != 'HOLD':
                    archive_signal(symbol, signal, score, layers, price, session_name)
                    # Broadcast to premium Telegram channel
                    _pair_cfg = PAIRS.get(symbol, {})
                    _pip_val = TradeBotEngine._get_pip_value(symbol, _pair_cfg.get('type', 'forex'))
                    _risk = _pair_cfg.get('risk_pips', 10) * _pip_val
                    _reward = _pair_cfg.get('reward_pips', 30) * _pip_val
                    _spread = _pair_cfg.get('est_spread_pips', 0)
                    if signal == 'BUY':
                        _sl = round(price - _risk, 5)
                        _tp = round(price + _reward, 5)
                    else:
                        _sl = round(price + _risk, 5)
                        _tp = round(price - _reward, 5)
                    _eff_reward = _pair_cfg.get('reward_pips', 30) - _spread
                    _rr = _eff_reward / _pair_cfg.get('risk_pips', 10) if _pair_cfg.get('risk_pips') else 3.0
                    try:
                        send_premium_signal(
                            symbol=symbol, direction=signal, price=price,
                            stop_loss=_sl, take_profit=_tp,
                            score=score, layers=layers, risk_reward=_rr,
                            session=session_name, est_spread_pips=_spread,
                        )
                    except Exception:
                        pass  # non-critical — don't block signal processing

        return prices, candles, signals, news_bias, log_lines

    # ── Periodic reconciliation — broker is the single source of truth ──

    def _cycle_reconcile(self):
        """Reconcile with broker at the start of every cycle. Prunes ghost positions."""
        if not self.authenticated:
            return defer.succeed(None)
        req = ProtoOAReconcileReq()
        req.ctidTraderAccountId = CTID
        d = self.client.send(req, responseTimeoutInSeconds=15)
        d.addCallback(self._process_cycle_reconcile)
        d.addErrback(lambda f: print(f"  [RECONCILE] Failed: {f.getErrorMessage()} — using cached state"))
        return d

    def _process_cycle_reconcile(self, msg):
        """Compare broker positions with local state. Broker wins all conflicts."""
        payload = Protobuf.extract(msg)
        if hasattr(payload, 'errorCode'):
            print(f"  [RECONCILE] Error: {getattr(payload, 'errorCode', '?')} — using cached state")
            return

        broker_pids = set()
        broker_positions = {}
        for pos in getattr(payload, 'position', []):
            pid = pos.positionId
            broker_pids.add(pid)
            sym_id = pos.tradeData.symbolId
            symbol = ID_TO_SYMBOL.get(sym_id, f"ID_{sym_id}")
            side = 'BUY' if pos.tradeData.tradeSide == ProtoOATradeSide.Value('BUY') else 'SELL'
            broker_positions[pid] = {
                'symbol': symbol, 'symbolId': sym_id, 'side': side,
                'volume': pos.tradeData.volume, 'positionId': pid,
                'entry': pos.price,
                'sl': pos.stopLoss if pos.stopLoss else 0,
                'tp': pos.takeProfit if pos.takeProfit else 0,
            }

        # PRUNE: remove local positions the broker no longer has
        local_pids = set(self.positions.keys())
        ghost_pids = local_pids - broker_pids
        if ghost_pids:
            for pid in ghost_pids:
                ghost_sym = self.positions[pid].get('symbol', '?')
                print(f"  [RECONCILE] GHOST REMOVED: {ghost_sym} posId={pid} — not on broker")
                self.local_positions.pop(ghost_sym, None)
                self.trailing_state.pop(pid, None)
                self._unsubscribe_spots(ghost_sym)
                del self.positions[pid]
            self._save_state()

        # Prune orphaned local_positions with no matching self.positions entry
        local_pid_syms = {p['symbol'] for p in self.positions.values()}
        orphan_syms = [sym for sym in list(self.local_positions.keys())
                       if sym not in local_pid_syms
                       and not any(bp['symbol'] == sym for bp in broker_positions.values())]
        if orphan_syms:
            for sym in orphan_syms:
                print(f"  [RECONCILE] ORPHAN REMOVED: {sym} — no matching broker position")
                self.local_positions.pop(sym, None)
            self._save_state()

        # ADD: broker positions we don't have locally
        missing_pids = broker_pids - local_pids
        if missing_pids:
            for pid in missing_pids:
                bp = broker_positions[pid]
                sym = bp['symbol']
                print(f"  [RECONCILE] MISSING ADDED: {sym} posId={pid} — found on broker")
                self.positions[pid] = {
                    'symbol': sym, 'symbolId': bp['symbolId'], 'side': bp['side'],
                    'volume': bp['volume'], 'positionId': pid,
                    'entry_price': bp['entry'], 'stop_loss': bp['sl'],
                    'take_profit': bp['tp'], 'lot_size': bp['volume'] / 10000000,
                    'open_time': datetime.now().isoformat(),
                }
                self.local_positions[sym] = {
                    'direction': bp['side'], 'entry_price': bp['entry'],
                    'lot_size': bp['volume'] / 10000000,
                    'stop_loss': bp['sl'], 'take_profit': bp['tp'],
                    'open_time': datetime.now().isoformat(),
                    'positionId': pid, 'bot': 'tradebot',
                }
                saved = self._saved_trailing_state.get(str(pid))
                if saved:
                    self.trailing_state[pid] = saved
                    self.trailing_state[pid]['current_sl'] = bp['sl']
                else:
                    self.trailing_state[pid] = {
                        'phase': 'initial', 'entry_price': bp['entry'],
                        'direction': bp['side'], 'symbol': sym,
                        'current_sl': bp['sl'], 'trail_activated': False,
                        'last_amend_time': 0, 'scaled_out': False,
                        'original_volume': bp['volume'],
                    }
                self._subscribe_spots(sym)
            self._save_state()

        changes = len(ghost_pids) + len(orphan_syms) + len(missing_pids)
        if changes:
            print(f"  [RECONCILE] Sync complete — {len(ghost_pids)} ghosts, {len(orphan_syms)} orphans, {len(missing_pids)} missing. Now: {len(self.positions)} positions")

        # ── LAYER 3 SL-GUARD: scan ALL broker positions for missing SL or TP ──
        for pid, bp in broker_positions.items():
            if bp['sl'] == 0 or bp['tp'] == 0:
                sym = bp['symbol']
                config = PAIRS.get(sym)
                if not config:
                    if bp['sl'] == 0:
                        print(f"  [SL-GUARD] WARNING: {sym} posId={pid} has NO SL and no config — cannot compute SL!")
                    continue
                ep = bp['entry']
                asset_type = config.get('type', 'forex')
                pip_value = self._get_pip_value(sym, asset_type)
                eff_reward = config['reward_pips'] - config.get('est_spread_pips', 0)

                # Compute missing SL
                sl_price = bp['sl']
                if bp['sl'] == 0:
                    if bp['side'] == 'BUY':
                        sl_price = round(ep - config['risk_pips'] * pip_value, 5)
                    else:
                        sl_price = round(ep + config['risk_pips'] * pip_value, 5)

                # Compute missing TP (only if not in trailing phase with TP already removed)
                tp_price = bp['tp']
                trail_state = self.trailing_state.get(pid, {})
                if bp['tp'] == 0 and not trail_state.get('tp_removed', False):
                    if bp['side'] == 'BUY':
                        tp_price = round(ep + eff_reward * pip_value, 5)
                    else:
                        tp_price = round(ep - eff_reward * pip_value, 5)

                if bp['sl'] == 0 or (bp['tp'] == 0 and tp_price):
                    sl_tag = f"SL={sl_price:.5f}" if bp['sl'] == 0 else ""
                    tp_tag = f"TP={tp_price:.5f}" if bp['tp'] == 0 and tp_price else ""
                    print(f"  [SL-GUARD] {sym} posId={pid} missing {sl_tag} {tp_tag} — amending")
                    # Amend: set both SL and TP
                    req = ProtoOAAmendPositionSLTPReq()
                    req.ctidTraderAccountId = CTID
                    req.positionId = pid
                    req.stopLoss = sl_price
                    if tp_price:
                        req.takeProfit = tp_price
                    d = self.client.send(req, responseTimeoutInSeconds=10)
                    d.addCallback(lambda msg, s=sym: print(f"  << SL-GUARD AMEND OK: {s}"))
                    d.addErrback(lambda f, s=sym: print(f"  << SL-GUARD AMEND FAILED: {s}: {f.getErrorMessage()}"))

                # Update all state dicts
                if bp['sl'] == 0:
                    if pid in self.positions:
                        self.positions[pid]['stop_loss'] = sl_price
                    if sym in self.local_positions:
                        self.local_positions[sym]['stop_loss'] = sl_price
                    if pid in self.trailing_state:
                        self.trailing_state[pid]['current_sl'] = sl_price
                if bp['tp'] == 0 and tp_price:
                    if pid in self.positions:
                        self.positions[pid]['take_profit'] = tp_price
                    if sym in self.local_positions:
                        self.local_positions[sym]['take_profit'] = tp_price
                self._save_state()

    def _trading_cycle(self):
        if not self.authenticated:
            print(f"[{self._ts()}] Not authenticated — skipping cycle")
            return

        if check_kill_switch():
            print(f"[{self._ts()}] Kill switch active — halting")
            if self._trading_loop and self._trading_loop.running:
                self._trading_loop.stop()
            return

        print(f"\n[{self._ts()}] Checking {len(PAIRS)} pairs...")

        # Fetch cTrader trendbars to populate cache (non-blocking, reactor thread)
        self._fetch_ctrader_trendbars()

        # Pre-compute depth analyses on reactor thread (reads deques, fast)
        depth_analyses = self._compute_all_depth_analyses()

        # Reconcile with broker FIRST, then fetch signals
        d = self._cycle_reconcile()
        d.addCallback(lambda _, da=depth_analyses: threads.deferToThread(
            self._fetch_all_signals, dict(PAIRS), dict(self._live_prices), da))
        d.addCallback(self._process_signals)
        d.addErrback(self._on_fetch_error)

    def _on_fetch_error(self, failure):
        print(f"[{self._ts()}] Fetch cycle error: {failure.getErrorMessage()}")

    def _process_signals(self, result):
        """Process fetch results back on the reactor thread (safe for cTrader API calls)."""
        prices, candles, signals, news_bias, log_lines = result

        for line in log_lines:
            print(line)

        # Update prices and candles for trailing stop + reversal detection
        self._last_prices = prices
        self._last_candles = candles
        self._manage_trailing_stops()
        self._check_reversal_exits(signals, news_bias)

        # Check for new signals — open positions via cTrader
        orders_sent_this_cycle = 0
        bonus_orders_sent = 0
        total_open = len(self.positions)
        max_pos = CONFIG['max_positions']
        max_bonus = CONFIG['max_bonus_positions']

        # Count how many bonus ("can't resist") positions are already open
        # Any positions beyond max_positions are bonus trades by definition
        existing_bonus = max(0, total_open - max_pos)

        for symbol, config in PAIRS.items():
            if symbol not in signals:
                continue
            signal, reason, score, layers = signals[symbol]
            if signal == 'HOLD':
                continue

            # Session filter: only enter during London+NY hours (08-21 UTC)
            current_utc_hour = datetime.now(timezone.utc).hour
            if current_utc_hour < 8 or current_utc_hour >= 21:
                continue

            # Per-pair auto-disable: skip if win rate too low (disabled for 24h)
            if symbol in self.pair_disabled_until:
                if datetime.now() < self.pair_disabled_until[symbol]:
                    continue
                else:
                    del self.pair_disabled_until[symbol]  # expired, re-enable

            # Already have a position in this symbol?
            if symbol in self.local_positions:
                continue

            # Cooldown check (15 min default, 60 min if 2+ consecutive losses)
            if symbol in self.last_trade_time:
                elapsed = (datetime.now() - self.last_trade_time[symbol]).total_seconds()
                consec = self.consecutive_losses.get(symbol, 0)
                lockout_minutes = 60 if consec >= 2 else CONFIG['cooldown_minutes']
                if elapsed < lockout_minutes * 60:
                    continue

            current_count = total_open + orders_sent_this_cycle

            if current_count < max_pos:
                # Normal slot available
                entry_price = prices[symbol]
                self._execute_order(symbol, signal, entry_price, config, reason)
                orders_sent_this_cycle += 1
            elif (existing_bonus + bonus_orders_sent) < max_bonus and score >= 9:
                # All slots full but this is a perfect setup (score 9/10 = near-max conviction)
                # Can't resist — take the bonus trade
                entry_price = prices[symbol]
                bonus_orders_sent += 1
                print(f"  ** BONUS TRADE #{existing_bonus + bonus_orders_sent}: {signal} {symbol} (perfect score {score}/10) **")
                self._execute_order(symbol, signal, entry_price, config, f"BONUS|{reason}")
                orders_sent_this_cycle += 1
                self._alert(
                    f"BONUS TRADE: {signal} {symbol}\n"
                    f"Perfect signal (score {score}/10)\n"
                    f"All layers + news aligned — couldn't resist"
                )

        # Refresh balance from broker
        if self.authenticated:
            req = ProtoOATraderReq()
            req.ctidTraderAccountId = CTID
            d = self.client.send(req)
            d.addCallbacks(self._on_balance_update, lambda f: None)

        self._save_state()
        open_count = len(self.positions)
        closed_count = len(self.closed_trades)
        print(f"  Balance: ${self.balance:.2f} | Open: {open_count} | Closed: {closed_count}")

    # ── Trailing stop management ──

    def _manage_trailing_stops(self):
        """Check open positions and move SL to break-even / activate trailing."""
        import time as _time
        now = _time.time()

        for pid, state in list(self.trailing_state.items()):
            symbol = state['symbol']
            # Prefer real-time cTrader spot price, fall back to Yahoo
            price = self._live_prices.get(symbol) or self._last_prices.get(symbol)
            if not price:
                continue

            config = PAIRS.get(symbol, {})
            if not config:
                continue

            entry = state['entry_price']
            direction = state['direction']
            asset_type = config.get('type', 'forex')

            pip_value = self._get_pip_value(symbol, asset_type)

            # Calculate profit in pips
            if direction == 'BUY':
                profit_pips = (price - entry) / pip_value
            else:
                profit_pips = (entry - price) / pip_value

            # Scale-out at 2× risk: percentage varies by asset class
            # Forex: 60% (lock more profit), Crypto/Commodity: 30% (let more ride)
            risk_pips = config['risk_pips']
            _scale_pct = {'forex': 0.60, 'crypto': 0.30, 'commodity': 0.30, 'index': 0.50}
            if (state.get('trail_activated')
                    and not state.get('scaled_out')
                    and not state.get('_scale_out_pending')
                    and profit_pips >= (risk_pips * 2)):
                original_vol = state.get('original_volume', 0)
                close_vol = int(original_vol * _scale_pct.get(asset_type, 0.50))
                if close_vol > 0 and pid in self.positions:
                    pct = _scale_pct.get(asset_type, 0.50)
                    print(f"  [SCALE-OUT] {symbol} closing {pct*100:.0f}% ({close_vol} vol) at {profit_pips:.1f} pips profit")
                    state['_scale_out_pending'] = True
                    remaining_vol = original_vol - close_vol
                    self._execute_scale_out(symbol, pid, close_vol, remaining_vol)

            # Ratchet SL forward for trailing positions using our own step_pips
            if state['trail_activated']:
                trigger_pips = config.get('trail_trigger_pips', config['risk_pips'])
                step_pips = config.get('trail_step_pips', config['risk_pips'] // 2)
                current_sl = state['current_sl']

                # Calculate the ideal SL: entry + N*step_offset (for BUY)
                # SL ratchets up in step_pips increments as profit grows
                step_offset = step_pips * pip_value
                steps_in_profit = int((profit_pips - trigger_pips) / step_pips)
                if steps_in_profit > 0:
                    if direction == 'BUY':
                        ideal_sl = round(entry + (steps_in_profit * step_offset), 5)
                    else:
                        ideal_sl = round(entry - (steps_in_profit * step_offset), 5)

                    # Minimum SL distance guard — SL must be >= step_pips from current price
                    min_sl_distance = step_pips * pip_value
                    if direction == 'BUY' and price - ideal_sl < min_sl_distance:
                        ideal_sl = round(price - min_sl_distance, 5)
                    elif direction == 'SELL' and ideal_sl - price < min_sl_distance:
                        ideal_sl = round(price + min_sl_distance, 5)

                    # Only move SL forward, never backward
                    should_amend = False
                    if direction == 'BUY' and ideal_sl > current_sl + (pip_value * 0.5):
                        should_amend = True
                    elif direction == 'SELL' and ideal_sl < current_sl - (pip_value * 0.5):
                        should_amend = True

                    if should_amend and (now - state['last_amend_time'] >= 30):
                        # Remove TP once SL locks in >= 1x risk (trigger_pips) of profit
                        sl_locked_pips = abs(ideal_sl - entry) / pip_value
                        clear_tp = not state.get('tp_removed', False) and sl_locked_pips >= trigger_pips
                        if clear_tp:
                            print(f"  [TRAIL-TP-REMOVED] {symbol} SL locks {sl_locked_pips:.1f} pips >= {trigger_pips} trigger — removing TP")
                            state['tp_removed'] = True

                        print(f"  [TRAIL-RATCHET] {symbol} SL {current_sl:.5f} -> {ideal_sl:.5f} "
                              f"(+{profit_pips:.1f} pips, step #{steps_in_profit})")
                        self._amend_sl(pid, symbol, ideal_sl, trailing=True, clear_tp=clear_tp)
                        state['current_sl'] = ideal_sl
                        state['last_amend_time'] = now
                        # Update both position dicts
                        if pid in self.positions:
                            self.positions[pid]['stop_loss'] = ideal_sl
                            if clear_tp:
                                self.positions[pid]['take_profit'] = 0
                        if symbol in self.local_positions:
                            self.local_positions[symbol]['stop_loss'] = ideal_sl
                        self._save_state()
                continue

            # Throttle: max one amend per 30s per position
            if now - state['last_amend_time'] < 30:
                continue

            trigger_pips = config.get('trail_trigger_pips', config['risk_pips'])
            step_pips = config.get('trail_step_pips', config['risk_pips'] // 2)

            phase = state['phase']

            # Phase: initial -> breakeven (profit >= 1x risk)
            if phase == 'initial' and profit_pips >= trigger_pips:
                new_sl = entry
                print(f"  [TRAIL] {symbol} -> BREAK-EVEN (profit {profit_pips:.1f} pips >= {trigger_pips})")
                self._amend_sl(pid, symbol, new_sl, trailing=False)
                state['phase'] = 'breakeven'
                state['current_sl'] = new_sl
                state['last_amend_time'] = now
                if pid in self.positions:
                    self.positions[pid]['stop_loss'] = new_sl
                if symbol in self.local_positions:
                    self.local_positions[symbol]['stop_loss'] = new_sl
                self._save_state()
                self._alert(f"TRAIL {symbol} -> BREAK-EVEN\nSL moved to entry {new_sl:.5f}")

            # Phase: breakeven -> trailing (profit >= 1.5x risk)
            # TP is kept until SL locks in >= 1x risk of profit
            elif phase == 'breakeven' and profit_pips >= (trigger_pips + step_pips):
                step_offset = step_pips * pip_value
                if direction == 'BUY':
                    new_sl = round(entry + step_offset, 5)
                else:
                    new_sl = round(entry - step_offset, 5)
                # Calculate how many pips SL locks in from entry
                sl_lock_pips = step_pips  # first step = step_pips above entry
                should_clear_tp = sl_lock_pips >= trigger_pips
                tp_status = "TP removed" if should_clear_tp else "TP kept"
                print(f"  [TRAIL] {symbol} -> TRAILING ACTIVE (profit {profit_pips:.1f} pips, SL={new_sl:.5f}, {tp_status})")
                self._amend_sl(pid, symbol, new_sl, trailing=True, clear_tp=should_clear_tp)
                state['phase'] = 'trailing'
                state['current_sl'] = new_sl
                state['trail_activated'] = True
                state['tp_removed'] = should_clear_tp
                state['last_amend_time'] = now
                if pid in self.positions:
                    self.positions[pid]['stop_loss'] = new_sl
                    if should_clear_tp:
                        self.positions[pid]['take_profit'] = 0
                if symbol in self.local_positions:
                    self.local_positions[symbol]['stop_loss'] = new_sl
                self._save_state()
                self._alert(f"TRAIL {symbol} -> TRAILING ACTIVE\nSL={new_sl:.5f}, {tp_status}")

    def _check_reversal_exits(self, signals, news_bias):
        """Proactively close positions when market signals a reversal.

        Two modes:
          1. Initial-phase positions: if 15M trend (Layer A) fully flips against the
             position, close at market to cut losses early (don't wait for full SL hit).
          2. Trailing positions: use full intelligence (EMA, momentum, news) with
             profit guards to detect when trend has turned.

        Profit guard (trailing only):
          - Strong reversal (MTF signal flip score >= 3/7): close at any profit level
          - Weak reversal (news + EMA, momentum + EMA): only close if profit >= 2× risk

        Reversal triggers (trailing):
          1. MTF signal engine generates opposite direction with score >= 3 (STRONG)
          2. News contradicts position AND EMA trend has flipped (WEAK — needs profit guard)
          3. Momentum reversed + EMA trend flipped (WEAK — needs profit guard)
        """
        for pid, state in list(self.trailing_state.items()):
            # ── Early exit for INITIAL phase: 15M trend flipped against position ──
            if not state['trail_activated'] and state['phase'] == 'initial':
                symbol = state['symbol']
                direction = state['direction']

                # Grace period: don't close positions in the first 5 minutes
                # Gives the trade time to develop — prevents instant close on noisy signals
                open_time_str = None
                if pid in self.positions:
                    open_time_str = self.positions[pid].get('open_time')
                elif symbol in self.local_positions:
                    open_time_str = self.local_positions[symbol].get('open_time')
                if open_time_str:
                    try:
                        open_dt = datetime.fromisoformat(open_time_str)
                        if not open_dt.tzinfo:
                            open_dt = open_dt.replace(tzinfo=timezone.utc)
                        age_minutes = (datetime.now(timezone.utc) - open_dt).total_seconds() / 60
                        if age_minutes < 5:
                            continue  # Too young — let the trade breathe
                    except (ValueError, TypeError):
                        pass

                if symbol in signals:
                    signal, reason, score, layers = signals[symbol]
                    # Opposite signal with sufficient conviction — close initial position early
                    # LS >= 2 = confirmed liquidity sweep against us + score >= 4
                    opposite = (direction == 'BUY' and signal == 'SELL' and layers.get('ls', 0) >= 2 and score >= 4)
                    opposite = opposite or (direction == 'SELL' and signal == 'BUY' and layers.get('ls', 0) >= 2 and score >= 4)
                    if opposite:
                        broker_pos = self.positions.get(pid)
                        if broker_pos:
                            price = self._live_prices.get(symbol) or self._last_prices.get(symbol)
                            print(f"  [REVERSAL-EARLY] {symbol} — signal flipped against {direction} (score {score}/10), closing initial position")
                            self._execute_close(symbol, pid, broker_pos['volume'])
                            self._alert(
                                f"EARLY EXIT: {symbol} ({direction})\n"
                                f"Signal reversed (score {score}/10) — cutting loss before SL\n"
                                f"{reason}"
                            )
                continue  # Skip trailing logic for non-trailing positions

            if not state['trail_activated']:
                continue  # Breakeven phase — let trailing logic handle it

            symbol = state['symbol']
            direction = state['direction']
            entry = state['entry_price']

            # Prefer real-time cTrader spot price, fall back to Yahoo
            price = self._live_prices.get(symbol) or self._last_prices.get(symbol)
            candle_data = self._last_candles.get(symbol)
            if not price or not candle_data:
                continue

            # Calculate current profit in pips for the profit guard
            config = PAIRS.get(symbol, {})
            if not config:
                continue
            asset_type = config.get('type', 'forex')
            pip_value = self._get_pip_value(symbol, asset_type)
            if direction == 'BUY':
                profit_pips = (price - entry) / pip_value
            else:
                profit_pips = (entry - price) / pip_value

            risk_pips = config['risk_pips']
            strong_reasons = []
            weak_reasons = []

            # ── Check 1 (STRONG): Signal engine flipped to opposite direction ──
            if symbol in signals:
                signal, reason, score, _layers = signals[symbol]
                if direction == 'BUY' and signal == 'SELL' and score >= 4:
                    strong_reasons.append(f"Signal flipped SELL (score {score}/10): {reason}")
                elif direction == 'SELL' and signal == 'BUY' and score >= 4:
                    strong_reasons.append(f"Signal flipped BUY (score {score}/10): {reason}")

            # ── Compute EMA trend + momentum from candles ──
            closes = candle_data.get('closes', [])
            ema_8 = calculate_ema(closes, 8) if len(closes) >= 8 else None
            ema_21 = calculate_ema(closes, 21) if len(closes) >= 21 else None
            trend_against = False
            momentum_against = False

            if ema_8 and ema_21:
                if direction == 'BUY' and ema_8 < ema_21:
                    trend_against = True
                elif direction == 'SELL' and ema_8 > ema_21:
                    trend_against = True

            if ema_8:
                ema_gap_pct = (price - ema_8) / ema_8 * 100
                if direction == 'BUY' and ema_gap_pct < -0.05:
                    momentum_against = True
                elif direction == 'SELL' and ema_gap_pct > 0.05:
                    momentum_against = True

            # ── Check 2 (WEAK): News contradicts + EMA trend flipped ──
            news_score = news_supports_direction(symbol, direction, news_bias)
            if news_score < 0 and trend_against:
                weak_reasons.append(f"News contradicts {direction} + EMA trend reversed")

            # ── Check 3 (WEAK): Momentum reversed + EMA trend flipped ──
            if momentum_against and trend_against and not weak_reasons:
                weak_reasons.append(f"Momentum + EMA trend reversed against {direction}")

            # ── Execute reversal exit with profit guard ──
            close_reasons = []

            # Strong signals: close at any profit (signal engine is high-conviction)
            if strong_reasons:
                close_reasons = strong_reasons

            # Weak signals: only close if profit >= 2× risk (protect against noise)
            elif weak_reasons and profit_pips >= (risk_pips * 2):
                close_reasons = weak_reasons

            if close_reasons:
                reason_text = '; '.join(close_reasons)
                print(f"  [REVERSAL] {symbol} — closing at +{profit_pips:.1f} pips: {reason_text}")

                broker_pos = self.positions.get(pid)
                if broker_pos:
                    self._execute_close(symbol, pid, broker_pos['volume'])
                    self._alert(
                        f"REVERSAL EXIT: {symbol} ({direction})\n"
                        f"Profit: +{profit_pips:.0f} pips\n"
                        f"{reason_text}"
                    )

    # ── Live spot price subscriptions ──

    def _subscribe_spots(self, symbol):
        """Subscribe to cTrader live spot prices for a symbol."""
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
            d.addCallback(lambda msg, s=symbol: print(f"  [SPOTS] Subscribed to {s} live prices"))
            d.addErrback(lambda f, s=symbol: print(f"  [SPOTS] Subscribe failed for {s}: {f.getErrorMessage()}"))
            self._spot_subscriptions.add(symbol)
        except Exception as e:
            print(f"  Warning: spot subscription failed for {symbol}: {e}")

    def _unsubscribe_spots(self, symbol):
        """Unsubscribe from cTrader live spot prices when no longer needed."""
        if symbol not in self._spot_subscriptions:
            return
        # Only unsubscribe if no other position uses this symbol
        still_needed = any(
            s['symbol'] == symbol for s in self.trailing_state.values()
        )
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
            print(f"  [SPOTS] Unsubscribed from {symbol}")
        except Exception as e:
            print(f"  Warning: spot unsubscribe failed for {symbol}: {e}")

    # ── SL/TP amendment ──

    def _amend_sl(self, position_id, symbol, new_sl, trailing=False, clear_tp=False):
        """Send ProtoOAAmendPositionSLTPReq to move SL (and optionally activate trailing).

        When clear_tp=True, TP is removed so the trailing SL becomes the only exit.
        """
        if not self.authenticated:
            print(f"  Cannot amend {symbol} — not authenticated")
            return

        req = ProtoOAAmendPositionSLTPReq()
        req.ctidTraderAccountId = CTID
        req.positionId = position_id
        req.stopLoss = new_sl
        req.trailingStopLoss = trailing

        if clear_tp:
            # Remove TP — let trailing SL ride the trend with no ceiling
            req.takeProfit = 0
            if symbol in self.local_positions:
                self.local_positions[symbol]['take_profit'] = 0
        else:
            # Preserve existing TP
            local = self.local_positions.get(symbol, {})
            if local.get('take_profit'):
                req.takeProfit = local['take_profit']

        trail_label = " +trailing" if trailing else ""
        tp_label = " (TP removed)" if clear_tp else ""
        print(f"  >> AMEND {symbol} posId={position_id} SL={new_sl:.5f}{trail_label}{tp_label}")

        d = self.client.send(req, responseTimeoutInSeconds=10)
        d.addCallback(lambda msg, s=symbol: self._on_amend_response(msg, s))
        d.addErrback(lambda f, s=symbol: self._on_amend_error(f, s))

    def _on_amend_response(self, msg, symbol):
        print(f"  << AMEND OK: {symbol}")

    def _on_amend_error(self, failure, symbol):
        err = failure.getErrorMessage()
        print(f"  << AMEND FAILED for {symbol}: {err}")

    # ── Order execution ──

    @staticmethod
    def _get_pip_multiplier(symbol, asset_type):
        """cTrader points per pip for relative SL/TP calculation.

        pip_multiplier = pip_value / point_size, where point_size = 10^(-broker_decimals)

        Confirmed from broker fill prices:
          Forex (5 dec): EURUSD 1.08123 → point=0.00001, pip=0.0001, mult=10
          JPY forex (3 dec): USDJPY 156.018 → point=0.001, pip=0.01, mult=10
          Crypto (2 dec): BTCUSD 66000.12, ETHUSD 2006.04 → point=0.01, pip=0.01, mult=1
          Gold/Oil (2 dec): XAUUSD 5186.12, XBRUSD 71.27 → point=0.01, pip=0.01, mult=1
          Silver (3 dec): XAGUSD 88.679 → point=0.001, pip=0.01, mult=10
          Nat Gas (3 dec): XNGUSD ~2.960 → point=0.001, pip=0.001, mult=1
          Indices (0 dec): JP225 58657, US30 49192 → point=1, pip=1.0, mult=1
          Indices (1 dec): US500 5500.1, AUS200 9069.6 → point=0.1, pip=0.1, mult=1
        """
        if asset_type == 'forex':
            return 10      # All forex: 10 (5-dec and 3-dec JPY both use mult=10)
        elif symbol == 'XAGUSD':
            return 10      # Silver: 3 decimals
        else:
            return 1       # All other CFDs: crypto, gold, oil, nat gas, all indices

    @staticmethod
    def _get_pip_value(symbol, asset_type):
        """Price distance per pip.
        Used for SL/TP price calculation, profit measurement, and trailing stops.

        Index pip values calibrated from cTrader price feeds:
          JP225 58657.00 — moves in whole numbers, 1 pip = 1.0
          US30  42000.00 — moves in whole numbers, 1 pip = 1.0
          US500  5500.10 — moves in 0.10, 1 pip = 0.1
          USTEC 19000.10 — moves in 0.10, 1 pip = 0.1
          UK100 10896.60 — moves in 0.10, 1 pip = 0.1
          DE30  25000.10 — moves in 0.10, 1 pip = 0.1
          AUS200 9198.60 — moves in 0.10, 1 pip = 0.1
        """
        if 'JPY' in symbol and asset_type == 'forex':
            return 0.01
        elif asset_type == 'forex':
            return 0.0001
        elif symbol == 'XNGUSD':
            return 0.001    # Natural gas: 3 decimals (e.g. 2.972)
        elif symbol in ('JP225', 'US30'):
            return 1.0      # Whole-number indices
        elif asset_type == 'index':
            return 0.1      # Most indices move in 0.10 increments
        else:
            return 0.01     # crypto, commodity (metals, oil)

    def _calc_safe_volume(self, symbol, config, entry_price):
        """Calculate the maximum safe volume that keeps dollar risk within limits.

        Risk budget = balance * MAX_RISK_PER_TRADE (from trading_safety).
        We work backwards from the dollar risk formula to find the max volume.
        """
        from lib.trading_safety import MAX_RISK_PER_TRADE
        asset_type = config.get('type', 'forex')
        sl_pips = config['risk_pips']
        max_risk = self.balance * MAX_RISK_PER_TRADE
        base_volume = config['volume']

        if max_risk <= 0 or sl_pips <= 0 or entry_price <= 0:
            return base_volume  # Can't calculate — use default

        # Estimate dollar risk at the configured volume
        dollar_risk = estimate_dollar_risk(base_volume, entry_price, sl_pips, symbol, asset_type)

        if dollar_risk <= 0:
            return base_volume  # Can't estimate — use default

        if dollar_risk <= max_risk:
            return base_volume  # Already within budget

        # Scale down: new_volume = base_volume * (max_risk / dollar_risk)
        scale = max_risk / dollar_risk
        safe_volume = int(base_volume * scale)

        # Enforce minimums (cTrader rejects 0-volume orders)
        min_volume = 100 if asset_type in ('crypto', 'commodity', 'index') else 100000
        safe_volume = max(safe_volume, min_volume)

        if safe_volume < base_volume:
            new_risk = estimate_dollar_risk(safe_volume, entry_price, sl_pips, symbol, asset_type)
            print(f"  [RISK-SCALE] {symbol}: vol {base_volume}->{safe_volume} "
                  f"(risk ${dollar_risk:.2f}->${new_risk:.2f}, budget=${max_risk:.2f})")

        return safe_volume

    def _execute_order(self, symbol, direction, entry_price, config, reason):
        if symbol in self._skip_symbols:
            return  # silently skip — errored previously this session
        sym_id = SYMBOL_IDS.get(symbol)
        if not sym_id:
            print(f"  Unknown symbol ID for {symbol}")
            return

        asset_type = config.get('type', 'forex')

        # ── SAFETY GATE: pre-trade checks (kill switch, drawdown, position limits, R:R) ──
        est_spread = config.get('est_spread_pips', 0)
        can_trade, check_reason = pre_trade_checks(
            volume=config['volume'],
            balance=self.balance,
            starting_balance=self._starting_balance,
            open_positions=len(self.positions),
            mode='demo',
            price=entry_price,
            symbol=symbol,
            asset_type=asset_type,
            sl_pips=config['risk_pips'],
            reward_pips=config['reward_pips'],
            est_spread_pips=est_spread,
        )
        if not can_trade:
            print(f"  [BLOCKED] {symbol}: {check_reason}")
            return

        # ── HARD R:R GATE: reject if effective R:R < 2:1 after spread ──
        effective_reward = config['reward_pips'] - est_spread
        if config['risk_pips'] > 0 and effective_reward / config['risk_pips'] < MIN_RR_RATIO:
            print(f"  [RR-BLOCK] {symbol}: effective R:R {effective_reward/config['risk_pips']:.2f}:1 < {MIN_RR_RATIO}:1 "
                  f"(reward={config['reward_pips']} - spread={est_spread} = {effective_reward} vs risk={config['risk_pips']})")
            return

        # ── DYNAMIC POSITION SIZING: scale volume to keep risk within budget ──
        volume = self._calc_safe_volume(symbol, config, entry_price)

        side = ProtoOATradeSide.Value('BUY') if direction == 'BUY' else ProtoOATradeSide.Value('SELL')

        # Relative SL/TP in cTrader points
        # Convert: price_distance = pips * pip_value, then to points using pip_multiplier
        pip_multiplier = self._get_pip_multiplier(symbol, asset_type)
        risk_points = int(round(config['risk_pips'] * pip_multiplier))
        reward_points = int(round(effective_reward * pip_multiplier))

        # Final dollar risk sanity log
        pip_value = self._get_pip_value(symbol, asset_type)
        sl_dist = config['risk_pips'] * pip_value
        tp_dist = effective_reward * pip_value
        final_risk = estimate_dollar_risk(volume, entry_price, config['risk_pips'], symbol, asset_type)

        req = ProtoOANewOrderReq()
        req.ctidTraderAccountId = CTID
        req.symbolId = sym_id
        req.orderType = ProtoOAOrderType.Value('MARKET')
        req.tradeSide = side
        req.volume = volume
        req.relativeStopLoss = risk_points
        req.relativeTakeProfit = reward_points
        req.comment = f"TradeBot|{reason[:30]}"
        req.label = "TradeBot"

        lot_display = volume / 10000000  # Display as lots
        print(f"  >> SENDING {direction} {symbol} vol={volume} ({lot_display:g}lot) "
              f"SL={config['risk_pips']}pip TP={config['reward_pips']}pip risk=${final_risk:.2f} "
              f"(SL_dist={sl_dist:.4f} TP_dist={tp_dist:.4f} pts={risk_points}/{reward_points})")

        d = self.client.send(req, responseTimeoutInSeconds=10)
        config_with_reason = dict(config, _reason=reason, _actual_volume=volume)
        d.addCallback(lambda msg, s=symbol, d2=direction, ep=entry_price, c=config_with_reason: self._on_order_response(msg, s, d2, ep, c))
        d.addErrback(lambda f, s=symbol: self._on_order_error(f, s))

    def _on_order_response(self, msg, symbol, direction, entry_price, config):
        # This callback fires when the broker acknowledges the order request.
        # It is NOT confirmation of a fill — the actual fill comes via _on_message
        # (ProtoOAExecutionEvent with etype==2, vol>0). We only set cooldown here
        # and store the config so _on_message can build the local_positions entry.
        # Note: cooldown (last_trade_time) is set on FILL, not here — see _on_message etype==2
        self._pending_order_configs[symbol] = {
            'direction': direction, 'entry_price': entry_price, 'config': config,
        }
        print(f"  << ORDER ACCEPTED: {direction} {symbol} — awaiting fill confirmation")

    def _on_order_error(self, failure, symbol):
        err = failure.getErrorMessage()
        print(f"  << ORDER FAILED for {symbol}: {err}")
        # Skip this symbol for the rest of the session to avoid log spam
        self._skip_symbols.add(symbol)
        print(f"  [SKIP] {symbol} — will not retry this session")

    # ── Scale-out (partial close with callback confirmation) ──

    def _execute_scale_out(self, symbol, pid, close_vol, remaining_vol):
        """Close half the position and confirm scaled_out in the callback."""
        if not self.authenticated:
            print(f"  Cannot scale-out {symbol} — not authenticated")
            return

        req = ProtoOAClosePositionReq()
        req.ctidTraderAccountId = CTID
        req.positionId = pid
        req.volume = close_vol

        lot_display = close_vol / 10000000
        print(f"  >> SCALE-OUT {symbol} posId={pid} closing {lot_display:g}lot")

        d = self.client.send(req, responseTimeoutInSeconds=10)
        d.addCallback(lambda msg, s=symbol, p=pid, rv=remaining_vol, cv=close_vol:
                      self._on_scale_out_response(msg, s, p, rv, cv))
        d.addErrback(lambda f, s=symbol, p=pid:
                     self._on_scale_out_error(f, s, p))

    def _on_scale_out_response(self, msg, symbol, pid, remaining_vol, closed_vol):
        """Broker ACK for scale-out request. NOT a fill confirmation.

        Do NOT set scaled_out=True or update volumes here — that happens
        in _on_message when the execution event (etype=2) confirms the
        partial close with the reduced volume. This callback only logs
        that the broker accepted the request.
        """
        print(f"  << SCALE-OUT ACCEPTED: {symbol} posId={pid} — awaiting fill confirmation")

    def _on_scale_out_error(self, failure, symbol, pid):
        err = failure.getErrorMessage()
        print(f"  << SCALE-OUT FAILED for {symbol}: {err}")
        # Clear pending flag so it retries next cycle
        state = self.trailing_state.get(pid)
        if state:
            state.pop('_scale_out_pending', None)
        self._alert(f"SCALE-OUT FAILED: {symbol}\n{err}")

    # ── Close position via cTrader API ──

    def _execute_close(self, symbol: str, position_id: int, volume: int):
        """Send a ProtoOAClosePositionReq to the broker."""
        if not self.authenticated:
            print(f"  Cannot close {symbol} — not authenticated")
            self._alert(f"CLOSE FAILED: {symbol} — not authenticated to broker")
            return

        req = ProtoOAClosePositionReq()
        req.ctidTraderAccountId = CTID
        req.positionId = position_id
        req.volume = volume

        lot_display = volume / 10000000
        print(f"  >> CLOSING {symbol} posId={position_id} vol={volume} ({lot_display:g}lot)")
        self._alert(f"Closing {symbol} (posId={position_id}, vol={volume})")

        d = self.client.send(req, responseTimeoutInSeconds=10)
        d.addCallback(lambda msg, s=symbol: self._on_close_response(msg, s))
        d.addErrback(lambda f, s=symbol: self._on_close_error(f, s))

    def _on_close_response(self, msg, symbol):
        print(f"  << CLOSE SENT: {symbol}")

    def _on_close_error(self, failure, symbol):
        err = failure.getErrorMessage()
        print(f"  << CLOSE FAILED for {symbol}: {err}")
        self._alert(f"CLOSE FAILED: {symbol}\n{err}")

    def _on_balance_update(self, msg):
        try:
            payload = Protobuf.extract(msg)
            self.balance = payload.trader.balance / 100
        except Exception:
            pass

    # ── Watchdog — keeps state fresh and force-reconnects if stuck ──

    def _watchdog(self):
        """Runs every 30s regardless of connection state.
        - Saves state so the dashboard always has a fresh timestamp.
        - If disconnected for > 3 minutes, force-restart the client connection.
        """
        self._save_state()

        if self.authenticated:
            return  # All good — trading loop handles everything

        # Not authenticated — check how long we've been down
        if self._last_authenticated_at:
            down_seconds = (datetime.now(timezone.utc) - self._last_authenticated_at).total_seconds()
        elif self._last_connected_at:
            down_seconds = (datetime.now(timezone.utc) - self._last_connected_at).total_seconds()
        else:
            # Never connected yet — give initial startup 3 minutes
            down_seconds = 0

        if down_seconds > 180:  # 3 minutes disconnected
            print(f"[{self._ts()}] WATCHDOG: Disconnected for {down_seconds:.0f}s — force-restarting connection")
            self._alert(
                f"WATCHDOG: Force-restarting connection\n"
                f"Disconnected for {down_seconds:.0f}s ({self._consecutive_failures} failures)\n"
                f"Open positions: {len(self.positions)} UNMONITORED"
            )
            try:
                self.client.stopService()
            except Exception as e:
                print(f"[{self._ts()}] WATCHDOG: stopService error (ignored): {e}")
            # Reset failure counters so backoff starts fresh
            self._consecutive_failures = 0
            self._reconnect_count = 0
            self._last_authenticated_at = datetime.now(timezone.utc)  # Reset timer to avoid rapid restarts
            try:
                self.client.startService()
                print(f"[{self._ts()}] WATCHDOG: Connection restarted")
            except Exception as e:
                print(f"[{self._ts()}] WATCHDOG: startService error: {e}")
        elif down_seconds > 0:
            print(f"[{self._ts()}] WATCHDOG: Waiting for reconnect ({down_seconds:.0f}s down, attempt {self._consecutive_failures})")

    # ── Error handling ──

    def _on_error(self, failure):
        print(f"[{self._ts()}] API Error: {failure.getErrorMessage()}")
        self.authenticated = False

    # ── Task dispatch integration ──

    def _check_tasks(self):
        """Poll for tasks assigned to tradebot and execute them."""
        try:
            tasks = get_pending_tasks('tradebot')
        except Exception as e:
            print(f"[{self._ts()}] Task poll error: {e}")
            return

        for task_data in tasks:
            task_id = task_data['id']
            task_type = task_data.get('task_type', '')
            print(f"[{self._ts()}] Task found: {task_id} ({task_type})")

            claimed = claim_task(task_id)
            if not claimed:
                continue

            try:
                if task_type == 'trade_analysis':
                    result = self._task_trade_analysis(claimed)
                elif task_type == 'market_scan':
                    result = self._task_market_scan(claimed)
                elif task_type == 'report':
                    result = self._task_report(claimed)
                elif task_type == 'close_position':
                    result = self._task_close_position(claimed)
                elif task_type == 'close_all':
                    result = self._task_close_all(claimed)
                else:
                    fail_task(task_id, f'Unknown task type: {task_type}')
                    continue
                complete_task(task_id, result)
                print(f"[{self._ts()}] Task {task_id} completed")
            except Exception as e:
                print(f"[{self._ts()}] Task {task_id} failed: {e}")
                fail_task(task_id, str(e))

    def _task_trade_analysis(self, task_data: dict) -> dict:
        """Analyze a specific symbol or the current portfolio."""
        params = task_data.get('params', {})
        symbol = params.get('symbol', '').upper()
        symbols_to_check = [symbol] if symbol and symbol in PAIRS else list(PAIRS.keys())

        analysis = {}
        task_news_bias = get_news_bias()
        for sym in symbols_to_check:
            price, tf_15m, tf_5m, tf_1m = get_mtf_data(sym)
            if price and (tf_15m or tf_5m or tf_1m):
                signal, reason, score, layers = get_advanced_signal(sym, price, tf_15m, tf_5m, tf_1m, task_news_bias)
                in_session, market = is_market_open()
                has_position = sym in self.local_positions
                analysis[sym] = {
                    'price': price, 'signal': signal, 'reason': reason,
                    'score': score, 'layers': layers,
                    'session': market, 'in_session': in_session,
                    'has_position': has_position,
                }
                if has_position:
                    pos = self.local_positions[sym]
                    analysis[sym]['position'] = {
                        'direction': pos.get('direction'),
                        'entry_price': pos.get('entry_price'),
                        'stop_loss': pos.get('stop_loss'),
                        'take_profit': pos.get('take_profit'),
                    }

        return {'analysis': analysis, 'symbols_checked': len(analysis), 'balance': self.balance}

    def _task_market_scan(self, task_data: dict) -> dict:
        """Scan all pairs for current signals."""
        signals = {}
        scan_news_bias = get_news_bias()
        for sym, config in PAIRS.items():
            price, tf_15m, tf_5m, tf_1m = get_mtf_data(sym)
            if price and (tf_15m or tf_5m or tf_1m):
                signal, reason, score, layers = get_advanced_signal(sym, price, tf_15m, tf_5m, tf_1m, scan_news_bias)
                signals[sym] = {
                    'price': price, 'signal': signal, 'reason': reason,
                    'score': score, 'layers': layers,
                    'config': {'risk_pips': config['risk_pips'], 'reward_pips': config['reward_pips']},
                }

        actionable = {s: v for s, v in signals.items() if v['signal'] != 'HOLD'}
        in_session, market = is_market_open()

        return {
            'signals': signals,
            'actionable': actionable,
            'total_scanned': len(signals),
            'actionable_count': len(actionable),
            'market_session': market,
            'in_session': in_session,
            'open_positions': len(self.positions),
            'balance': self.balance,
        }

    def _task_report(self, task_data: dict) -> dict:
        """Generate a portfolio/performance report."""
        stats = {
            'balance': round(self.balance, 2),
            'open_positions': len(self.positions),
            'total_closed': len(self.closed_trades),
            'wins': len([t for t in self.closed_trades if t.get('pnl', 0) > 0]),
            'losses': len([t for t in self.closed_trades if t.get('pnl', 0) <= 0]),
            'total_pnl': round(sum(t.get('pnl', 0) for t in self.closed_trades), 2),
        }
        if stats['total_closed'] > 0:
            stats['win_rate'] = round(stats['wins'] / stats['total_closed'] * 100, 1)
        else:
            stats['win_rate'] = 0.0

        positions_detail = {}
        for sym, pos in self.local_positions.items():
            positions_detail[sym] = {
                'direction': pos.get('direction'),
                'entry_price': pos.get('entry_price'),
                'lot_size': pos.get('lot_size'),
                'stop_loss': pos.get('stop_loss'),
                'take_profit': pos.get('take_profit'),
                'open_time': pos.get('open_time'),
            }

        return {
            'stats': stats,
            'positions': positions_detail,
            'mode': MODE,
            'connected': self.authenticated,
            'generated_at': datetime.now(timezone.utc).isoformat(),
        }

    def _task_close_position(self, task_data: dict) -> dict:
        """Close a specific position by symbol or positionId."""
        params = task_data.get('params', {})
        symbol = params.get('symbol', '').upper()
        position_id = params.get('positionId')

        if not self.authenticated:
            return {'error': 'Not authenticated to broker', 'closed': False}

        # Find the position
        if position_id and position_id in self.positions:
            pos = self.positions[position_id]
            volume = pos['volume']
            sym = pos['symbol']
        elif symbol and symbol in self.local_positions:
            local = self.local_positions[symbol]
            position_id = local.get('positionId')
            if not position_id or position_id not in self.positions:
                return {'error': f'No broker position found for {symbol}', 'closed': False}
            volume = self.positions[position_id]['volume']
            sym = symbol
        else:
            return {'error': f'Position not found: symbol={symbol} posId={position_id}', 'closed': False}

        self._execute_close(sym, position_id, volume)
        return {'symbol': sym, 'positionId': position_id, 'closed': True, 'volume': volume}

    def _task_close_all(self, task_data: dict) -> dict:
        """Close all open positions."""
        if not self.authenticated:
            return {'error': 'Not authenticated to broker', 'closed': 0}

        closed = []
        for pid, pos in list(self.positions.items()):
            self._execute_close(pos['symbol'], pid, pos['volume'])
            closed.append({'symbol': pos['symbol'], 'positionId': pid})

        return {'closed': len(closed), 'positions': closed}

    # ── Trailing state persistence ──

    TRAIL_STATE_FILE = '/root/.openclaw/workspace/employees/trailing_state.json'

    @staticmethod
    def _load_trailing_state() -> dict:
        """Load persisted trailing state from disk. Returns {str(pid): state_dict}."""
        _path = '/root/.openclaw/workspace/employees/trailing_state.json'
        try:
            if os.path.isfile(_path):
                with open(_path, 'r') as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    print(f"  Loaded trailing state: {len(data)} positions from disk")
                    return data
        except Exception as e:
            print(f"  Warning: failed to load trailing state: {e}")
        return {}

    def _persist_trailing_state(self):
        """Save trailing state to disk for crash recovery."""
        # Convert int pid keys to strings for JSON, skip transient fields
        saveable = {}
        for pid, state in self.trailing_state.items():
            s = dict(state)
            s.pop('_scale_out_pending', None)  # transient
            s['last_amend_time'] = 0  # reset throttle on restart
            saveable[str(pid)] = s
        try:
            atomic_json_write(self.TRAIL_STATE_FILE, saveable)
        except Exception as e:
            print(f"  Warning: failed to persist trailing state: {e}")

    # ── State persistence (for dashboard) ──

    def _save_state(self):
        pnls = [t.get('pnl', 0) for t in self.closed_trades]
        gross_wins = sum(p for p in pnls if p > 0)
        gross_losses = abs(sum(p for p in pnls if p <= 0))
        stats = {
            'balance': round(self.balance, 2),
            'open': len(self.positions),
            'total': len(self.closed_trades),
            'wins': len([p for p in pnls if p > 0]),
            'losses': len([p for p in pnls if p <= 0]),
            'win_rate': 0,
            'total_pnl': round(sum(pnls), 2),
            'profit_factor': round(gross_wins / gross_losses, 2) if gross_losses > 0 else 0.0,
            'sharpe_ratio': 0.0,
        }
        if stats['total'] > 0:
            stats['win_rate'] = round(stats['wins'] / stats['total'] * 100, 1)
        # Sharpe ratio: mean(returns) / std(returns) — annualized is overkill for live paper
        if len(pnls) >= 2:
            import statistics
            _mean = statistics.mean(pnls)
            _stdev = statistics.stdev(pnls)
            stats['sharpe_ratio'] = round(_mean / _stdev, 2) if _stdev > 0 else 0.0

        # Enrich positions with trail phase for dashboard visibility
        # Use pid-keyed positions for accuracy (handles duplicate symbols)
        positions_with_trail = {}
        for pid, pos in self.positions.items():
            sym = pos.get('symbol', '?')
            # Build display data from pid-keyed position (accurate per-position)
            pos_data = {
                'direction': pos.get('side', '?'),
                'entry_price': pos.get('entry_price', 0),
                'lot_size': pos.get('lot_size', 0),
                'stop_loss': pos.get('stop_loss', 0),
                'take_profit': pos.get('take_profit', 0),
                'open_time': pos.get('open_time', ''),
                'positionId': pid,
                'bot': 'tradebot',
            }
            if pid in self.trailing_state:
                pos_data['trail_phase'] = self.trailing_state[pid]['phase']
                pos_data['trail_activated'] = self.trailing_state[pid]['trail_activated']
                pos_data['scaled_out'] = self.trailing_state[pid].get('scaled_out', False)
            # Use pid-based key to handle duplicate symbols in dashboard
            display_key = f"{sym}_{pid}" if sym in positions_with_trail else sym
            positions_with_trail[display_key] = pos_data

        state_data = {
            'balance': self.balance,
            'positions': positions_with_trail,
            'closed_trades': self.closed_trades[-50:],  # Keep last 50
            'stats': stats,
            'mode': 'demo',
            'connected': self.authenticated,
            'last_update': datetime.now().isoformat(),
        }

        for path in ['/root/.openclaw/workspace/employees/trading_state.json',
                     '/root/.openclaw/workspace/employees/paper-trading-state.json']:
            try:
                atomic_json_write(path, state_data)
            except Exception as e:
                print(f"Warning: failed to save state to {path}: {e}")

        status_data = {
            'balance': round(self.balance, 2),
            'connected': self.authenticated,
            'mode': 'demo',
            'account': str(CTID),
            'positions': len(self.positions),
            'last_update': datetime.now().isoformat(),
        }
        try:
            atomic_json_write('/root/.openclaw/workspace/employees/trading_status.json', status_data)
        except Exception as e:
            print(f"Warning: failed to save status: {e}")

        # Persist trailing state for crash recovery
        self._persist_trailing_state()

    # ── Alerting ──

    def _alert(self, text: str):
        """Send a Telegram alert via Zeff.bot pipeline."""
        try:
            import html
            safe_text = html.escape(text)
            msg = (
                "<b>⬡ ZEFF.BOT</b>\n"
                "<b>🤖 TRADEBOT ALERT</b>\n"
                f"<i>{self._ts()}</i>\n\n"
                f"{safe_text}"
            )
            telegram_send(msg)
        except Exception as e:
            print(f"[{self._ts()}] WARNING: Telegram alert failed: {e}")

    # ── Utility ──

    @staticmethod
    def _ts():
        return datetime.now().strftime("%H:%M:%S")


if __name__ == '__main__':
    engine = TradeBotEngine()
    engine.start()
