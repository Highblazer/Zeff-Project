#!/usr/bin/env python3
"""
Signal API — FastAPI service exposing trading signals, news sentiment, and stats.

Endpoints:
  GET /api/signals/latest      — all current signals with scores + layers
  GET /api/signals/{symbol}    — detailed analysis for one pair
  GET /api/signals/history     — historical signal log
  GET /api/news/sentiment      — current market bias from news intelligence
  GET /api/stats               — bot performance (win rate, profit factor, Sharpe)
  GET /api/status              — system status (uptime, memory, load)
  GET /api/agents              — agent roster

Auth: API key via X-API-Key header or ?api_key= query param.
Rate limiting: 100 req/min free tier, 1000 req/min paid tier.
"""

import json
import os
import sys
import time
import hashlib
import secrets
from datetime import datetime, timezone
from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ── Paths ──
WORKSPACE = '/root/.openclaw/workspace'
STATE_FILE = os.path.join(WORKSPACE, 'employees/trading_state.json')
SIGNAL_HISTORY = os.path.join(WORKSPACE, 'employees/signal_history.jsonl')
NEWS_INTEL_PATH = os.path.join(WORKSPACE, 'memory/tradebot-intel.md')
API_KEYS_PATH = os.path.join(WORKSPACE, 'python/api_keys.json')

# ── Import signal engine (for on-demand analysis) ──
sys.path.insert(0, WORKSPACE)

# ── Rate limiting state ──
_rate_buckets: dict[str, list[float]] = defaultdict(list)
RATE_LIMITS = {'free': 100, 'paid': 1000}  # requests per minute

app = FastAPI(
    title="OpenClaw Signal API",
    description="Trading signals, news sentiment, and performance stats from the OpenClaw fleet.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ── Helpers ──

def _load_api_keys() -> dict:
    try:
        with open(API_KEYS_PATH) as f:
            return json.load(f).get('keys', {})
    except Exception:
        return {}


def _save_api_keys(keys: dict):
    with open(API_KEYS_PATH, 'w') as f:
        json.dump({'keys': keys}, f, indent=2)


def _load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _load_signal_history(limit: int = 100, symbol: str = None) -> list:
    results = []
    try:
        with open(SIGNAL_HISTORY) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if symbol and entry.get('symbol') != symbol.upper():
                    continue
                results.append(entry)
    except FileNotFoundError:
        pass
    return results[-limit:]


def _load_news_intel() -> dict:
    """Parse the news intel markdown file for sentiment data."""
    try:
        with open(NEWS_INTEL_PATH) as f:
            content = f.read()
    except Exception:
        return {'available': False}

    # Count directional keywords (same logic as paper-trading-runner)
    lower = content.lower()
    usd_bull_kw = ['rate hike', 'hawkish', 'strong dollar', 'fed tighten', 'nonfarm beat',
                   'cpi higher', 'inflation rise', 'gdp growth', 'employment strong']
    usd_bear_kw = ['rate cut', 'dovish', 'weak dollar', 'fed ease', 'nonfarm miss',
                   'cpi lower', 'inflation fall', 'recession', 'unemployment rise']
    risk_on_kw = ['rally', 'optimism', 'risk-on', 'stocks rise', 'market up', 'vix fall']
    risk_off_kw = ['crisis', 'fear', 'risk-off', 'selloff', 'crash', 'tension', 'war']
    crypto_bull_kw = ['bitcoin rally', 'crypto rally', 'btc rise', 'adoption', 'etf approved']
    crypto_bear_kw = ['bitcoin crash', 'crypto crash', 'btc fall', 'crypto ban', 'regulation']

    bull = sum(1 for kw in usd_bull_kw if kw in lower)
    bear = sum(1 for kw in usd_bear_kw if kw in lower)
    ron = sum(1 for kw in risk_on_kw if kw in lower)
    roff = sum(1 for kw in risk_off_kw if kw in lower)
    cbull = sum(1 for kw in crypto_bull_kw if kw in lower)
    cbear = sum(1 for kw in crypto_bear_kw if kw in lower)

    usd_bias = 'bullish' if bull > bear and bull >= 2 else ('bearish' if bear > bull and bear >= 2 else 'neutral')
    risk = 'risk_on' if ron > roff and ron >= 2 else ('risk_off' if roff > ron and roff >= 2 else 'neutral')
    crypto = 'bullish' if cbull > cbear else ('bearish' if cbear > cbull else 'neutral')

    headlines = content.count('###')

    return {
        'available': True,
        'usd_bias': usd_bias,
        'risk_sentiment': risk,
        'crypto_bias': crypto,
        'confidence': min((bull + bear + ron + roff + cbull + cbear) / 10.0, 1.0),
        'headlines': headlines,
        'last_updated': os.path.getmtime(NEWS_INTEL_PATH) if os.path.exists(NEWS_INTEL_PATH) else None,
    }


# ── Auth dependency ──

async def verify_api_key(request: Request):
    """Verify API key from header or query param. Returns key info."""
    key = request.headers.get('X-API-Key') or request.query_params.get('api_key')
    if not key:
        raise HTTPException(status_code=401, detail="Missing API key. Pass via X-API-Key header or ?api_key= param.")

    keys = _load_api_keys()
    if key not in keys:
        raise HTTPException(status_code=403, detail="Invalid API key.")

    key_info = keys[key]
    if not key_info.get('active', True):
        raise HTTPException(status_code=403, detail="API key is deactivated.")

    # Rate limiting
    tier = key_info.get('tier', 'free')
    limit = RATE_LIMITS.get(tier, 100)
    now = time.time()
    bucket = _rate_buckets[key]
    # Prune old entries (> 60s)
    bucket[:] = [t for t in bucket if now - t < 60]
    if len(bucket) >= limit:
        raise HTTPException(status_code=429, detail=f"Rate limit exceeded ({limit}/min for {tier} tier).")
    bucket.append(now)

    return key_info


# ── Endpoints ──

@app.get("/api/signals/latest")
async def signals_latest(auth: dict = Depends(verify_api_key)):
    """Get all current signals with scores and layer breakdown."""
    state = _load_state()
    positions = state.get('positions', {})
    stats = state.get('stats', {})

    # Load recent signals from history
    history = _load_signal_history(limit=50)
    # Group by symbol, keep latest per symbol
    latest_by_symbol = {}
    for entry in history:
        sym = entry.get('symbol')
        if sym:
            latest_by_symbol[sym] = entry

    return {
        'signals': latest_by_symbol,
        'open_positions': len(positions),
        'balance': stats.get('balance'),
        'mode': state.get('mode', 'demo'),
        'last_update': state.get('last_update'),
        'generated_at': datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/signals/{symbol}")
async def signal_detail(symbol: str, auth: dict = Depends(verify_api_key)):
    """Get detailed signal analysis for a specific symbol."""
    symbol = symbol.upper()
    history = _load_signal_history(limit=20, symbol=symbol)
    state = _load_state()
    positions = state.get('positions', {})

    # Check if we have an open position
    open_position = None
    for key, pos in positions.items():
        pos_sym = key.split('_')[0] if '_' in key else key
        if pos_sym == symbol:
            open_position = pos
            break

    if not history:
        raise HTTPException(status_code=404, detail=f"No signal data for {symbol}")

    latest = history[-1]
    return {
        'symbol': symbol,
        'latest_signal': latest,
        'history': history,
        'open_position': open_position,
        'generated_at': datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/signals/history")
async def signal_history(
    limit: int = Query(100, ge=1, le=1000),
    symbol: str = Query(None),
    auth: dict = Depends(verify_api_key),
):
    """Get historical signals from the archive."""
    history = _load_signal_history(limit=limit, symbol=symbol)
    return {
        'count': len(history),
        'signals': history,
        'generated_at': datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/news/sentiment")
async def news_sentiment(auth: dict = Depends(verify_api_key)):
    """Get current market news sentiment analysis."""
    intel = _load_news_intel()
    return {
        'sentiment': intel,
        'generated_at': datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/stats")
async def trading_stats(auth: dict = Depends(verify_api_key)):
    """Get bot performance statistics."""
    state = _load_state()
    stats = state.get('stats', {})
    closed = state.get('closed_trades', [])

    # Compute additional metrics from closed trades
    pnls = [t.get('pnl', 0) for t in closed if 'pnl' in t]
    by_symbol = defaultdict(list)
    for t in closed:
        if 'pnl' in t:
            by_symbol[t.get('symbol', 'unknown')].append(t['pnl'])

    symbol_stats = {}
    for sym, pnl_list in by_symbol.items():
        wins = [p for p in pnl_list if p > 0]
        losses = [p for p in pnl_list if p <= 0]
        symbol_stats[sym] = {
            'trades': len(pnl_list),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': round(len(wins) / len(pnl_list) * 100, 1) if pnl_list else 0,
            'total_pnl': round(sum(pnl_list), 2),
        }

    return {
        'overall': stats,
        'by_symbol': symbol_stats,
        'total_closed_trades': len(closed),
        'mode': state.get('mode', 'demo'),
        'connected': state.get('connected', False),
        'last_update': state.get('last_update'),
        'generated_at': datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/status")
async def system_status():
    """Public endpoint — no auth required. System health check."""
    try:
        with open('/proc/uptime') as f:
            uptime = float(f.read().split()[0])
        with open('/proc/meminfo') as f:
            meminfo = f.read()
        mem_total = int([l for l in meminfo.split('\n') if 'MemTotal' in l][0].split()[1]) / 1024
        mem_avail = int([l for l in meminfo.split('\n') if 'MemAvailable' in l][0].split()[1]) / 1024
        mem_pct = ((mem_total - mem_avail) / mem_total) * 100
        with open('/proc/loadavg') as f:
            load = f.read().split()[:3]
    except Exception as e:
        return {'error': str(e)}

    return {
        'uptime_seconds': int(uptime),
        'uptime_human': f"{int(uptime // 3600)}h {int((uptime % 3600) // 60)}m",
        'memory_percent': round(mem_pct, 1),
        'load': load,
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/agents")
async def agents():
    """Public endpoint — agent roster."""
    return [
        {"id": "001", "name": "Zeff.bot", "role": "CEO", "status": "online"},
        {"id": "003", "name": "TradeBot", "role": "CTO — Chief Trading Officer", "status": "running"},
        {"id": "004", "name": "Natalia", "role": "CRO — Chief Research Officer", "status": "running"},
        {"id": "005", "name": "Ali.bot", "role": "CTS — Chief Trading Strategist", "status": "running"},
        {"id": "008", "name": "Poly.Bot", "role": "CPO — Chief Prediction Officer", "status": "running"},
    ]


# ── Admin: generate new API keys ──

@app.post("/admin/keys/generate")
async def generate_key(
    tier: str = Query("free"),
    owner: str = Query("anonymous"),
    admin_secret: str = Query(...),
):
    """Generate a new API key (admin only)."""
    expected_secret = os.environ.get('SIGNAL_API_ADMIN_SECRET', 'changeme')
    if admin_secret != expected_secret:
        raise HTTPException(status_code=403, detail="Invalid admin secret.")

    new_key = secrets.token_urlsafe(32)
    keys = _load_api_keys()
    keys[new_key] = {
        'tier': tier,
        'rate_limit': RATE_LIMITS.get(tier, 100),
        'created': datetime.now(timezone.utc).isoformat(),
        'owner': owner,
        'active': True,
    }
    _save_api_keys(keys)

    return {'api_key': new_key, 'tier': tier, 'rate_limit': RATE_LIMITS.get(tier, 100)}


# ── Run ──

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000, log_level='info')
