#!/usr/bin/env python3
"""
AI World Order — Fleet Command Dashboard
Dark cyberpunk theme with hexagonal branding
"""

import streamlit as st
import json
import psutil
import os
import sys
import glob
from datetime import datetime, timezone

sys.path.insert(0, '/root/.openclaw/workspace')
from lib.task_dispatch import create_task

try:
    import yfinance as yf
    YF_AVAILABLE = True
except ImportError:
    YF_AVAILABLE = False

st.set_page_config(
    page_title="AI World Order",
    page_icon="⬡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ══════════════════════════════════════════════════════════════
#  LOGO + CSS
# ══════════════════════════════════════════════════════════════

AWO_LOGO = """
<svg viewBox="0 0 400 120" xmlns="http://www.w3.org/2000/svg" style="width:320px;height:96px;">
  <!-- Hexagonal icon -->
  <g transform="translate(50,60)">
    <!-- Outer hex -->
    <polygon points="0,-38 33,-19 33,19 0,38 -33,19 -33,-19"
             fill="none" stroke="#00e5ff" stroke-width="2.5" opacity="0.9"/>
    <!-- Inner hex -->
    <polygon points="0,-24 21,-12 21,12 0,24 -21,12 -21,-12"
             fill="none" stroke="#00e5ff" stroke-width="1.5" opacity="0.5"/>
    <!-- Center eye / node -->
    <circle cx="0" cy="0" r="6" fill="#00e5ff" opacity="0.8"/>
    <circle cx="0" cy="0" r="3" fill="#0a0f1e"/>
    <!-- Connection lines radiating out -->
    <line x1="0" y1="-24" x2="0" y2="-38" stroke="#00e5ff" stroke-width="1" opacity="0.4"/>
    <line x1="21" y1="-12" x2="33" y2="-19" stroke="#00e5ff" stroke-width="1" opacity="0.4"/>
    <line x1="21" y1="12" x2="33" y2="19" stroke="#00e5ff" stroke-width="1" opacity="0.4"/>
    <line x1="0" y1="24" x2="0" y2="38" stroke="#00e5ff" stroke-width="1" opacity="0.4"/>
    <line x1="-21" y1="12" x2="-33" y2="19" stroke="#00e5ff" stroke-width="1" opacity="0.4"/>
    <line x1="-21" y1="-12" x2="-33" y2="-19" stroke="#00e5ff" stroke-width="1" opacity="0.4"/>
    <!-- Orbital dots -->
    <circle cx="0" cy="-38" r="2.5" fill="#00e5ff" opacity="0.6"/>
    <circle cx="33" cy="-19" r="2.5" fill="#00e5ff" opacity="0.6"/>
    <circle cx="33" cy="19" r="2.5" fill="#00e5ff" opacity="0.6"/>
    <circle cx="0" cy="38" r="2.5" fill="#00e5ff" opacity="0.6"/>
    <circle cx="-33" cy="19" r="2.5" fill="#00e5ff" opacity="0.6"/>
    <circle cx="-33" cy="-19" r="2.5" fill="#00e5ff" opacity="0.6"/>
  </g>
  <!-- Text -->
  <text x="100" y="48" fill="#00e5ff" font-family="'Segoe UI','Helvetica Neue',sans-serif"
        font-size="28" font-weight="700" letter-spacing="3">AI WORLD ORDER</text>
  <text x="100" y="72" fill="#5a7a8a" font-family="'Segoe UI','Helvetica Neue',sans-serif"
        font-size="11" letter-spacing="6" font-weight="400">AUTONOMOUS FLEET COMMAND</text>
</svg>
"""

st.markdown(f"""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

    :root {{
        --bg-primary: #0a0f1e;
        --bg-card: rgba(12,18,36,0.92);
        --bg-card-hover: rgba(16,24,48,0.95);
        --border: rgba(0,229,255,0.15);
        --border-hover: rgba(0,229,255,0.35);
        --cyan: #00e5ff;
        --cyan-dim: rgba(0,229,255,0.6);
        --cyan-glow: rgba(0,229,255,0.08);
        --green: #00e676;
        --red: #ff5252;
        --amber: #ffc107;
        --text-primary: #e0e8f0;
        --text-secondary: #5a7a8a;
        --text-muted: #3a4a5a;
    }}

    .stApp {{
        background: var(--bg-primary);
        color: var(--text-primary);
        font-family: 'Inter', -apple-system, sans-serif;
    }}
    .stApp > div {{ position: relative; z-index: 1; }}

    /* Global text */
    h1, h2, h3, h4, h5, h6 {{
        color: var(--cyan) !important;
        font-family: 'Inter', sans-serif !important;
        font-weight: 600 !important;
        letter-spacing: 0.5px;
    }}
    p, div, span, label {{ color: var(--text-primary) !important; }}
    a {{ color: var(--cyan) !important; }}

    /* Hide sidebar and header */
    [data-testid="stSidebar"] {{ display: none; }}
    header[data-testid="stHeader"] {{ background: transparent !important; }}

    /* Metrics */
    [data-testid="stMetric"] {{
        background: var(--bg-card) !important;
        border: 1px solid var(--border) !important;
        border-radius: 10px !important;
        padding: 16px 18px !important;
        backdrop-filter: blur(8px);
    }}
    [data-testid="stMetricLabel"] {{ color: var(--text-secondary) !important; font-size: 11px !important; letter-spacing: 1.5px; text-transform: uppercase; }}
    [data-testid="stMetricValue"] {{ color: var(--cyan) !important; font-family: 'JetBrains Mono', monospace !important; font-weight: 600 !important; }}
    [data-testid="stMetricDelta"] svg {{ display: none; }}

    /* Buttons */
    .stButton > button {{
        background: transparent !important;
        color: var(--cyan) !important;
        border: 1px solid var(--border) !important;
        border-radius: 6px !important;
        font-family: 'Inter', sans-serif !important;
        font-weight: 500 !important;
        font-size: 12px !important;
        letter-spacing: 0.5px;
        transition: all 0.2s;
    }}
    .stButton > button:hover {{
        border-color: var(--cyan) !important;
        background: var(--cyan-glow) !important;
        box-shadow: 0 0 15px rgba(0,229,255,0.15);
    }}

    /* Kill button */
    .kill-btn > button {{
        background: rgba(255,82,82,0.1) !important;
        color: var(--red) !important;
        border-color: rgba(255,82,82,0.3) !important;
    }}
    .kill-btn > button:hover {{
        background: rgba(255,82,82,0.2) !important;
        border-color: var(--red) !important;
        box-shadow: 0 0 15px rgba(255,82,82,0.2);
    }}

    /* Cards */
    .awo-card {{
        background: var(--bg-card);
        border: 1px solid var(--border);
        border-radius: 10px;
        padding: 18px 20px;
        margin: 8px 0;
        backdrop-filter: blur(8px);
        transition: border-color 0.25s, box-shadow 0.25s;
    }}
    .awo-card:hover {{
        border-color: var(--border-hover);
        box-shadow: 0 0 20px var(--cyan-glow);
    }}
    .awo-card .card-title {{
        font-size: 13px;
        font-weight: 600;
        color: var(--cyan) !important;
        letter-spacing: 0.5px;
        margin-bottom: 6px;
    }}
    .awo-card .card-subtitle {{
        font-size: 11px;
        color: var(--text-secondary) !important;
    }}
    .awo-card .card-body {{
        font-size: 13px;
        color: var(--text-primary) !important;
        line-height: 1.6;
    }}

    /* Status badges */
    .badge {{
        display: inline-block;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 10px;
        font-weight: 600;
        letter-spacing: 1px;
        text-transform: uppercase;
    }}
    .badge-online {{ background: rgba(0,230,118,0.12); color: var(--green) !important; border: 1px solid rgba(0,230,118,0.25); }}
    .badge-offline {{ background: rgba(255,82,82,0.12); color: var(--red) !important; border: 1px solid rgba(255,82,82,0.25); }}
    .badge-idle {{ background: rgba(255,193,7,0.12); color: var(--amber) !important; border: 1px solid rgba(255,193,7,0.25); }}
    .badge-demo {{ background: rgba(0,229,255,0.1); color: var(--cyan) !important; border: 1px solid var(--border); }}

    /* Price grid */
    .pgrid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(195px, 1fr)); gap: 10px; margin: 12px 0; }}
    .pcell {{
        background: var(--bg-card);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 14px 16px;
        transition: border-color 0.2s;
    }}
    .pcell:hover {{ border-color: var(--border-hover); }}
    .pcell .psym {{ font-size: 11px; font-weight: 600; color: var(--text-secondary) !important; letter-spacing: 1.5px; }}
    .pcell .pprice {{ font-size: 20px; font-weight: 600; font-family: 'JetBrains Mono', monospace; margin: 4px 0 2px 0; }}
    .pcell .pchg {{ font-size: 11px; font-family: 'JetBrains Mono', monospace; }}
    .c-up {{ color: var(--green) !important; }}
    .c-dn {{ color: var(--red) !important; }}
    .c-fl {{ color: var(--text-muted) !important; }}

    /* Position table */
    .pos-row {{
        display: grid;
        grid-template-columns: 100px 60px 110px 110px 90px 90px 80px 90px;
        gap: 8px;
        align-items: center;
        padding: 10px 16px;
        border-bottom: 1px solid rgba(0,229,255,0.06);
        font-size: 12px;
        font-family: 'JetBrains Mono', monospace;
    }}
    .pos-row:hover {{ background: rgba(0,229,255,0.03); }}
    .pos-header {{
        font-family: 'Inter', sans-serif;
        font-size: 10px;
        font-weight: 600;
        color: var(--text-secondary) !important;
        letter-spacing: 1.2px;
        text-transform: uppercase;
        border-bottom: 1px solid var(--border);
    }}
    .pos-header span {{ color: var(--text-secondary) !important; }}

    /* Dividers */
    hr {{ border-color: var(--border) !important; opacity: 0.4; }}

    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {{ gap: 0; background: transparent; }}
    .stTabs [data-baseweb="tab"] {{
        color: var(--text-secondary) !important;
        background: transparent !important;
        border: none !important;
        border-bottom: 2px solid transparent !important;
        font-family: 'Inter', sans-serif !important;
        font-size: 12px !important;
        font-weight: 600 !important;
        letter-spacing: 1.5px !important;
        padding: 10px 24px !important;
        text-transform: uppercase;
    }}
    .stTabs [aria-selected="true"] {{
        color: var(--cyan) !important;
        border-bottom: 2px solid var(--cyan) !important;
    }}
    .stTabs [data-baseweb="tab-panel"] {{ padding-top: 20px; }}

    /* Section headers */
    .section-hdr {{
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 2px;
        color: var(--text-secondary) !important;
        text-transform: uppercase;
        margin: 24px 0 12px 0;
        padding-bottom: 8px;
        border-bottom: 1px solid var(--border);
    }}

    /* Logo area */
    .logo-bar {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 8px 0 20px 0;
        border-bottom: 1px solid var(--border);
        margin-bottom: 20px;
    }}
    .logo-bar .meta {{
        font-family: 'JetBrains Mono', monospace;
        font-size: 11px;
        color: var(--text-secondary) !important;
        text-align: right;
        line-height: 1.8;
    }}

    /* Selectbox / form inputs */
    .stSelectbox > div > div {{ background: var(--bg-card) !important; border-color: var(--border) !important; color: var(--text-primary) !important; }}
    .stTextInput > div > div > input {{ background: var(--bg-card) !important; border-color: var(--border) !important; color: var(--text-primary) !important; font-family: 'JetBrains Mono', monospace !important; }}
    .stSlider > div {{ color: var(--text-primary) !important; }}

    /* Info/success/error boxes */
    .stAlert {{ background: var(--bg-card) !important; border-left: 3px solid var(--cyan) !important; color: var(--text-primary) !important; }}

    /* Scrollbar */
    ::-webkit-scrollbar {{ width: 6px; }}
    ::-webkit-scrollbar-track {{ background: var(--bg-primary); }}
    ::-webkit-scrollbar-thumb {{ background: rgba(0,229,255,0.2); border-radius: 3px; }}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
#  DATA LOADING
# ══════════════════════════════════════════════════════════════

STATE_FILE = '/root/.openclaw/workspace/employees/trading_state.json'
PREV_PRICES_FILE = '/root/.openclaw/workspace/employees/.prev_prices.json'
TASKS_ROOT = '/root/.openclaw/workspace/tasks'
KILL_SWITCH_PATH = '/root/.openclaw/workspace/STOP_TRADING'

def _load_json(path, default=None):
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}

def get_uptime():
    try:
        secs = float(open('/proc/uptime').read().split()[0])
        d, rem = divmod(int(secs), 86400)
        h, rem = divmod(rem, 3600)
        m, _ = divmod(rem, 60)
        return f"{d}d {h}h {m}m"
    except Exception:
        return "—"

def get_sys():
    try:
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        net = psutil.net_io_counters()
        hrs = float(open('/proc/uptime').read().split()[0]) / 3600
        procs = len(psutil.pids())
        return {
            'cpu': cpu, 'memory': mem.percent, 'mem_used_gb': mem.used / (1024**3),
            'mem_total_gb': mem.total / (1024**3), 'disk': disk.percent,
            'disk_used_gb': disk.used / (1024**3), 'disk_total_gb': disk.total / (1024**3),
            'uptime': get_uptime(), 'cost': hrs * 0.02,
            'net_sent_mb': net.bytes_sent / (1024**2), 'net_recv_mb': net.bytes_recv / (1024**2),
            'processes': procs,
        }
    except Exception:
        return {'cpu': 0, 'memory': 0, 'disk': 0, 'uptime': '—', 'cost': 0, 'processes': 0,
                'mem_used_gb': 0, 'mem_total_gb': 0, 'disk_used_gb': 0, 'disk_total_gb': 0,
                'net_sent_mb': 0, 'net_recv_mb': 0}

@st.cache_data(ttl=30)
def get_live_prices():
    prices = {}
    if not YF_AVAILABLE:
        return prices
    symbols = {
        'EURUSD': 'EURUSD=X', 'GBPUSD': 'GBPUSD=X', 'USDJPY': 'USDJPY=X',
        'AUDUSD': 'AUDUSD=X', 'USDCAD': 'USDCAD=X', 'USDCHF': 'USDCHF=X',
        'NZDUSD': 'NZDUSD=X', 'XAUUSD': 'GC=F', 'XAGUSD': 'SI=F', 'BTCUSD': 'BTC-USD',
    }
    for sym, yahoo in symbols.items():
        try:
            t = yf.Ticker(yahoo)
            info = t.info
            p = info.get('regularMarketPrice')
            prev = info.get('regularMarketPreviousClose') or info.get('previousClose')
            if p:
                prices[sym] = {'price': p, 'prev_close': prev or p}
        except Exception:
            pass
    return prices

def load_prev_prices():
    return _load_json(PREV_PRICES_FILE, {})

def save_prev_prices(p):
    try:
        with open(PREV_PRICES_FILE, 'w') as f:
            json.dump(p, f)
    except Exception:
        pass

def calc_pnl(entry, current, direction, lot_size):
    if not entry or not lot_size:
        return 0.0
    mult = 100000
    if direction == 'BUY':
        return (current - entry) * lot_size * mult
    return (entry - current) * lot_size * mult

def load_state():
    for path in [STATE_FILE, '/root/.openclaw/workspace/employees/paper-trading-state.json']:
        data = _load_json(path)
        if data and (data.get('positions') or data.get('balance', 0) > 0):
            return data
    return {'balance': 0, 'positions': {}, 'stats': {}, 'mode': 'demo', 'connected': False}

def load_trading_status():
    return _load_json('/root/.openclaw/workspace/employees/trading_status.json',
                      {'balance': 0, 'connected': False, 'mode': 'demo'})

def count_tasks():
    counts = {}
    for s in ['pending', 'in_progress', 'completed', 'failed']:
        d = os.path.join(TASKS_ROOT, s)
        try:
            counts[s] = len([f for f in os.listdir(d) if f.endswith('.json')])
        except OSError:
            counts[s] = 0
    return counts

def load_tasks(status_filter='all', limit=30):
    dirs = ['pending', 'in_progress', 'completed', 'failed'] if status_filter == 'all' else [status_filter]
    tasks = []
    for d in dirs:
        p = os.path.join(TASKS_ROOT, d)
        if not os.path.isdir(p):
            continue
        for fn in os.listdir(p):
            if fn.endswith('.json'):
                t = _load_json(os.path.join(p, fn))
                if t:
                    tasks.append(t)
    tasks.sort(key=lambda t: t.get('created_at', ''), reverse=True)
    return tasks[:limit]

def is_kill_switch_active():
    return os.path.exists(KILL_SWITCH_PATH)

def get_lobster_workflows():
    wf_dir = '/root/.openclaw/workspace/workflows'
    workflows = []
    for f in glob.glob(os.path.join(wf_dir, '*.yaml')) + glob.glob(os.path.join(wf_dir, '*.json')):
        workflows.append(os.path.basename(f))
    return workflows

def get_installed_skills():
    skills_dir = '/root/.openclaw/workspace/skills'
    skills = []
    if os.path.isdir(skills_dir):
        for d in os.listdir(skills_dir):
            skill_md = os.path.join(skills_dir, d, 'SKILL.md')
            if os.path.isfile(skill_md):
                skills.append(d)
    return sorted(skills)


# ══════════════════════════════════════════════════════════════
#  LOAD ALL DATA
# ══════════════════════════════════════════════════════════════

ts = load_trading_status()
state = load_state()
if ts.get('connected'):
    state['connected'] = True
if not state.get('balance'):
    state['balance'] = ts.get('balance', 0)
state['mode'] = state.get('mode', ts.get('mode', 'demo'))

try:
    last = datetime.fromisoformat(state.get('last_update', '2000-01-01'))
    state['connected'] = (datetime.now() - last).total_seconds() < 120
except Exception:
    state['connected'] = False

price_data = get_live_prices()
prices = {s: d['price'] for s, d in price_data.items()}
prev_closes = {s: d['prev_close'] for s, d in price_data.items()}
prev_tick = load_prev_prices()
save_prev_prices(prices)

sys_stats = get_sys()
positions = state.get('positions', {})
stats = state.get('stats', {})
config = _load_json('/root/.openclaw/workspace/employees/paper-trading-config.json',
                    {'initial_balance': 200})
starting_balance = config.get('initial_balance', 200)
balance = state.get('balance', 0)
total_pnl = sum(calc_pnl(
    p.get('entry_price', p.get('entry', 0)),
    prices.get(s, p.get('entry_price', p.get('entry', 0))),
    p.get('direction', 'BUY'),
    p.get('lot_size', p.get('volume', 0))
) for s, p in positions.items())
realized_pnl = stats.get('total_pnl', 0)
account_return = ((balance - starting_balance) / starting_balance * 100) if starting_balance else 0

natalia_status = _load_json('/root/.openclaw/workspace/employees/natalia_status.json')
kalshi_status = _load_json('/root/.openclaw/workspace/employees/kalshi_status.json')
kalshi_paper = _load_json('/root/.openclaw/workspace/employees/kalshi_paper_status.json')
task_counts = count_tasks()
kill_active = is_kill_switch_active()
workflows = get_lobster_workflows()
skills = get_installed_skills()

# Natalia liveness
natalia_live = False
try:
    hb = datetime.fromisoformat(natalia_status.get('last_heartbeat', '2000-01-01').replace('Z', '+00:00').replace('+00:00', ''))
    natalia_live = (datetime.now() - hb).total_seconds() < 120
except Exception:
    pass


# ══════════════════════════════════════════════════════════════
#  HEADER
# ══════════════════════════════════════════════════════════════

now = datetime.now()
utc_now = datetime.now(timezone.utc)

st.markdown(f"""
<div class="logo-bar">
    <div>{AWO_LOGO}</div>
    <div class="meta">
        {now.strftime('%Y-%m-%d %H:%M:%S')} LOCAL<br>
        {utc_now.strftime('%H:%M:%S')} UTC<br>
        UPTIME {sys_stats['uptime']}<br>
        <a href="http://62.171.152.37:8502" target="_blank"
           style="color:#00e5ff;text-decoration:none;border:1px solid rgba(0,229,255,0.35);
                  padding:4px 14px;border-radius:4px;font-size:11px;font-weight:600;
                  letter-spacing:1.5px;margin-top:4px;display:inline-block;">NEWS INTEL &rarr;</a>
    </div>
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
#  TABS
# ══════════════════════════════════════════════════════════════

tab_home, tab_trading, tab_research, tab_tasks, tab_system = st.tabs([
    "OVERVIEW", "TRADING", "RESEARCH", "TASKS", "SYSTEM"
])


# ══════════════════════════════════════════════════════════════
#  TAB: OVERVIEW
# ══════════════════════════════════════════════════════════════

with tab_home:

    # ── Key Metrics Row ──
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    conn_icon = "ONLINE" if state.get('connected') else "OFFLINE"
    with m1:
        st.metric("BALANCE", f"${balance:,.2f}",
                  delta=f"{account_return:+.1f}%" if account_return != 0 else None)
    with m2:
        st.metric("UNREALIZED P&L", f"${total_pnl:+,.2f}")
    with m3:
        st.metric("REALIZED P&L", f"${realized_pnl:+,.2f}")
    with m4:
        st.metric("OPEN POSITIONS", f"{len(positions)}")
    with m5:
        win_rate = stats.get('win_rate', 0)
        total_trades = stats.get('total', 0)
        st.metric("WIN RATE", f"{win_rate:.0f}%" if total_trades else "—",
                  delta=f"{total_trades} trades" if total_trades else None)
    with m6:
        st.metric("BROKER", conn_icon)

    # ── Kill switch alert ──
    if kill_active:
        st.markdown("""
        <div class="awo-card" style="border-color:rgba(255,82,82,0.5);background:rgba(255,82,82,0.08);">
            <div class="card-title" style="color:#ff5252 !important;">KILL SWITCH ACTIVE</div>
            <div class="card-body" style="color:#ff8a80 !important;">All trading has been halted. Remove the kill switch to resume operations.</div>
        </div>""", unsafe_allow_html=True)

    # ── Fleet Status ──
    st.markdown('<div class="section-hdr">Fleet Status</div>', unsafe_allow_html=True)

    f1, f2, f3 = st.columns(3)
    with f1:
        badge = 'badge-online' if state.get('connected') else 'badge-offline'
        status = 'ONLINE' if state.get('connected') else 'OFFLINE'
        st.markdown(f"""
        <div class="awo-card">
            <div class="card-title">001 ZEFF.BOT <span class="badge badge-online">ONLINE</span></div>
            <div class="card-subtitle">Chief Executive Officer</div>
            <div class="card-body" style="margin-top:8px;">
                Gateway: port 18789<br>
                Channel: Telegram<br>
                Model: MiniMax M2.5
            </div>
        </div>""", unsafe_allow_html=True)

    with f2:
        tb_badge = 'badge-online' if state.get('connected') else 'badge-offline'
        tb_status = 'ONLINE' if state.get('connected') else 'OFFLINE'
        st.markdown(f"""
        <div class="awo-card">
            <div class="card-title">002 TRADEBOT <span class="badge {tb_badge}">{tb_status}</span></div>
            <div class="card-subtitle">Conservative Multi-Market Trading</div>
            <div class="card-body" style="margin-top:8px;">
                Positions: {len(positions)} | Mode: {state.get('mode','demo').upper()}<br>
                Balance: ${balance:,.2f}<br>
                Strategy: FVG + S/R + EMA + Fib
            </div>
        </div>""", unsafe_allow_html=True)

    with f3:
        nat_badge = 'badge-online' if natalia_live else ('badge-idle' if natalia_status.get('status') == 'idle' else 'badge-offline')
        nat_status_text = 'ONLINE' if natalia_live else natalia_status.get('status', 'OFFLINE').upper()
        brave_str = "Brave API" if natalia_status.get('brave_api') else "DuckDuckGo (fallback)"
        st.markdown(f"""
        <div class="awo-card">
            <div class="card-title">004 NATALIA <span class="badge {nat_badge}">{nat_status_text}</span></div>
            <div class="card-subtitle">Chief Research Officer</div>
            <div class="card-body" style="margin-top:8px;">
                Task: {natalia_status.get('current_task') or 'Idle'}<br>
                Search: {brave_str}<br>
                PID: {natalia_status.get('pid', '—')}
            </div>
        </div>""", unsafe_allow_html=True)

    # ── Live Prices ──
    st.markdown('<div class="section-hdr">Live Market Prices</div>', unsafe_allow_html=True)

    if prices:
        html = '<div class="pgrid">'
        for sym in prices:
            p = prices[sym]
            pc = prev_closes.get(sym, p)
            pt = prev_tick.get(sym, p)
            dchg = p - pc
            dpct = (dchg / pc * 100) if pc else 0

            if p > pt: d_cls, arrow = 'c-up', '&#9650;'
            elif p < pt: d_cls, arrow = 'c-dn', '&#9660;'
            else: d_cls, arrow = 'c-fl', '&#9679;'

            dc_cls = 'c-up' if dchg > 0 else ('c-dn' if dchg < 0 else 'c-fl')
            sign = '+' if dchg > 0 else ''

            if p >= 1000: pfmt = f"{p:,.2f}"
            elif p >= 10: pfmt = f"{p:.3f}"
            else: pfmt = f"{p:.5f}"

            cfmt = f"{sign}{dchg:.5f}" if abs(dchg) < 1 else f"{sign}{dchg:,.2f}"

            # Check if we have an open position
            pos_indicator = ''
            if sym in positions:
                pos_dir = positions[sym].get('direction', '')
                pos_indicator = f'<span style="font-size:9px;color:var(--cyan);opacity:0.7;float:right;">{pos_dir}</span>'

            html += f'''<div class="pcell">
                <div class="psym">{sym}{pos_indicator}</div>
                <div class="pprice {d_cls}">{arrow} {pfmt}</div>
                <div class="pchg {dc_cls}">{cfmt} ({sign}{dpct:.2f}%)</div>
            </div>'''
        html += '</div>'
        st.markdown(html, unsafe_allow_html=True)
    else:
        st.info("Waiting for price data...")

    # ── Open Positions ──
    st.markdown('<div class="section-hdr">Open Positions</div>', unsafe_allow_html=True)

    if positions:
        # Header row
        st.markdown("""<div class="awo-card" style="padding:0;overflow:hidden;">
        <div class="pos-row pos-header">
            <span>SYMBOL</span><span>SIDE</span><span>ENTRY</span>
            <span>CURRENT</span><span>SL</span><span>TP</span>
            <span>LOT</span><span>P&L</span>
        </div>""", unsafe_allow_html=True)

        rows_html = ""
        for sym, pos in positions.items():
            d = pos.get('direction', '?')
            entry = pos.get('entry_price', pos.get('entry', 0))
            current = prices.get(sym, entry)
            sl = pos.get('stop_loss', 0)
            tp = pos.get('take_profit', 0)
            lot = pos.get('lot_size', pos.get('volume', 0))
            pnl = calc_pnl(entry, current, d, lot)

            pnl_cls = 'c-up' if pnl >= 0 else 'c-dn'
            side_cls = 'c-up' if d == 'BUY' else 'c-dn'

            rows_html += f"""<div class="pos-row">
                <span style="font-weight:600;">{sym}</span>
                <span class="{side_cls}">{d}</span>
                <span>{entry:.5f}</span>
                <span>{current:.5f}</span>
                <span>{sl:.5f}</span>
                <span>{tp:.5f}</span>
                <span>{lot:.2f}</span>
                <span class="{pnl_cls}" style="font-weight:600;">${pnl:+.2f}</span>
            </div>"""

        st.markdown(rows_html + "</div>", unsafe_allow_html=True)
    else:
        st.markdown("""<div class="awo-card">
            <div class="card-body" style="color:var(--text-secondary) !important;text-align:center;">No open positions</div>
        </div>""", unsafe_allow_html=True)

    # ── Kalshi + Task Summary side by side ──
    st.markdown('<div class="section-hdr">Markets & Operations</div>', unsafe_allow_html=True)
    k1, k2, k3 = st.columns(3)

    with k1:
        k_connected = kalshi_status.get('connected', False)
        k_badge = 'badge-online' if k_connected else 'badge-offline'
        st.markdown(f"""
        <div class="awo-card">
            <div class="card-title">KALSHI <span class="badge {k_badge}">{'LIVE' if k_connected else 'OFF'}</span></div>
            <div class="card-body">
                Mode: {kalshi_status.get('mode', '—')}<br>
                Markets tracked: {kalshi_status.get('markets', 0)}<br>
                Paper balance: ${kalshi_paper.get('balance', 0):.2f}<br>
                Trades: {kalshi_paper.get('trades_count', 0)} ({kalshi_paper.get('wins', 0)}W / {kalshi_paper.get('losses', 0)}L)
            </div>
        </div>""", unsafe_allow_html=True)

    with k2:
        total_tasks = sum(task_counts.values())
        st.markdown(f"""
        <div class="awo-card">
            <div class="card-title">TASK DISPATCH</div>
            <div class="card-body">
                Pending: {task_counts.get('pending', 0)}<br>
                In Progress: {task_counts.get('in_progress', 0)}<br>
                Completed: {task_counts.get('completed', 0)}<br>
                Failed: {task_counts.get('failed', 0)}<br>
                Total: {total_tasks}
            </div>
        </div>""", unsafe_allow_html=True)

    with k3:
        st.markdown(f"""
        <div class="awo-card">
            <div class="card-title">LOBSTER WORKFLOWS</div>
            <div class="card-body">
                {"<br>".join(f"&#8226; {w}" for w in workflows) if workflows else "No workflows installed"}<br><br>
                Skills: {', '.join(skills) if skills else '—'}
            </div>
        </div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
#  TAB: TRADING
# ══════════════════════════════════════════════════════════════

with tab_trading:

    # ── Account Overview ──
    t1, t2, t3, t4, t5, t6 = st.columns(6)
    with t1: st.metric("BALANCE", f"${balance:,.2f}")
    with t2: st.metric("STARTING", f"${starting_balance:,.2f}")
    with t3: st.metric("RETURN", f"{account_return:+.1f}%")
    with t4: st.metric("UNREALIZED", f"${total_pnl:+,.2f}")
    with t5: st.metric("REALIZED", f"${realized_pnl:+,.2f}")
    with t6:
        drawdown = ((starting_balance - balance) / starting_balance * 100) if starting_balance else 0
        st.metric("DRAWDOWN", f"{drawdown:.1f}%")

    # ── Trade Stats ──
    st.markdown('<div class="section-hdr">Performance</div>', unsafe_allow_html=True)
    s1, s2, s3, s4, s5, s6 = st.columns(6)
    with s1: st.metric("TOTAL TRADES", stats.get('total', 0))
    with s2: st.metric("WINS", stats.get('wins', 0))
    with s3: st.metric("LOSSES", stats.get('losses', 0))
    with s4: st.metric("WIN RATE", f"{stats.get('win_rate', 0):.0f}%")
    with s5: st.metric("OPEN", len(positions))
    with s6:
        mode_str = state.get('mode', 'demo').upper()
        st.metric("MODE", mode_str)

    # ── Kill Switch ──
    st.markdown('<div class="section-hdr">Risk Controls</div>', unsafe_allow_html=True)
    rc1, rc2, rc3, rc4 = st.columns(4)
    with rc1:
        if kill_active:
            st.markdown('<span class="badge badge-offline" style="font-size:14px;padding:6px 16px;">KILL SWITCH: ACTIVE</span>', unsafe_allow_html=True)
            if st.button("DEACTIVATE KILL SWITCH"):
                os.remove(KILL_SWITCH_PATH)
                st.rerun()
        else:
            st.markdown('<span class="badge badge-online" style="font-size:14px;padding:6px 16px;">KILL SWITCH: OFF</span>', unsafe_allow_html=True)
            with st.container():
                st.markdown('<div class="kill-btn">', unsafe_allow_html=True)
                if st.button("ACTIVATE KILL SWITCH"):
                    with open(KILL_SWITCH_PATH, 'w') as f:
                        json.dump({'activated': datetime.now(timezone.utc).isoformat(), 'reason': 'Dashboard'}, f)
                    st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)

    with rc2:
        st.markdown(f"""
        <div class="awo-card">
            <div class="card-title">RISK LIMITS</div>
            <div class="card-body">
                Max risk/trade: 2%<br>
                Max daily DD: 10%<br>
                Max positions: 3<br>
                Min balance: $10
            </div>
        </div>""", unsafe_allow_html=True)

    with rc3:
        st.markdown(f"""
        <div class="awo-card">
            <div class="card-title">STRATEGY</div>
            <div class="card-body">
                FVG + S/R Confirmation<br>
                EMA 20/50 Trend<br>
                Fibonacci Levels<br>
                Breakout Detection
            </div>
        </div>""", unsafe_allow_html=True)

    with rc4:
        st.markdown(f"""
        <div class="awo-card">
            <div class="card-title">BROKER</div>
            <div class="card-body">
                IC Markets cTrader<br>
                Mode: DEMO<br>
                Connected: {'Yes' if state.get('connected') else 'No'}<br>
                Account: ****{str(ts.get('account', ''))[-4:]}
            </div>
        </div>""", unsafe_allow_html=True)

    # ── Positions table ──
    st.markdown('<div class="section-hdr">Open Positions</div>', unsafe_allow_html=True)

    if positions:
        for sym, pos in positions.items():
            d = pos.get('direction', '?')
            entry = pos.get('entry_price', pos.get('entry', 0))
            current = prices.get(sym, entry)
            sl = pos.get('stop_loss', 0)
            tp = pos.get('take_profit', 0)
            lot = pos.get('lot_size', pos.get('volume', 0))
            pnl = calc_pnl(entry, current, d, lot)
            opened = pos.get('open_time', '—')[:19]

            pnl_cls = 'c-up' if pnl >= 0 else 'c-dn'
            side_emoji = '&#9650;' if d == 'BUY' else '&#9660;'
            side_cls = 'c-up' if d == 'BUY' else 'c-dn'

            # Distance to SL/TP in pips
            pip_mult = 100 if 'JPY' in sym else 10000
            sl_dist = abs(current - sl) * pip_mult
            tp_dist = abs(tp - current) * pip_mult

            c1, c2 = st.columns([5, 1])
            with c1:
                st.markdown(f"""
                <div class="awo-card">
                    <div class="card-title">
                        <span class="{side_cls}">{side_emoji} {d}</span> {sym}
                        <span style="float:right;" class="{pnl_cls}">${pnl:+.2f}</span>
                    </div>
                    <div class="card-body" style="font-family:'JetBrains Mono',monospace;font-size:12px;">
                        Entry: {entry:.5f} &nbsp;|&nbsp; Current: {current:.5f} &nbsp;|&nbsp;
                        SL: {sl:.5f} ({sl_dist:.0f} pips) &nbsp;|&nbsp;
                        TP: {tp:.5f} ({tp_dist:.0f} pips) &nbsp;|&nbsp;
                        Lot: {lot:.2f} &nbsp;|&nbsp; Opened: {opened}
                    </div>
                </div>""", unsafe_allow_html=True)
            with c2:
                if st.button("CLOSE", key=f"tc_{sym}"):
                    pos_id = pos.get('positionId')
                    try:
                        create_task(
                            title=f'Close {sym} position',
                            assigned_to='tradebot',
                            task_type='close_position',
                            params={'symbol': sym, 'positionId': pos_id},
                            priority=1,
                            created_by='dashboard',
                        )
                        st.toast(f'Close order dispatched for {sym} (posId={pos_id})')
                    except Exception as e:
                        st.error(f'Failed to dispatch close: {e}')
                    st.rerun()
    else:
        st.info("No open positions")

    # ── Market Prices ──
    st.markdown('<div class="section-hdr">Market Prices</div>', unsafe_allow_html=True)
    if prices:
        html = '<div class="pgrid">'
        for sym in prices:
            p = prices[sym]
            pc = prev_closes.get(sym, p)
            pt = prev_tick.get(sym, p)
            dchg = p - pc
            dpct = (dchg / pc * 100) if pc else 0
            if p > pt: d_cls, arrow = 'c-up', '&#9650;'
            elif p < pt: d_cls, arrow = 'c-dn', '&#9660;'
            else: d_cls, arrow = 'c-fl', '&#9679;'
            dc_cls = 'c-up' if dchg > 0 else ('c-dn' if dchg < 0 else 'c-fl')
            sign = '+' if dchg > 0 else ''
            pfmt = f"{p:,.2f}" if p >= 1000 else (f"{p:.3f}" if p >= 10 else f"{p:.5f}")
            cfmt = f"{sign}{dchg:.5f}" if abs(dchg) < 1 else f"{sign}{dchg:,.2f}"
            html += f'<div class="pcell"><div class="psym">{sym}</div><div class="pprice {d_cls}">{arrow} {pfmt}</div><div class="pchg {dc_cls}">{cfmt} ({sign}{dpct:.2f}%)</div></div>'
        html += '</div>'
        st.markdown(html, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
#  TAB: RESEARCH
# ══════════════════════════════════════════════════════════════

with tab_research:

    r1, r2, r3, r4 = st.columns(4)
    with r1:
        nat_s = 'ONLINE' if natalia_live else natalia_status.get('status', 'OFFLINE').upper()
        st.metric("NATALIA", nat_s)
    with r2:
        st.metric("BRAVE API", "Active" if natalia_status.get('brave_api') else "Inactive")
    with r3:
        st.metric("SKILLS", len(skills))
    with r4:
        st.metric("TASKS DONE", task_counts.get('completed', 0))

    # ── Installed Skills ──
    st.markdown('<div class="section-hdr">Installed Skills</div>', unsafe_allow_html=True)

    # Read skill descriptions
    skills_detail = []
    for sk in skills:
        md_path = f'/root/.openclaw/workspace/skills/{sk}/SKILL.md'
        desc = '—'
        try:
            with open(md_path) as f:
                content = f.read()
            for line in content.split('\n'):
                if line.startswith('description:'):
                    desc = line.split(':', 1)[1].strip().strip('"\'')[:120]
                    break
        except Exception:
            pass
        skills_detail.append((sk, desc))

    # Also check brave search skills
    brave_skills_dir = '/root/.openclaw/workspace/skills/brave-search/brave-search-skills-main/skills'
    brave_skills = []
    if os.path.isdir(brave_skills_dir):
        for d in os.listdir(brave_skills_dir):
            if os.path.isdir(os.path.join(brave_skills_dir, d)):
                brave_skills.append(d)

    if skills_detail:
        for name, desc in skills_detail:
            st.markdown(f"""<div class="awo-card">
                <div class="card-title">{name}</div>
                <div class="card-body">{desc}</div>
            </div>""", unsafe_allow_html=True)

    if brave_skills:
        st.markdown('<div class="section-hdr">Brave Search Skills</div>', unsafe_allow_html=True)
        cols = st.columns(4)
        for i, bs in enumerate(sorted(brave_skills)):
            with cols[i % 4]:
                st.markdown(f"""<div class="awo-card" style="text-align:center;">
                    <div class="card-title">{bs}</div>
                </div>""", unsafe_allow_html=True)

    # ── Recent Memory ──
    st.markdown('<div class="section-hdr">Recent Memory Entries</div>', unsafe_allow_html=True)
    mem_dir = '/root/.openclaw/workspace/memory'
    mem_files = sorted(glob.glob(os.path.join(mem_dir, '*.md')), reverse=True)[:5]
    if mem_files:
        for mf in mem_files:
            fname = os.path.basename(mf)
            try:
                with open(mf) as f:
                    preview = f.read(300).replace('<', '&lt;').replace('>', '&gt;')
                st.markdown(f"""<div class="awo-card">
                    <div class="card-title">{fname}</div>
                    <div class="card-body" style="font-size:11px;opacity:0.8;white-space:pre-wrap;">{preview}...</div>
                </div>""", unsafe_allow_html=True)
            except Exception:
                pass
    else:
        st.info("No memory entries found")


# ══════════════════════════════════════════════════════════════
#  TAB: TASKS
# ══════════════════════════════════════════════════════════════

with tab_tasks:

    tc1, tc2, tc3, tc4 = st.columns(4)
    with tc1: st.metric("PENDING", task_counts.get('pending', 0))
    with tc2: st.metric("IN PROGRESS", task_counts.get('in_progress', 0))
    with tc3: st.metric("COMPLETED", task_counts.get('completed', 0))
    with tc4: st.metric("FAILED", task_counts.get('failed', 0))

    # ── Create task ──
    st.markdown('<div class="section-hdr">Create Task</div>', unsafe_allow_html=True)
    with st.form("create_task_form"):
        cf1, cf2, cf3 = st.columns(3)
        with cf1:
            new_bot = st.selectbox("Assign to", ["natalia", "tradebot"])
        with cf2:
            type_opts = {"natalia": ["research", "report"], "tradebot": ["trade_analysis", "market_scan", "report"]}
            new_type = st.selectbox("Task type", type_opts.get(new_bot, []))
        with cf3:
            new_priority = st.slider("Priority", 1, 10, 5)
        new_title = st.text_input("Title / Query")
        submitted = st.form_submit_button("CREATE TASK")

        if submitted and new_title:
            try:
                from lib.task_dispatch import create_task as td_create
                task = td_create(
                    title=new_title, assigned_to=new_bot, task_type=new_type,
                    params={"query": new_title} if new_type == "research" else {"topic": new_title},
                    priority=new_priority, created_by='dashboard',
                )
                st.success(f"Task created: {task['id']}")
            except Exception as e:
                st.error(f"Failed: {e}")

    # ── Task list ──
    st.markdown('<div class="section-hdr">Task Queue</div>', unsafe_allow_html=True)
    task_filter = st.selectbox("Filter", ["all", "pending", "in_progress", "completed", "failed"],
                               label_visibility="collapsed")

    all_tasks = load_tasks(task_filter, 30)
    if all_tasks:
        for t in all_tasks:
            s_icon = {'pending': '&#9711;', 'in_progress': '&#9654;', 'completed': '&#10003;', 'failed': '&#10007;'}.get(t.get('status', '?'), '?')
            s_color = {'pending': 'var(--text-secondary)', 'in_progress': 'var(--amber)', 'completed': 'var(--green)', 'failed': 'var(--red)'}.get(t.get('status'), 'var(--text-secondary)')

            result_preview = ''
            if t.get('result') and isinstance(t['result'], dict):
                r = t['result']
                for key in ['summary', 'report', 'message']:
                    if key in r:
                        result_preview = str(r[key])[:150]
                        break
                if not result_preview and 'signals' in r:
                    result_preview = f"Scanned {r.get('total_scanned', 0)} pairs, {r.get('actionable_count', 0)} actionable"

            error_html = ''
            if t.get('error'):
                error_html = f'<div style="color:var(--red);font-size:11px;margin-top:4px;">Error: {str(t["error"])[:150]}</div>'

            st.markdown(f"""<div class="awo-card">
                <div class="card-title">
                    <span style="color:{s_color} !important;">{s_icon}</span>
                    {t.get('id', '?')[:8]} &mdash; {t.get('assigned_to', '?')} / {t.get('task_type', '?')}
                    <span class="badge" style="color:{s_color} !important;border-color:{s_color};background:transparent;float:right;">{t.get('status', '?').upper()}</span>
                </div>
                <div class="card-body">{t.get('title', '')}</div>
                {'<div style="font-size:11px;color:var(--text-secondary);margin-top:4px;">' + result_preview + '</div>' if result_preview else ''}
                {error_html}
                <div class="card-subtitle" style="margin-top:6px;">Created {t.get('created_at', '?')[:19]} by {t.get('created_by', '?')}</div>
            </div>""", unsafe_allow_html=True)
    else:
        st.info("No tasks found")


# ══════════════════════════════════════════════════════════════
#  TAB: SYSTEM
# ══════════════════════════════════════════════════════════════

with tab_system:

    sy1, sy2, sy3, sy4, sy5, sy6 = st.columns(6)
    with sy1: st.metric("UPTIME", sys_stats['uptime'])
    with sy2: st.metric("CPU", f"{sys_stats['cpu']:.1f}%")
    with sy3: st.metric("MEMORY", f"{sys_stats['memory']:.1f}%")
    with sy4: st.metric("DISK", f"{sys_stats['disk']:.1f}%")
    with sy5: st.metric("PROCESSES", sys_stats.get('processes', 0))
    with sy6: st.metric("EST. COST", f"${sys_stats['cost']:.2f}")

    st.markdown('<div class="section-hdr">Resource Details</div>', unsafe_allow_html=True)
    rd1, rd2, rd3 = st.columns(3)

    with rd1:
        st.markdown(f"""<div class="awo-card">
            <div class="card-title">MEMORY</div>
            <div class="card-body" style="font-family:'JetBrains Mono',monospace;font-size:12px;">
                Used: {sys_stats.get('mem_used_gb', 0):.1f} GB<br>
                Total: {sys_stats.get('mem_total_gb', 0):.1f} GB<br>
                Usage: {sys_stats['memory']:.1f}%
            </div>
        </div>""", unsafe_allow_html=True)

    with rd2:
        st.markdown(f"""<div class="awo-card">
            <div class="card-title">DISK</div>
            <div class="card-body" style="font-family:'JetBrains Mono',monospace;font-size:12px;">
                Used: {sys_stats.get('disk_used_gb', 0):.1f} GB<br>
                Total: {sys_stats.get('disk_total_gb', 0):.1f} GB<br>
                Usage: {sys_stats['disk']:.1f}%
            </div>
        </div>""", unsafe_allow_html=True)

    with rd3:
        st.markdown(f"""<div class="awo-card">
            <div class="card-title">NETWORK</div>
            <div class="card-body" style="font-family:'JetBrains Mono',monospace;font-size:12px;">
                Sent: {sys_stats.get('net_sent_mb', 0):,.0f} MB<br>
                Recv: {sys_stats.get('net_recv_mb', 0):,.0f} MB
            </div>
        </div>""", unsafe_allow_html=True)

    # ── Services ──
    st.markdown('<div class="section-hdr">Services</div>', unsafe_allow_html=True)

    sv1, sv2, sv3, sv4 = st.columns(4)
    with sv1:
        gw_up = False
        try:
            import urllib.request
            r = urllib.request.urlopen('http://127.0.0.1:18789/health', timeout=2)
            gw_up = r.status == 200
        except Exception:
            pass
        gw_badge = 'badge-online' if gw_up else 'badge-offline'
        st.markdown(f"""<div class="awo-card">
            <div class="card-title">OPENCLAW GATEWAY <span class="badge {gw_badge}">{'UP' if gw_up else 'DOWN'}</span></div>
            <div class="card-body">Port 18789<br>Mode: local / loopback<br>Auth: token</div>
        </div>""", unsafe_allow_html=True)

    with sv2:
        st.markdown(f"""<div class="awo-card">
            <div class="card-title">TELEGRAM <span class="badge badge-online">ACTIVE</span></div>
            <div class="card-body">DM Policy: allowlist<br>Group Policy: allowlist<br>Streaming: off</div>
        </div>""", unsafe_allow_html=True)

    with sv3:
        tb_svc = 'badge-online' if state.get('connected') else 'badge-offline'
        st.markdown(f"""<div class="awo-card">
            <div class="card-title">TRADEBOT ENGINE <span class="badge {tb_svc}">{'UP' if state.get('connected') else 'DOWN'}</span></div>
            <div class="card-body">IC Markets cTrader<br>Demo account<br>Cycle: 60s / Task poll: 30s</div>
        </div>""", unsafe_allow_html=True)

    with sv4:
        lobster_ver = '—'
        try:
            import subprocess
            result = subprocess.run(['lobster', 'version'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                lobster_ver = result.stdout.strip()
        except Exception:
            pass
        lb_badge = 'badge-online' if lobster_ver != '—' else 'badge-offline'
        st.markdown(f"""<div class="awo-card">
            <div class="card-title">LOBSTER <span class="badge {lb_badge}">{'v' + lobster_ver if lobster_ver != '—' else 'N/A'}</span></div>
            <div class="card-body">Workflow runtime<br>Workflows: {len(workflows)}<br>{"<br>".join(workflows) if workflows else "None"}</div>
        </div>""", unsafe_allow_html=True)

    # ── Config summary ──
    st.markdown('<div class="section-hdr">Configuration</div>', unsafe_allow_html=True)
    oc_config = _load_json('/root/.openclaw/openclaw.json')
    model = oc_config.get('agents', {}).get('defaults', {}).get('model', {}).get('primary', '—')
    max_concurrent = oc_config.get('agents', {}).get('defaults', {}).get('maxConcurrent', '—')
    max_sub = oc_config.get('agents', {}).get('defaults', {}).get('subagents', {}).get('maxConcurrent', '—')

    cfg1, cfg2 = st.columns(2)
    with cfg1:
        st.markdown(f"""<div class="awo-card">
            <div class="card-title">AGENT CONFIGURATION</div>
            <div class="card-body" style="font-family:'JetBrains Mono',monospace;font-size:12px;">
                Primary model: {model}<br>
                Max concurrent agents: {max_concurrent}<br>
                Max sub-agents: {max_sub}<br>
                Compaction: {oc_config.get('agents', {}).get('defaults', {}).get('compaction', {}).get('mode', '—')}<br>
                Browser: {oc_config.get('browser', {}).get('executablePath', '—')}<br>
                Tools allowed: lobster
            </div>
        </div>""", unsafe_allow_html=True)

    with cfg2:
        st.markdown(f"""<div class="awo-card">
            <div class="card-title">SAFETY CONFIGURATION</div>
            <div class="card-body" style="font-family:'JetBrains Mono',monospace;font-size:12px;">
                Kill switch: {'ACTIVE' if kill_active else 'Off'}<br>
                Max risk/trade: 2%<br>
                Max daily drawdown: 10%<br>
                Max position volume: 1.0 lot<br>
                Max open positions: 3<br>
                Min balance to trade: $10.00<br>
                Demo mode enforced: Yes
            </div>
        </div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
#  FOOTER
# ══════════════════════════════════════════════════════════════

st.markdown(f"""<div style="text-align:center;padding:30px 0 10px 0;border-top:1px solid var(--border);margin-top:30px;">
    <span style="font-size:11px;color:var(--text-muted) !important;letter-spacing:2px;">
        AI WORLD ORDER &nbsp;&bull;&nbsp; AUTONOMOUS FLEET COMMAND &nbsp;&bull;&nbsp; {now.strftime('%Y')}
    </span>
</div>""", unsafe_allow_html=True)
