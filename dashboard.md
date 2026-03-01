# ⬡ Binary Rogue Command Center

**Updated:** 2026-03-01

---

## 👥 Employees

| # | Name | Status | Role |
|---|------|--------|------|
| 001 | Zeff.bot | 🟢 | CEO — Strategic Direction & Fleet Oversight |
| 002 | TradeBot | 🟢 | Chief Trading Officer — 1H Scalping + Multi-Market |
| 003 | Ali.bot | 🟢 | Chief Trading Strategist — 6-Layer Precision (4H/D/W) |
| 004 | Natalia | 🟢 | Chief Research Officer — Intelligence & Knowledge Discovery |
| 006 | Kalshi Bot | 🟢 | Prediction Markets — Elections & Economic Events |
| 008 | Poly.Bot | 🟢 | Chief Prediction Officer — Polymarket CLOB Trading |

---

## 📊 Trading Accounts

| Bot | Broker | Mode | Balance | Positions | Strategy |
|-----|--------|------|---------|-----------|----------|
| TradeBot | IC Markets cTrader | Demo | $404.62 | 1 open | 1H scalping, 45s cycles |
| Ali.bot | IC Markets cTrader | Demo | $201.26 | 3 open | 6-layer precision (4H/D/W) |
| Poly.Bot | Polymarket (CLOB) | Paper | $100.00 | 0 | High-conviction predictions |
| Kalshi Bot | Kalshi | Paper | $100.00 | 0 | Election & economic predictions |

---

## 📈 Active Markets (35+ Instruments)

| Category | Instruments |
|----------|-------------|
| Forex Majors (7) | EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF, NZDUSD |
| Forex Crosses (5) | EURJPY, GBPJPY, EURGBP, AUDJPY, CADJPY |
| Crypto (10) | BTCUSD, ETHUSD, LTCUSD, XRPUSD, SOLUSD, ADAUSD, DOGEUSD, DOTUSD, AVXUSD, LNKUSD |
| Commodities (6) | XAUUSD, XAGUSD, XTIUSD, XBRUSD, XNGUSD, XPTUSD |
| Indices (8) | US500, US30, USTEC, US2000, UK100, DE30, JP225, AUS200 |
| Prediction | Polymarket (politics, tech, economics), Kalshi (elections, CPI, GDP, NFP, Fed) |

---

## 🖥️ Dashboards & UIs

| Dashboard | Port | Purpose |
|-----------|------|---------|
| Fleet Command | 8080 | Main ops — agent status, positions, performance, tasks, news |
| Public Performance | 8502 | Read-only proof of trading (win rate, Sharpe, P&L) |
| News Intelligence | 8503 | Real-time categorized news for TradeBot & Natalia |

---

## 🔌 APIs & Services

| Service | Port | Protocol | Purpose |
|---------|------|----------|---------|
| Signal API | 8000 | REST (FastAPI) | Signals, news sentiment, stats, API key auth + rate limits |
| Fleet Dashboard | 8080 | Streamlit | Fleet Command visualization + controls |
| Copy-Trade Server | 8765 | WebSocket | Real-time trade broadcast (OPEN/CLOSE/AMEND/TICK events) |

**Signal API Endpoints:**
- `GET /api/signals/latest` — Current signals with scores
- `GET /api/signals/{symbol}` — Detailed pair analysis
- `GET /api/signals/history` — Signal archives
- `GET /api/news/sentiment` — Market bias from news intel
- `GET /api/stats` — Bot performance metrics
- `GET /api/status` — System health (public)
- `GET /api/agents` — Agent roster (public)
- `POST /admin/keys/generate` — API key management

---

## 🧠 Intelligence & Research

| System | Description |
|--------|-------------|
| Natalia Research Engine | Web search (Brave + DuckDuckGo), fact-checking, multi-query deep reports |
| News Collector | Brave News API — forex, crypto, macro, AI/LLM categorization |
| News Store | Persistent article storage with deduplication & memory rotation |
| Memory System | Fleet-wide knowledge sharing via structured memory files |
| Sentiment Analysis | Keyword-based market bias extraction from news intel |

---

## 🛡️ Risk Management & Safety

| Feature | Description |
|---------|-------------|
| Kill Switch | `STOP_TRADING` file halts all trading instantly |
| Position Limits | Max 5 concurrent positions |
| Risk Per Trade | Max 5% of balance |
| Daily Drawdown | Max 15% aggregate |
| Min Balance | $10 to trade |
| Pre-Trade Validation | Dollar risk, volume, spread checks on every order |
| Atomic Writes | Crash-safe JSON persistence (no state corruption) |

---

## 📦 Core Libraries

| Module | Purpose |
|--------|---------|
| `lib/trading_safety.py` | Risk checks, kill switch, pre-trade validation |
| `lib/polymarket_api.py` | Polymarket CLOB API client |
| `lib/telegram.py` | Telegram bot messaging & alerts |
| `lib/news_collector.py` | Brave Search news aggregation |
| `lib/news_store.py` | Article persistence & memory management |
| `lib/zeffbot_report.py` | Executive reporting to CEO via Telegram |
| `lib/task_dispatch.py` | Async file-based task queue |
| `lib/credentials.py` | Secure credential loading from env |
| `lib/atomic_write.py` | Crash-safe JSON writes |
| `lib/logging_config.py` | Structured logging with rotation |

---

## 🔧 Infrastructure

| Component | Details |
|-----------|---------|
| Model | Minimax M2.5 (reasoning, 200K context) |
| Gateway | Port 18789 (local loopback) |
| Notifications | Telegram (real-time alerts to fleet owner) |
| Task Queue | File-based async dispatch (pending/in_progress/completed/failed) |
| Deployment | Local single-machine, Cloudflare tunnel for public access |
| Credentials | .env-based, token auth on gateway |
| Process Mgmt | systemd services with auto-restart |
| Fleet Health | Unified health monitor with auto-recovery + Telegram alerts |
| Backups | Daily auto-push to GitHub + local state snapshots (14-day retention) |
| Log Rotation | Cron-based (daily at 03:00, cap 50MB per log) |

---

## 🔄 systemd Services

| Service | Status | Auto-Restart |
|---------|--------|-------------|
| `tradebot.service` | Enabled | Yes (on-failure, 10s delay) |
| `alibot.service` | Enabled | Yes (on-failure, 30s delay) |
| `natalia.service` | Enabled | Yes (on-failure, 10s delay) |
| `polybot.service` | Enabled | Yes (on-failure, 30s delay) |
| `kalshi.service` | Enabled | Yes (on-failure, 30s delay) |
| `tradebot-watchdog.service` | Enabled | Yes (always) |
| `fleet-health.service` | Enabled | Yes (always) |
| `trade-dashboard.service` | Enabled | Yes |

---

*Binary Rogue*
