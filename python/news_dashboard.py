#!/usr/bin/env python3
"""
News Intelligence Dashboard — Streamlit app (port 8502).

Displays categorized news intelligence for TradeBot and Natalia,
with auto-collection, filtering, and cyberpunk AWO theme.

Run: streamlit run python/news_dashboard.py --server.port 8502
"""

import sys
import time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '/root/.openclaw/workspace')

import streamlit as st

st.set_page_config(
    page_title='AWO News Intelligence',
    page_icon='📡',
    layout='wide',
    initial_sidebar_state='collapsed',
)

from lib.news_store import get_feed, get_feed_metadata, is_stale
from lib.news_collector import run_collection

# ══════════════════════════════════════════════════════════════
#  LOGO + CSS (same theme as main dashboard)
# ══════════════════════════════════════════════════════════════

AWO_LOGO = """
<svg viewBox="0 0 400 120" xmlns="http://www.w3.org/2000/svg" style="width:280px;height:84px;">
  <g transform="translate(50,60)">
    <polygon points="0,-38 33,-19 33,19 0,38 -33,19 -33,-19"
             fill="none" stroke="#00e5ff" stroke-width="2.5" opacity="0.9"/>
    <polygon points="0,-24 21,-12 21,12 0,24 -21,12 -21,-12"
             fill="none" stroke="#00e5ff" stroke-width="1.5" opacity="0.5"/>
    <circle cx="0" cy="0" r="6" fill="#00e5ff" opacity="0.8"/>
    <circle cx="0" cy="0" r="3" fill="#0a0f1e"/>
    <line x1="0" y1="-24" x2="0" y2="-38" stroke="#00e5ff" stroke-width="1" opacity="0.4"/>
    <line x1="21" y1="-12" x2="33" y2="-19" stroke="#00e5ff" stroke-width="1" opacity="0.4"/>
    <line x1="21" y1="12" x2="33" y2="19" stroke="#00e5ff" stroke-width="1" opacity="0.4"/>
    <line x1="0" y1="24" x2="0" y2="38" stroke="#00e5ff" stroke-width="1" opacity="0.4"/>
    <line x1="-21" y1="12" x2="-33" y2="19" stroke="#00e5ff" stroke-width="1" opacity="0.4"/>
    <line x1="-21" y1="-12" x2="-33" y2="-19" stroke="#00e5ff" stroke-width="1" opacity="0.4"/>
    <circle cx="0" cy="-38" r="2.5" fill="#00e5ff" opacity="0.6"/>
    <circle cx="33" cy="-19" r="2.5" fill="#00e5ff" opacity="0.6"/>
    <circle cx="33" cy="19" r="2.5" fill="#00e5ff" opacity="0.6"/>
    <circle cx="0" cy="38" r="2.5" fill="#00e5ff" opacity="0.6"/>
    <circle cx="-33" cy="19" r="2.5" fill="#00e5ff" opacity="0.6"/>
    <circle cx="-33" cy="-19" r="2.5" fill="#00e5ff" opacity="0.6"/>
  </g>
  <text x="100" y="48" fill="#00e5ff" font-family="'Segoe UI','Helvetica Neue',sans-serif"
        font-size="24" font-weight="700" letter-spacing="3">NEWS INTELLIGENCE</text>
  <text x="100" y="72" fill="#5a7a8a" font-family="'Segoe UI','Helvetica Neue',sans-serif"
        font-size="11" letter-spacing="6" font-weight="400">AI WORLD ORDER</text>
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

    h1, h2, h3, h4, h5, h6 {{
        color: var(--cyan) !important;
        font-family: 'Inter', sans-serif !important;
        font-weight: 600 !important;
        letter-spacing: 0.5px;
    }}
    p, div, span, label {{ color: var(--text-primary) !important; }}
    a {{ color: var(--cyan) !important; }}

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

    /* Radio buttons */
    .stRadio > div {{ flex-direction: row !important; gap: 4px; }}
    .stRadio > div > label {{
        background: var(--bg-card) !important;
        border: 1px solid var(--border) !important;
        border-radius: 6px !important;
        padding: 6px 14px !important;
        font-size: 11px !important;
        font-weight: 600 !important;
        letter-spacing: 1px !important;
        cursor: pointer;
    }}
    .stRadio > div > label[data-checked="true"],
    .stRadio > div [data-baseweb="radio"] input:checked + div {{
        border-color: var(--cyan) !important;
        background: var(--cyan-glow) !important;
    }}

    /* Article cards */
    .news-card {{
        background: var(--bg-card);
        border: 1px solid var(--border);
        border-radius: 10px;
        padding: 16px 18px;
        margin: 8px 0;
        backdrop-filter: blur(8px);
        transition: border-color 0.25s, box-shadow 0.25s;
    }}
    .news-card:hover {{
        border-color: var(--border-hover);
        box-shadow: 0 0 20px var(--cyan-glow);
    }}
    .news-card .card-source {{
        font-size: 10px;
        font-weight: 600;
        color: var(--text-secondary) !important;
        letter-spacing: 1px;
        text-transform: uppercase;
        margin-bottom: 4px;
    }}
    .news-card .card-title {{
        font-size: 14px;
        font-weight: 600;
        color: var(--text-primary) !important;
        line-height: 1.4;
        margin-bottom: 6px;
    }}
    .news-card .card-title a {{
        color: var(--text-primary) !important;
        text-decoration: none;
    }}
    .news-card .card-title a:hover {{
        color: var(--cyan) !important;
    }}
    .news-card .card-excerpt {{
        font-size: 12px;
        color: var(--text-secondary) !important;
        line-height: 1.5;
    }}

    /* Relevance badges */
    .badge {{
        display: inline-block;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 9px;
        font-weight: 600;
        letter-spacing: 0.8px;
        text-transform: uppercase;
        margin-left: 6px;
    }}
    .badge-high {{ background: rgba(0,230,118,0.12); color: var(--green) !important; border: 1px solid rgba(0,230,118,0.25); }}
    .badge-medium {{ background: rgba(255,193,7,0.12); color: var(--amber) !important; border: 1px solid rgba(255,193,7,0.25); }}
    .badge-low {{ background: rgba(90,122,138,0.15); color: var(--text-secondary) !important; border: 1px solid rgba(90,122,138,0.25); }}

    /* Section headers */
    .section-hdr {{
        font-size: 12px;
        font-weight: 600;
        letter-spacing: 2px;
        color: var(--text-secondary) !important;
        text-transform: uppercase;
        margin: 20px 0 12px 0;
        padding-bottom: 8px;
        border-bottom: 1px solid var(--border);
    }}

    /* Logo bar */
    .logo-bar {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 8px 0 16px 0;
        border-bottom: 1px solid var(--border);
        margin-bottom: 16px;
    }}
    .logo-bar .meta {{
        font-family: 'JetBrains Mono', monospace;
        font-size: 11px;
        color: var(--text-secondary) !important;
        text-align: right;
        line-height: 1.8;
    }}
    .logo-bar .meta a {{
        color: var(--cyan) !important;
        text-decoration: none;
        border: 1px solid var(--border);
        padding: 4px 12px;
        border-radius: 4px;
        font-size: 11px;
        letter-spacing: 1px;
    }}
    .logo-bar .meta a:hover {{
        border-color: var(--cyan);
        background: var(--cyan-glow);
    }}

    /* Footer */
    .awo-footer {{
        text-align: center;
        padding: 24px 0 12px 0;
        margin-top: 32px;
        border-top: 1px solid var(--border);
        font-size: 10px;
        color: var(--text-muted) !important;
        letter-spacing: 2px;
        text-transform: uppercase;
    }}

    hr {{ border-color: var(--border) !important; opacity: 0.4; }}
    ::-webkit-scrollbar {{ width: 6px; }}
    ::-webkit-scrollbar-track {{ background: var(--bg-primary); }}
    ::-webkit-scrollbar-thumb {{ background: rgba(0,229,255,0.2); border-radius: 3px; }}

    .stAlert {{ background: var(--bg-card) !important; border-left: 3px solid var(--cyan) !important; color: var(--text-primary) !important; }}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════

def _relevance_badge(score: float) -> str:
    """Return HTML badge for relevance score."""
    if score >= 0.7:
        return '<span class="badge badge-high">HIGH</span>'
    elif score >= 0.4:
        return '<span class="badge badge-medium">MED</span>'
    else:
        return '<span class="badge badge-low">LOW</span>'


def _time_ago(iso_str: str) -> str:
    """Convert ISO timestamp to human-readable age."""
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        minutes = int(delta.total_seconds() / 60)
        if minutes < 60:
            return f'{minutes}m ago'
        hours = minutes // 60
        if hours < 24:
            return f'{hours}h ago'
        days = hours // 24
        return f'{days}d ago'
    except Exception:
        return ''


def _render_article_card(article: dict) -> str:
    """Render a single article as an HTML card."""
    title = article.get('title', 'Untitled')
    url = article.get('url', '#')
    source = article.get('source', 'unknown')
    age = article.get('age', '') or _time_ago(article.get('extracted_at', ''))
    score = article.get('relevance_score', 0)
    badge = _relevance_badge(score)
    desc = article.get('description', '') or article.get('summary', '')
    excerpt = desc[:250].rstrip() + ('...' if len(desc) > 250 else '')

    return f"""
    <div class="news-card">
        <div class="card-source">{source} &middot; {age} {badge}</div>
        <div class="card-title"><a href="{url}" target="_blank">{title}</a></div>
        <div class="card-excerpt">{excerpt}</div>
    </div>
    """


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
        <br>
        <a href="//62.171.152.37:8501" target="_self">FLEET COMMAND</a>
    </div>
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
#  STALE CHECK — auto-collect if feed > 1 hour old
# ══════════════════════════════════════════════════════════════

if 'collection_running' not in st.session_state:
    st.session_state.collection_running = False

if is_stale() and not st.session_state.collection_running:
    st.session_state.collection_running = True
    with st.status('Collecting fresh intelligence...', expanded=True) as status:
        st.write('Querying Brave News API across 11 topics...')
        try:
            articles = run_collection()
            st.write(f'Collected {len(articles)} articles')
            status.update(label='Collection complete', state='complete')
        except Exception as e:
            st.write(f'Collection error: {e}')
            status.update(label='Collection failed', state='error')
    st.session_state.collection_running = False
    st.rerun()


# ══════════════════════════════════════════════════════════════
#  TIME RANGE FILTER
# ══════════════════════════════════════════════════════════════

time_options = {'1h': 1, '6h': 6, '12h': 12, '24h': 24, '48h': 48}
col_filter, col_refresh = st.columns([4, 1])

with col_filter:
    selected_range = st.radio(
        'TIME RANGE',
        options=list(time_options.keys()),
        index=3,  # default 24h
        horizontal=True,
        label_visibility='collapsed',
    )
hours = time_options[selected_range]

with col_refresh:
    if st.button('REFRESH NOW'):
        with st.spinner('Collecting...'):
            try:
                run_collection()
            except Exception as e:
                st.error(f'Collection failed: {e}')
        st.rerun()


# ══════════════════════════════════════════════════════════════
#  METRICS ROW
# ══════════════════════════════════════════════════════════════

meta = get_feed_metadata()
tradebot_articles = get_feed(bot='tradebot', hours=hours)
natalia_articles = get_feed(bot='natalia', hours=hours)
total = len(set(a['id'] for a in tradebot_articles + natalia_articles))

last_collected = meta.get('last_collection_at', '')
if last_collected:
    last_str = _time_ago(last_collected)
else:
    last_str = 'NEVER'

m1, m2, m3, m4 = st.columns(4)
with m1:
    st.metric('TOTAL ARTICLES', total)
with m2:
    st.metric('TRADEBOT INTEL', len(tradebot_articles))
with m3:
    st.metric('NATALIA INTEL', len(natalia_articles))
with m4:
    st.metric('LAST COLLECTED', last_str)


# ══════════════════════════════════════════════════════════════
#  TWO-COLUMN FEED
# ══════════════════════════════════════════════════════════════

col_trade, col_natalia = st.columns(2)

with col_trade:
    st.markdown('<div class="section-hdr">TRADEBOT INTEL — MARKETS & ECONOMICS</div>', unsafe_allow_html=True)

    if not tradebot_articles:
        st.markdown("""
        <div class="news-card">
            <div class="card-excerpt">No market intelligence in this time range. Click REFRESH NOW to collect.</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        for article in tradebot_articles[:20]:
            st.markdown(_render_article_card(article), unsafe_allow_html=True)

            # Expandable full content
            content = article.get('full_content', '')
            if content:
                with st.expander('Read full content', expanded=False):
                    st.markdown(f'<div style="font-size:12px;color:#5a7a8a;line-height:1.6;">{content[:2000]}</div>', unsafe_allow_html=True)


with col_natalia:
    st.markdown('<div class="section-hdr">NATALIA INTEL — AI & TECHNOLOGY</div>', unsafe_allow_html=True)

    if not natalia_articles:
        st.markdown("""
        <div class="news-card">
            <div class="card-excerpt">No AI/tech intelligence in this time range. Click REFRESH NOW to collect.</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        for article in natalia_articles[:20]:
            st.markdown(_render_article_card(article), unsafe_allow_html=True)

            content = article.get('full_content', '')
            if content:
                with st.expander('Read full content', expanded=False):
                    st.markdown(f'<div style="font-size:12px;color:#5a7a8a;line-height:1.6;">{content[:2000]}</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
#  FOOTER
# ══════════════════════════════════════════════════════════════

st.markdown("""
<div class="awo-footer">
    AI WORLD ORDER &middot; NEWS INTELLIGENCE MODULE &middot; AUTONOMOUS FLEET COMMAND
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
#  AUTO-REFRESH every 5 minutes
# ══════════════════════════════════════════════════════════════

st.markdown("""
<script>
    setTimeout(function() {
        window.location.reload();
    }, 300000);
</script>
""", unsafe_allow_html=True)
