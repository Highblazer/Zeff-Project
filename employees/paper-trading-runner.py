#!/usr/bin/env python3
"""
TradeBot - Advanced Strategy: Fair Value Gaps + S/R + Market Structure
Risk:Reward 1:3 + Trailing Stop | Focus on market opens
Executes real trades on IC Markets cTrader Demo account via Open API
"""

import requests
import json
import os
from datetime import datetime, timezone

# Safety imports
import sys
sys.path.insert(0, '/root/.openclaw/workspace')
from lib.trading_safety import check_kill_switch, validate_price
from lib.credentials import get_icm_credentials
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
    ProtoOAGetPositionUnrealizedPnLReq,
    ProtoOAAmendPositionSLTPReq,
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
    ProtoOAOrderType, ProtoOATradeSide,
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
    # volume 100000 = 0.01 lot (micro). Smaller to fit more positions on $200 balance.
    # R:R 1:3 + trailing stop. trail_trigger = 1× risk, trail_step = 0.5× risk.
    'EURUSD':  {'name': 'EUR/USD',  'type': 'forex',  'volume': 100000, 'risk_pips': 10, 'reward_pips': 30, 'trail_trigger_pips': 10, 'trail_step_pips': 5},
    'GBPUSD':  {'name': 'GBP/USD',  'type': 'forex',  'volume': 100000, 'risk_pips': 12, 'reward_pips': 36, 'trail_trigger_pips': 12, 'trail_step_pips': 6},
    'USDJPY':  {'name': 'USD/JPY',  'type': 'forex',  'volume': 100000, 'risk_pips': 12, 'reward_pips': 36, 'trail_trigger_pips': 12, 'trail_step_pips': 6},
    'AUDUSD':  {'name': 'AUD/USD',  'type': 'forex',  'volume': 100000, 'risk_pips': 10, 'reward_pips': 30, 'trail_trigger_pips': 10, 'trail_step_pips': 5},
    'USDCAD':  {'name': 'USD/CAD',  'type': 'forex',  'volume': 100000, 'risk_pips': 12, 'reward_pips': 36, 'trail_trigger_pips': 12, 'trail_step_pips': 6},
    'USDCHF':  {'name': 'USD/CHF',  'type': 'forex',  'volume': 100000, 'risk_pips': 12, 'reward_pips': 36, 'trail_trigger_pips': 12, 'trail_step_pips': 6},
    'NZDUSD':  {'name': 'NZD/USD',  'type': 'forex',  'volume': 100000, 'risk_pips': 10, 'reward_pips': 30, 'trail_trigger_pips': 10, 'trail_step_pips': 5},
    # ── Forex Crosses ──
    'EURJPY':  {'name': 'EUR/JPY',  'type': 'forex',  'volume': 100000, 'risk_pips': 15, 'reward_pips': 45, 'trail_trigger_pips': 15, 'trail_step_pips': 8},
    'GBPJPY':  {'name': 'GBP/JPY',  'type': 'forex',  'volume': 100000, 'risk_pips': 18, 'reward_pips': 54, 'trail_trigger_pips': 18, 'trail_step_pips': 9},
    'EURGBP':  {'name': 'EUR/GBP',  'type': 'forex',  'volume': 100000, 'risk_pips': 10, 'reward_pips': 30, 'trail_trigger_pips': 10, 'trail_step_pips': 5},
    # ── Crypto ──
    # cTrader CFD: volume / 100 = broker units. Min from broker error messages.
    'BTCUSD':  {'name': 'BTC/USD',  'type': 'crypto', 'volume': 100,    'risk_pips': 500, 'reward_pips': 1500, 'trail_trigger_pips': 500, 'trail_step_pips': 250},
    'ETHUSD':  {'name': 'ETH/USD',  'type': 'crypto', 'volume': 100,    'risk_pips': 30,  'reward_pips': 90,   'trail_trigger_pips': 30,  'trail_step_pips': 15},
    'SOLUSD':  {'name': 'SOL/USD',  'type': 'crypto', 'volume': 100,    'risk_pips': 200, 'reward_pips': 600,  'trail_trigger_pips': 200, 'trail_step_pips': 100},
    'XRPUSD':  {'name': 'XRP/USD',  'type': 'crypto', 'volume': 100,    'risk_pips': 50,  'reward_pips': 150,  'trail_trigger_pips': 50,  'trail_step_pips': 25},
    'LTCUSD':  {'name': 'LTC/USD',  'type': 'crypto', 'volume': 100,    'risk_pips': 200, 'reward_pips': 600,  'trail_trigger_pips': 200, 'trail_step_pips': 100},
    'ADAUSD':  {'name': 'ADA/USD',  'type': 'crypto', 'volume': 100,    'risk_pips': 50,  'reward_pips': 150,  'trail_trigger_pips': 50,  'trail_step_pips': 25},
    'DOGEUSD': {'name': 'DOGE/USD', 'type': 'crypto', 'volume': 10000,  'risk_pips': 20,  'reward_pips': 60,   'trail_trigger_pips': 20,  'trail_step_pips': 10},
    'LNKUSD':  {'name': 'LINK/USD', 'type': 'crypto', 'volume': 100,    'risk_pips': 100, 'reward_pips': 300,  'trail_trigger_pips': 100, 'trail_step_pips': 50},
    # ── Commodities ──
    # These need significant margin — may get NOT_ENOUGH_MONEY on small accounts.
    'XAUUSD':  {'name': 'Gold',     'type': 'commodity', 'volume': 100, 'risk_pips': 200, 'reward_pips': 600, 'trail_trigger_pips': 200, 'trail_step_pips': 100},
    'XAGUSD':  {'name': 'Silver',   'type': 'commodity', 'volume': 5000,'risk_pips': 30,  'reward_pips': 90,  'trail_trigger_pips': 30,  'trail_step_pips': 15},
    'XTIUSD':  {'name': 'WTI Oil',  'type': 'commodity', 'volume': 5000,'risk_pips': 30,  'reward_pips': 90,  'trail_trigger_pips': 30,  'trail_step_pips': 15},
    'XBRUSD':  {'name': 'Brent Oil','type': 'commodity', 'volume': 5000,'risk_pips': 30,  'reward_pips': 90,  'trail_trigger_pips': 30,  'trail_step_pips': 15},
    'XNGUSD':  {'name': 'Nat Gas',  'type': 'commodity', 'volume': 500000,'risk_pips': 20,'reward_pips': 60,  'trail_trigger_pips': 20,  'trail_step_pips': 10},
    # ── Indices ──
    # Index volume: may need substantial margin on small accounts.
    'US500':   {'name': 'S&P 500',  'type': 'index', 'volume': 100,    'risk_pips': 50,  'reward_pips': 150, 'trail_trigger_pips': 50,  'trail_step_pips': 25},
    'US30':    {'name': 'Dow Jones', 'type': 'index', 'volume': 100,    'risk_pips': 80,  'reward_pips': 240, 'trail_trigger_pips': 80,  'trail_step_pips': 40},
    'USTEC':   {'name': 'Nasdaq',    'type': 'index', 'volume': 100,    'risk_pips': 70,  'reward_pips': 210, 'trail_trigger_pips': 70,  'trail_step_pips': 35},
    'UK100':   {'name': 'FTSE 100',  'type': 'index', 'volume': 100,    'risk_pips': 40,  'reward_pips': 120, 'trail_trigger_pips': 40,  'trail_step_pips': 20},
    'DE30':    {'name': 'DAX',       'type': 'index', 'volume': 100,    'risk_pips': 50,  'reward_pips': 150, 'trail_trigger_pips': 50,  'trail_step_pips': 25},
    'JP225':   {'name': 'Nikkei',    'type': 'index', 'volume': 100,    'risk_pips': 80,  'reward_pips': 240, 'trail_trigger_pips': 80,  'trail_step_pips': 40},
    'AUS200':  {'name': 'ASX 200',   'type': 'index', 'volume': 100,    'risk_pips': 30,  'reward_pips': 90,  'trail_trigger_pips': 30,  'trail_step_pips': 15},
}

CONFIG = {
    'max_positions': 5,       # max 5 simultaneous trades
    'check_interval': 45,     # check every 45 seconds
    'cooldown_minutes': 5,    # shorter cooldown = more trades
}

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

# ── Price fetching (Yahoo Finance for analysis candles) ──

def get_price(symbol):
    yahoo_symbols = {
        # Forex
        'EURUSD': 'EURUSD=X', 'GBPUSD': 'GBPUSD=X', 'USDJPY': 'USDJPY=X',
        'AUDUSD': 'AUDUSD=X', 'USDCAD': 'USDCAD=X', 'USDCHF': 'USDCHF=X',
        'NZDUSD': 'NZDUSD=X', 'EURJPY': 'EURJPY=X', 'GBPJPY': 'GBPJPY=X',
        'EURGBP': 'EURGBP=X',
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
    try:
        yahoo = yahoo_symbols.get(symbol, symbol)
        headers = {'User-Agent': 'Mozilla/5.0'}
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo}"
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        if 'result' not in data['chart'] or not data['chart']['result']:
            return None, None
        price = data['chart']['result'][0]['meta']['regularMarketPrice']

        url2 = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo}?interval=1h&range=48h"
        r2 = requests.get(url2, headers=headers, timeout=10)
        data2 = r2.json()
        if 'result' not in data2['chart'] or not data2['chart']['result']:
            return price, None
        candles = data2['chart']['result'][0]['indicators']['quote'][0]
        highs = [h for h in candles.get('high', []) if h is not None]
        lows = [l for l in candles.get('low', []) if l is not None]
        closes = [c for c in candles.get('close', []) if c is not None]
        return price, {'highs': highs, 'lows': lows, 'closes': closes}
    except Exception:
        return None, None


# ══════════════════════════════════════════════════════════════════════
#  NEWS-DRIVEN MOMENTUM STRATEGY
#  Philosophy: Lose small, win big. Trade WITH the trend and the news.
#  - Tight SL (10-12 pips) so losses are tiny
#  - TP at 3× risk (1:3 R:R) + trailing stop to lock in gains
#  - Break-even at 1× risk, broker auto-trail at 1.5× risk
#  - News bias tips the scale — only trade in the direction news supports
#  - EMA trend + momentum confirm entry timing
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


def get_signal(symbol, price, data):
    """News-driven momentum strategy.

    Entry rules (need 2 of 3):
      1. EMA trend — 8 EMA > 21 EMA = bullish, else bearish
      2. Momentum — price above/below EMA 8 with separation
      3. News bias — news supports the direction

    Filters:
      - Don't trade AGAINST the news (hard block)
      - Stronger signals when all 3 align

    Risk management: 1:3 R:R + trailing stop. Break-even at 1× risk,
    then broker auto-trails. You only need ~25% win rate to be profitable.
    """
    if not data or len(data.get('closes', [])) < 25:
        return 'HOLD', 'Insufficient data', 0

    closes = data['closes']
    highs = data['highs']
    lows = data['lows']
    current_price = closes[-1]

    # ── Indicators ──
    ema_8 = calculate_ema(closes, 8)
    ema_21 = calculate_ema(closes, 21)
    if not ema_8 or not ema_21:
        return 'HOLD', 'EMA not ready', 0

    # ── Trend direction ──
    trend = 'bullish' if ema_8 > ema_21 else 'bearish'

    # ── Momentum — price pulling away from fast EMA ──
    ema_gap_pct = (current_price - ema_8) / ema_8 * 100
    has_momentum_up = ema_gap_pct > 0.02    # price above EMA 8
    has_momentum_down = ema_gap_pct < -0.02  # price below EMA 8

    # ── Recent range breakout ──
    if len(closes) >= 8:
        high_8 = max(highs[-8:])
        low_8 = min(lows[-8:])
        breaking_up = current_price >= high_8
        breaking_down = current_price <= low_8
    else:
        breaking_up = breaking_down = False

    # ── News bias ──
    news_bias = get_news_bias()
    in_session, session_name = is_market_open()

    # ── Signal scoring ──
    buy_score = 0
    sell_score = 0

    # 1. EMA trend
    if trend == 'bullish':
        buy_score += 1
    else:
        sell_score += 1

    # 2. Momentum
    if has_momentum_up:
        buy_score += 1
    if has_momentum_down:
        sell_score += 1

    # 3. Breakout
    if breaking_up:
        buy_score += 1
    if breaking_down:
        sell_score += 1

    # 4. News (bonus point, but also hard block if contradicts)
    news_buy = news_supports_direction(symbol, 'BUY', news_bias)
    news_sell = news_supports_direction(symbol, 'SELL', news_bias)

    if news_buy > 0:
        buy_score += 1
    if news_sell > 0:
        sell_score += 1

    # ── Decision ──
    # Need score >= 2 to trade. News contradiction = hard block.
    if buy_score >= 2 and buy_score > sell_score:
        if news_buy < 0:
            return 'HOLD', f'News blocks BUY ({news_bias["usd_bias"]})', buy_score
        reason = f'Momentum BUY (score {buy_score}) {session_name}'
        if news_buy > 0:
            reason += f' +news({news_bias["usd_bias"]})'
        return 'BUY', reason, buy_score

    if sell_score >= 2 and sell_score > buy_score:
        if news_sell < 0:
            return 'HOLD', f'News blocks SELL ({news_bias["usd_bias"]})', sell_score
        reason = f'Momentum SELL (score {sell_score}) {session_name}'
        if news_sell > 0:
            reason += f' +news({news_bias["usd_bias"]})'
        return 'SELL', reason, sell_score

    return 'HOLD', 'No setup', 0


# ══════════════════════════════════════════════════════════════════════
#  cTrader Trading Engine — runs on Twisted reactor
# ══════════════════════════════════════════════════════════════════════

class TradeBotEngine:
    def __init__(self):
        self.client = Client(EndPoints.PROTOBUF_DEMO_HOST, EndPoints.PROTOBUF_PORT, TcpProtocol)
        self.authenticated = False
        self.balance = 0.0
        self.positions = {}        # positionId -> position data from broker
        self.local_positions = {}  # symbol -> local tracking (for dashboard)
        self.closed_trades = []
        self.last_trade_time = {}
        self._reconnect_count = 0
        self._consecutive_failures = 0
        self._last_disconnect_alert = 0  # timestamp of last Telegram alert
        self._last_connected_at = None
        self._trading_loop = None
        self._task_loop = None
        self._skip_symbols = set()  # symbols that errored — skip for rest of session
        self.trailing_state = {}   # positionId -> {phase, entry_price, direction, symbol, current_sl, trail_activated, last_amend_time, scaled_out, original_volume}
        self._last_prices = {}     # symbol -> latest price from cycle
        self._last_candles = {}    # symbol -> candle data (highs, lows, closes) for reversal detection
        self._live_prices = {}     # symbol -> real-time bid/ask from cTrader spot subscription
        self._spot_subscriptions = set()  # symbols currently subscribed to spot prices

    # ── Connection lifecycle ──

    def start(self):
        print("=" * 60)
        print("TradeBot - IC Markets cTrader Demo")
        print("Strategy: EMA Momentum + News Bias | R:R 1:3 + Trailing Stop")
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
        self._alert(f"Account authenticated (DEMO). Reconciling positions...")
        # Get account balance
        req = ProtoOATraderReq()
        req.ctidTraderAccountId = CTID
        d = self.client.send(req)
        d.addCallbacks(self._on_trader_info, self._on_error)

    def _on_trader_info(self, msg):
        payload = Protobuf.extract(msg)
        self.balance = payload.trader.balance / 100
        print(f"[{self._ts()}] Account balance: ${self.balance:.2f}")
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
            }
            self.local_positions[symbol] = {
                'direction': side,
                'entry_price': entry,
                'lot_size': volume / 10000000,  # 100000 vol = 0.01 lot
                'stop_loss': sl,
                'take_profit': tp,
                'open_time': datetime.now().isoformat(),
                'positionId': pos.positionId,
                'bot': 'tradebot',
            }
            # Rebuild trailing state from broker position
            broker_trailing = getattr(pos, 'trailingStopLoss', False)
            if broker_trailing:
                phase = 'trailing'
            elif sl and entry:
                # Detect if SL has been moved to break-even
                config = PAIRS.get(symbol, {})
                pip_val = 0.01 if ('JPY' in symbol and config.get('type') == 'forex') else 0.0001 if config.get('type') == 'forex' else 0.01
                if side == 'BUY' and sl >= entry - (pip_val * 0.5):
                    phase = 'breakeven'
                elif side == 'SELL' and sl <= entry + (pip_val * 0.5):
                    phase = 'breakeven'
                else:
                    phase = 'initial'
            else:
                phase = 'initial'
            self.trailing_state[pos.positionId] = {
                'phase': phase,
                'entry_price': entry,
                'direction': side,
                'symbol': symbol,
                'current_sl': sl,
                'trail_activated': broker_trailing,
                'last_amend_time': 0,
                'scaled_out': broker_trailing,  # If already trailing, assume scale-out happened
                'original_volume': volume,
            }
            # Subscribe to live spot prices for open positions
            self._subscribe_spots(symbol)
        print(f"[{self._ts()}] Reconciled {len(self.positions)} open positions from broker")
        self._alert(
            f"ONLINE — {len(self.positions)} positions reconciled\n"
            f"Balance: ${self.balance:.2f}"
        )
        for pid, p in self.positions.items():
            sym = p['symbol']
            lots = p['volume'] / 10000000
            entry = self.local_positions.get(sym, {}).get('entry_price', 0)
            print(f"  {p['side']} {sym} {lots:.2f}lot @ {entry:.5f} posId={pid}")

        self._save_state()
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

                    if etype == 2 and vol > 0:  # ORDER_FILLED with volume = new/open
                        lots = vol / 10000000
                        print(f"  [FILL] {side} {sym} {lots:.2f}lot @ {pos.price:.5f} posId={pid}")
                        self.positions[pid] = {
                            'symbol': sym, 'symbolId': pos.tradeData.symbolId,
                            'side': side, 'volume': vol, 'positionId': pid,
                        }
                        # Initialize trailing stop state for this position
                        sl_price = pos.stopLoss if pos.stopLoss else 0
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
                        # Subscribe to live spot prices for this symbol
                        self._subscribe_spots(sym)
                    elif etype == 2 and vol == 0:  # FILLED with 0 volume = position closed
                        if pid in self.positions:
                            closed_sym = self.positions[pid]['symbol']
                            broker_pnl = self._extract_broker_pnl(payload)
                            print(f"  [CLOSED] {closed_sym} posId={pid} P&L=${broker_pnl:.2f}" if broker_pnl is not None else f"  [CLOSED] {closed_sym} posId={pid}")
                            closed_pos = self.local_positions.get(closed_sym, {})
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
                    elif asset_type in ('commodity', 'index'):
                        divisor = 100.0        # 2 decimal places
                    else:
                        divisor = 100000.0
                    self._live_prices[symbol] = payload.bid / divisor
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
        print(f"\n[{cycle}] Checking {len(PAIRS)} pairs...")

        prices = {}
        signals = {}

        # Get news bias once per cycle (shared across all pairs)
        news_bias = get_news_bias()
        in_session, session_name = is_market_open()
        print(f"  News: USD={news_bias['usd_bias']} Risk={news_bias['risk_sentiment']} "
              f"Crypto={news_bias.get('crypto_bias','?')} Oil={news_bias.get('oil_bias','?')} "
              f"Conf={news_bias['confidence']:.1f} | Session={session_name}")

        candles = {}
        for symbol, config in PAIRS.items():
            price, data = get_price(symbol)
            if price and data:
                if not validate_price(price, symbol):
                    continue
                prices[symbol] = price
                candles[symbol] = data
                signal, reason, score = get_signal(symbol, price, data)
                signals[symbol] = (signal, reason, score)
                print(f"  {config['name']}: {price:.5f} | {signal} ({reason})")

        # Update prices and candles for trailing stop + reversal detection
        self._last_prices = prices
        self._last_candles = candles
        self._manage_trailing_stops()
        self._check_reversal_exits(signals, news_bias)

        # Check for new signals — open positions via cTrader
        orders_sent_this_cycle = 0
        for symbol, config in PAIRS.items():
            if symbol not in signals:
                continue
            signal, reason, score = signals[symbol]
            if signal == 'HOLD':
                continue

            # Already have a position in this symbol?
            if symbol in self.local_positions:
                continue

            # Max positions check (count pending orders sent this cycle too)
            if (len(self.positions) + orders_sent_this_cycle) >= CONFIG['max_positions']:
                continue

            # Cooldown check
            if symbol in self.last_trade_time:
                elapsed = (datetime.now() - self.last_trade_time[symbol]).total_seconds()
                if elapsed < CONFIG['cooldown_minutes'] * 60:
                    continue

            entry_price = prices[symbol]
            self._execute_order(symbol, signal, entry_price, config, reason)
            orders_sent_this_cycle += 1

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
            if state['trail_activated']:
                continue  # Broker is auto-trailing, nothing to do

            symbol = state['symbol']
            # Prefer real-time cTrader spot price, fall back to Yahoo
            price = self._live_prices.get(symbol) or self._last_prices.get(symbol)
            if not price:
                continue

            # Throttle: max one amend per 30s per position
            if now - state['last_amend_time'] < 30:
                continue

            config = PAIRS.get(symbol, {})
            if not config:
                continue

            entry = state['entry_price']
            direction = state['direction']
            asset_type = config.get('type', 'forex')

            # pip_value: price distance per pip
            if 'JPY' in symbol and asset_type == 'forex':
                pip_value = 0.01
            elif asset_type == 'forex':
                pip_value = 0.0001
            else:
                pip_value = 0.01  # crypto, commodity, index

            trigger_pips = config.get('trail_trigger_pips', config['risk_pips'])
            step_pips = config.get('trail_step_pips', config['risk_pips'] // 2)

            # Calculate profit in pips
            if direction == 'BUY':
                profit_pips = (price - entry) / pip_value
            else:
                profit_pips = (entry - price) / pip_value

            phase = state['phase']

            # Phase: initial -> breakeven (profit >= 1x risk)
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
                self._alert(f"TRAIL {symbol} -> BREAK-EVEN\nSL moved to entry {new_sl:.5f}")

            # Phase: breakeven -> trailing (profit >= 1.5x risk)
            elif phase == 'breakeven' and profit_pips >= (trigger_pips + step_pips):
                step_offset = step_pips * pip_value
                if direction == 'BUY':
                    new_sl = round(entry + step_offset, 5)
                else:
                    new_sl = round(entry - step_offset, 5)
                print(f"  [TRAIL] {symbol} -> TRAILING ACTIVE (profit {profit_pips:.1f} pips, SL={new_sl:.5f})")
                self._amend_sl(pid, symbol, new_sl, trailing=True, clear_tp=True)
                state['phase'] = 'trailing'
                state['current_sl'] = new_sl
                state['trail_activated'] = True
                state['last_amend_time'] = now
                if symbol in self.local_positions:
                    self.local_positions[symbol]['stop_loss'] = new_sl
                self._save_state()
                self._alert(f"TRAIL {symbol} -> TRAILING ACTIVE\nSL={new_sl:.5f}, TP removed — riding trend until reversal")

            # Scale-out: close 50% at 2× risk to lock in guaranteed profit
            risk_pips = config['risk_pips']
            if state.get('trail_activated') and not state.get('scaled_out') and profit_pips >= (risk_pips * 2):
                original_vol = state.get('original_volume', 0)
                close_vol = original_vol // 2
                if close_vol > 0 and pid in self.positions:
                    print(f"  [SCALE-OUT] {symbol} closing 50% ({close_vol} vol) at {profit_pips:.1f} pips profit")
                    self._execute_close(symbol, pid, close_vol)
                    state['scaled_out'] = True
                    # Update tracked volume
                    remaining_vol = original_vol - close_vol
                    self.positions[pid]['volume'] = remaining_vol
                    if symbol in self.local_positions:
                        self.local_positions[symbol]['lot_size'] = remaining_vol / 10000000
                    self._save_state()
                    self._alert(
                        f"SCALE-OUT: {symbol}\n"
                        f"Closed 50% at +{profit_pips:.0f} pips profit\n"
                        f"Remaining 50% trailing with no TP"
                    )

    def _check_reversal_exits(self, signals, news_bias):
        """Proactively close trailing positions when market signals a reversal.

        Uses the bot's full intelligence — EMA trend, momentum, news bias —
        to detect when a trend has turned against an open trailing position.
        Only applies to positions where trailing is active (TP removed).

        Profit guard:
          - Strong reversal (signal flip score >= 2): close at any profit level
          - Weak reversal (news + EMA, momentum + EMA): only close if profit >= 2× risk
            This prevents premature exits on noise when the trade just started trailing.

        Reversal triggers:
          1. Signal engine generates opposite direction with score >= 2 (STRONG)
          2. News contradicts position AND EMA trend has flipped (WEAK — needs profit guard)
          3. Momentum reversed + EMA trend flipped (WEAK — needs profit guard)
        """
        for pid, state in list(self.trailing_state.items()):
            if not state['trail_activated']:
                continue  # Only check positions riding the trend (TP removed)

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
            if 'JPY' in symbol and asset_type == 'forex':
                pip_value = 0.01
            elif asset_type == 'forex':
                pip_value = 0.0001
            else:
                pip_value = 0.01
            if direction == 'BUY':
                profit_pips = (price - entry) / pip_value
            else:
                profit_pips = (entry - price) / pip_value

            risk_pips = config['risk_pips']
            strong_reasons = []
            weak_reasons = []

            # ── Check 1 (STRONG): Signal engine flipped to opposite direction ──
            if symbol in signals:
                signal, reason, score = signals[symbol]
                if direction == 'BUY' and signal == 'SELL' and score >= 2:
                    strong_reasons.append(f"Signal flipped SELL (score {score}): {reason}")
                elif direction == 'SELL' and signal == 'BUY' and score >= 2:
                    strong_reasons.append(f"Signal flipped BUY (score {score}): {reason}")

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

    def _execute_order(self, symbol, direction, entry_price, config, reason):
        if symbol in self._skip_symbols:
            return  # silently skip — errored previously this session
        sym_id = SYMBOL_IDS.get(symbol)
        if not sym_id:
            print(f"  Unknown symbol ID for {symbol}")
            return

        side = ProtoOATradeSide.Value('BUY') if direction == 'BUY' else ProtoOATradeSide.Value('SELL')
        volume = config['volume']  # cTrader units: 100000 = 0.01 lot

        # Relative SL/TP in cTrader points (smallest price increment)
        # cTrader uses integer points — must match symbol's digit precision
        asset_type = config.get('type', 'forex')
        if 'JPY' in symbol and asset_type == 'forex':
            pip_multiplier = 100     # JPY forex: 3 decimals, 1 pip = 100 points
        elif asset_type == 'forex':
            pip_multiplier = 10      # Standard forex: 5 decimals, 1 pip = 10 points
        elif asset_type == 'crypto':
            pip_multiplier = 100     # Crypto: 2 decimals on cTrader
        elif symbol in ('XAUUSD', 'XAGUSD'):
            pip_multiplier = 100     # Metals: 2-3 decimals
        elif symbol in ('XTIUSD', 'XBRUSD', 'XNGUSD'):
            pip_multiplier = 100     # Energy: 2-3 decimals
        elif asset_type == 'index':
            pip_multiplier = 100     # Indices: 1-2 decimals
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
        req.comment = f"TradeBot|{reason[:30]}"
        req.label = "TradeBot"

        lot_display = volume / 10000000  # Display as lots
        print(f"  >> SENDING {direction} {symbol} {lot_display:.2f}lot SL={config['risk_pips']}pip TP={config['reward_pips']}pip")

        d = self.client.send(req, responseTimeoutInSeconds=10)
        config_with_reason = dict(config, _reason=reason)
        d.addCallback(lambda msg, s=symbol, d2=direction, ep=entry_price, c=config_with_reason: self._on_order_response(msg, s, d2, ep, c))
        d.addErrback(lambda f, s=symbol: self._on_order_error(f, s))

    def _on_order_response(self, msg, symbol, direction, entry_price, config):
        print(f"  << ORDER FILLED: {direction} {symbol}")
        self.last_trade_time[symbol] = datetime.now()
        # Calculate SL/TP for dashboard display
        multiplier = 0.0001
        if 'JPY' in symbol:
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
            'direction': direction,
            'entry_price': entry_price,
            'lot_size': lot_size,
            'stop_loss': sl,
            'take_profit': tp,
            'open_time': datetime.now().isoformat(),
            'bot': 'tradebot',
        }
        self._save_state()

        # Report to Zeff.bot → Telegram
        try:
            report_trade_opened(symbol, direction, entry_price, lot_size, sl, tp, config.get('_reason', ''))
        except Exception as e:
            print(f"  Warning: Telegram report failed: {e}")

    def _on_order_error(self, failure, symbol):
        err = failure.getErrorMessage()
        print(f"  << ORDER FAILED for {symbol}: {err}")
        # Skip this symbol for the rest of the session to avoid log spam
        self._skip_symbols.add(symbol)
        print(f"  [SKIP] {symbol} — will not retry this session")

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
        print(f"  >> CLOSING {symbol} posId={position_id} {lot_display:.2f}lot")
        self._alert(f"Closing {symbol} (posId={position_id}, {lot_display:.2f}lot)")

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
        for sym in symbols_to_check:
            price, data = get_price(sym)
            if price and data:
                signal, reason = get_signal(sym, price, data)
                in_session, market = is_market_open()
                has_position = sym in self.local_positions
                analysis[sym] = {
                    'price': price, 'signal': signal, 'reason': reason,
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
        for sym, config in PAIRS.items():
            price, data = get_price(sym)
            if price and data:
                signal, reason = get_signal(sym, price, data)
                signals[sym] = {
                    'price': price, 'signal': signal, 'reason': reason,
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

    # ── State persistence (for dashboard) ──

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

        # Enrich positions with trail phase for dashboard visibility
        positions_with_trail = {}
        for sym, pos in self.local_positions.items():
            pos_data = dict(pos)
            # Find trailing state by positionId
            pid = pos.get('positionId')
            if pid and pid in self.trailing_state:
                pos_data['trail_phase'] = self.trailing_state[pid]['phase']
                pos_data['trail_activated'] = self.trailing_state[pid]['trail_activated']
                pos_data['scaled_out'] = self.trailing_state[pid].get('scaled_out', False)
            positions_with_trail[sym] = pos_data

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
