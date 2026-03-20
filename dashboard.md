# ⬡ AI World Order — Fleet Reference

**Updated:** 2026-03-19

---

## 👥 Employees

| # | Name | Status | Role | Division |
|---|------|--------|------|----------|
| 001 | Zeff.bot | 🟢 | CEO — Strategic Direction & Fleet Oversight | Command |
| 002 | TradeBot | 🟢 | Chief Trading Officer — 1H Scalping + Multi-Market | Trading |
| 004 | Natalia | 🟢 | Chief Research Officer — Intelligence & Knowledge Discovery | Intelligence |
| 009 | Pixel Pete | 🟢 | Chief Web Officer — Client Website Development | New Business |

---

## 📊 Trading Accounts

| Bot | Broker | Mode | Balance | Positions | Strategy |
|-----|--------|------|---------|-----------|----------|
| TradeBot | IC Markets cTrader | Demo | $404.62 | 1 open | 1H scalping, 45s cycles |

---

## 📈 Active Markets (36 Instruments)

| Category | Instruments |
|----------|-------------|
| Forex Majors (7) | EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF, NZDUSD |
| Forex Crosses (5) | EURJPY, GBPJPY, EURGBP, AUDJPY, CADJPY |
| Crypto (10) | BTCUSD, ETHUSD, LTCUSD, XRPUSD, SOLUSD, ADAUSD, DOGEUSD, DOTUSD, AVXUSD, LNKUSD |
| Commodities (6) | XAUUSD, XAGUSD, XTIUSD, XBRUSD, XNGUSD, XPTUSD |
| Indices (8) | US500, US30, USTEC, US2000, UK100, DE30, JP225, AUS200 |

---

## 🔔 Notifications

| Channel | Purpose |
|---------|---------|
| Telegram | Trade entry/exit alerts, fleet health alerts, research reports, CEO reports |

---

## 🌐 Web Projects

| Project | Status | Description |
|---------|--------|-------------|
| BleuCrewBe | In Development | Client website — managed by Pixel Pete (#009) |

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
| `natalia.service` | Enabled | Yes (on-failure, 10s delay) |
| `tradebot-watchdog.service` | Enabled | Yes (always) |
| `fleet-health.service` | Enabled | Yes (always) |

---

*AI World Order*
