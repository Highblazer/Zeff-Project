#!/usr/bin/env python3
"""
Public Performance Dashboard — Read-only proof of trading performance.

Shows: win rate, profit factor, Sharpe ratio, open positions (no balances).
Hosted on Cloudflare tunnel with a proper domain.
Acts as proof of performance for paid subscribers.

Run: streamlit run python/public_dashboard.py --server.port 8502
"""

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, '/root/.openclaw/workspace')

try:
    import streamlit as st
except ImportError:
    print("Install streamlit: pip install streamlit")
    sys.exit(1)

# ── Config ──
STATE_FILE = '/root/.openclaw/workspace/employees/trading_state.json'
SIGNAL_HISTORY = '/root/.openclaw/workspace/employees/signal_history.jsonl'
TRADE_HISTORY = '/root/.openclaw/workspace/employees/trade_history.jsonl'

st.set_page_config(
    page_title="OpenClaw — Live Trading Performance",
    page_icon="⬡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Custom CSS ──
st.markdown("""
<style>
    .main { background-color: #0a0a0f; }
    .stApp { background-color: #0a0a0f; }
    h1, h2, h3, h4 { color: #00e5ff !important; }
    .metric-card {
        background: linear-gradient(135deg, #111118 0%, #0d0d15 100%);
        border: 1px solid #1a1a2e;
        border-radius: 12px;
        padding: 20px;
        text-align: center;
    }
    .metric-value {
        font-size: 2.5em;
        font-weight: bold;
        color: #00e5ff;
    }
    .metric-label {
        color: #888;
        font-size: 0.9em;
        margin-top: 5px;
    }
    .position-card {
        background: #111118;
        border: 1px solid #1a1a2e;
        border-radius: 8px;
        padding: 12px;
        margin: 4px 0;
    }
    .win { color: #00ff88; }
    .loss { color: #ff4444; }
    .neutral { color: #888; }
    .live-badge {
        display: inline-block;
        background: #00ff88;
        color: #000;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 0.75em;
        font-weight: bold;
        animation: pulse 2s infinite;
    }
    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.6; }
    }
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=10)
def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


@st.cache_data(ttl=30)
def load_signal_history():
    signals = []
    try:
        with open(SIGNAL_HISTORY) as f:
            for line in f:
                if line.strip():
                    signals.append(json.loads(line))
    except FileNotFoundError:
        pass
    return signals[-100:]


@st.cache_data(ttl=60)
def load_trade_history():
    trades = []
    try:
        with open(TRADE_HISTORY) as f:
            for line in f:
                if line.strip():
                    trades.append(json.loads(line))
    except FileNotFoundError:
        pass
    return trades


# ── Load Data ──
state = load_state()
stats = state.get('stats', {})
positions = state.get('positions', {})
closed_trades = state.get('closed_trades', [])
connected = state.get('connected', False)
last_update = state.get('last_update', '')

# ── Header ──
col_title, col_status = st.columns([3, 1])
with col_title:
    st.markdown("# OpenClaw Trading Performance")
    st.markdown("*Live demo account — multi-timeframe momentum strategy*")
with col_status:
    if connected:
        st.markdown('<span class="live-badge">LIVE</span>', unsafe_allow_html=True)
    else:
        st.markdown("Disconnected", unsafe_allow_html=True)
    if last_update:
        try:
            dt = datetime.fromisoformat(last_update)
            st.caption(f"Updated: {dt.strftime('%H:%M:%S UTC')}")
        except Exception:
            st.caption(f"Updated: {last_update}")

st.divider()

# ── Performance Metrics ──
st.markdown("### Performance Metrics")
m1, m2, m3, m4, m5 = st.columns(5)

with m1:
    wr = stats.get('win_rate', 0)
    color = 'win' if wr >= 50 else 'loss' if wr < 40 else 'neutral'
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-value {color}">{wr}%</div>
        <div class="metric-label">Win Rate</div>
    </div>
    """, unsafe_allow_html=True)

with m2:
    pf = stats.get('profit_factor', 0)
    color = 'win' if pf >= 1.5 else 'loss' if pf < 1 else 'neutral'
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-value {color}">{pf:.2f}</div>
        <div class="metric-label">Profit Factor</div>
    </div>
    """, unsafe_allow_html=True)

with m3:
    sr = stats.get('sharpe_ratio', 0)
    color = 'win' if sr > 0.5 else 'loss' if sr < 0 else 'neutral'
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-value {color}">{sr:.2f}</div>
        <div class="metric-label">Sharpe Ratio</div>
    </div>
    """, unsafe_allow_html=True)

with m4:
    total = stats.get('total', 0)
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-value">{total}</div>
        <div class="metric-label">Total Trades</div>
    </div>
    """, unsafe_allow_html=True)

with m5:
    pnl = stats.get('total_pnl', 0)
    color = 'win' if pnl > 0 else 'loss' if pnl < 0 else 'neutral'
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-value {color}">${pnl:+.2f}</div>
        <div class="metric-label">Total P&L</div>
    </div>
    """, unsafe_allow_html=True)

st.divider()

# ── Open Positions ──
st.markdown(f"### Open Positions ({len(positions)})")

if positions:
    for key, pos in positions.items():
        sym = key.split('_')[0] if '_' in key else key
        direction = pos.get('direction', '?')
        entry = pos.get('entry_price', 0)
        sl = pos.get('stop_loss', 0)
        tp = pos.get('take_profit', 0)
        trail = pos.get('trail_phase', 'initial')

        dir_color = 'win' if direction == 'BUY' else 'loss'
        trail_badge = f' [{trail.upper()}]' if trail != 'initial' else ''

        st.markdown(f"""
        <div class="position-card">
            <strong class="{dir_color}">{direction}</strong> <strong>{sym}</strong>{trail_badge}
            &nbsp;|&nbsp; Entry: {entry:.5f}
            &nbsp;|&nbsp; SL: {sl:.5f}
            &nbsp;|&nbsp; TP: {tp:.5f if tp else 'Trailing'}
        </div>
        """, unsafe_allow_html=True)
else:
    st.info("No open positions")

st.divider()

# ── Recent Signals ──
st.markdown("### Recent Signals")
signals = load_signal_history()
if signals:
    recent = signals[-20:][::-1]
    for sig in recent:
        direction = sig.get('signal', '?')
        sym = sig.get('symbol', '?')
        score = sig.get('score', 0)
        layers = sig.get('layers', {})
        ts = sig.get('timestamp', '')

        dir_color = 'win' if direction == 'BUY' else 'loss'
        try:
            dt = datetime.fromisoformat(ts)
            time_str = dt.strftime('%H:%M')
        except Exception:
            time_str = ts[:16]

        st.markdown(f"""
        <div class="position-card">
            <span style="color:#666">{time_str}</span>
            &nbsp; <strong class="{dir_color}">{direction}</strong> <strong>{sym}</strong>
            &nbsp; Score: {score}/7
            (A:{layers.get('a',0)} B:{layers.get('b',0)} C:{layers.get('c',0)} N:{layers.get('news',0)})
        </div>
        """, unsafe_allow_html=True)
else:
    st.info("No signals recorded yet")

# ── Footer ──
st.divider()
st.markdown("""
<div style="text-align: center; color: #444; font-size: 0.8em;">
    OpenClaw Trading System — Demo Account<br>
    Past performance does not guarantee future results.
</div>
""", unsafe_allow_html=True)

# Auto-refresh
st.markdown("""
<script>
    setTimeout(function() { window.location.reload(); }, 30000);
</script>
""", unsafe_allow_html=True)
