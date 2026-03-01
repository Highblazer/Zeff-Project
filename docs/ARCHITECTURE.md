# OpenClaw Architecture

## System Overview

OpenClaw is an autonomous AI-operated trading and research platform. It consists of a fleet of AI agents ("employees") that manage forex, commodity, and crypto trading via the IC Markets cTrader API. The system runs on a Linux server and includes a Streamlit-based dashboard, Telegram alerting, Brave Search integration, and shared safety/utility libraries.

The platform is structured around three core agents:

- **Zeff.bot (#001)** -- CEO, overall orchestration
- **TradeBot (#002)** -- Conservative multi-market trading bot
- **Natalia (#003)** -- Chief Research Officer, research and analysis

## Directory Structure

```
/root/.openclaw/workspace/
|
|-- SOUL.md, IDENTITY.md, AGENTS.md   Top-level mission and identity docs
|-- HEARTBEAT.md                       Fleet status heartbeat
|-- TOOLS.md, USER.md                  Tool catalog and user reference
|
|-- lib/                               Shared Python libraries (see below)
|   |-- credentials.py                 Centralized credential loader
|   |-- trading_safety.py              Kill switch, drawdown limits, position validation
|   |-- atomic_write.py                Crash-safe file writes
|   |-- logging_config.py              Standardized rotating-log setup
|   |-- telegram.py                    Unified Telegram notification module
|
|-- employees/                         Bot scripts, employee mission files, state files
|   |-- paper-trading-runner.py        ** Canonical active bot ** (see below)
|   |-- tradebot_*.py                  Deprecated experimental bot variants
|   |-- ego_trading/                   Ego trading experiment (deprecated)
|   |-- ctrader_bot.py                 Early cTrader prototype (deprecated)
|   |-- icmarkets-connector.py         Low-level IC Markets connector (deprecated)
|   |-- zeffbot.md, tradebot.md,
|   |   natalia.md                     Employee mission/personality files
|   |-- EMPLOYEE_TEMPLATE.md           Template for onboarding new agents
|   |-- trading_state.json,
|   |   trading_status.json            Runtime state and status
|   |-- paper-trading-config.json      Configuration for the paper-trading runner
|   |-- send_alert.py, send_telegram.py,
|   |   telegram_notify.py,
|   |   trade_alerts.py                Legacy alert scripts (superseded by lib/telegram.py)
|   |-- monitor_bot.sh,
|   |   tradebot_supervisor.sh         Process supervisor scripts
|
|-- python/                            Core Python application code
|   |-- agent.py                       Main agent framework
|   |-- api.py                         API server
|   |-- models.py                      Data models
|   |-- streamlit_dashboard.py         Streamlit web dashboard
|   |-- tools/                         Agent tool implementations
|   |   |-- search.py                  Brave Search web search tool
|   |-- helpers/                       Agent helper utilities
|   |-- extensions/                    Agent extensions
|
|-- conf/                              Configuration files (non-secret)
|   |-- icmarkets.json                 IC Markets connection config (tokens loaded at runtime)
|   |-- trading.json                   Trading parameters (symbols, risk, lot sizes)
|
|-- skills/                            Installable skill modules
|   |-- brave-search/                  Brave Search API skill
|   |-- code-review/                   Code review skill
|   |-- trading-analysis/              Trading analysis skill
|
|-- brave-search-skills/               Brave Search skills distribution
|-- brave-search-skills-main/          Brave Search skills source
|
|-- logs/                              Log files (rotating, managed by logging_config.py)
|-- memory/                            Agent memory and research notes
|-- docs/                              Documentation (this file)
|-- dist/                              Build artifacts / deployment bundles
|
|-- system-monitor.py                  System health monitor
|-- backup_to_github.sh               GitHub backup script
|-- paper-trading-state.json           Top-level copy of trading state
```

## Canonical Active Bot

**`employees/paper-trading-runner.py`** is the canonical, actively-running trading bot. It implements:

- Fair Value Gap (FVG) + Support/Resistance + Market Structure strategy
- 1:3 risk-to-reward ratio
- IC Markets cTrader API integration via Twisted
- Kill switch checks on every trading cycle
- State persistence to JSON files
- Telegram trade alerts

All other bot files in `employees/` are deprecated experiments from earlier development iterations:

| File | Status | Notes |
|------|--------|-------|
| `tradebot_simple.py` | Deprecated | Early simple strategy |
| `tradebot_http.py` | Deprecated | HTTP-based API experiment |
| `tradebot_rest.py` | Deprecated | REST API variant |
| `tradebot_robust.py` | Deprecated | Robustness experiment |
| `tradebot_live.py` | Deprecated | Early live trading attempt |
| `tradebot_fix.py` | Deprecated | FIX protocol experiment |
| `tradebot_fix_socket.py` | Deprecated | FIX socket variant |
| `tradebot_kalshi.py` | Deprecated | Kalshi prediction market bot |
| `tradebot_kalshi_paper.py` | Deprecated | Kalshi paper trading |
| `ctrader_bot.py` | Deprecated | Early cTrader prototype |
| `icmarkets-connector.py` | Deprecated | Low-level connector |
| `ego_trading/ego_bot.py` | Deprecated | Ego trading experiment |

## Credentials Flow

Credentials follow a strict chain from environment to runtime:

```
.env file
  |
  v
lib/credentials.py (_load_dotenv)
  |  Reads .env, sets os.environ defaults
  |  Provides get_icm_credentials(), get_icm_live_credentials()
  |  Provides require_demo_mode() safety guard
  v
Bots (paper-trading-runner.py, etc.)
  |  Import from lib.credentials
  |  Call get_icm_credentials() to obtain tokens
  v
IC Markets cTrader API
```

**Key environment variables:**

| Variable | Purpose |
|----------|---------|
| `ICM_CLIENT_ID` | cTrader OAuth client ID |
| `ICM_API_SECRET` | cTrader OAuth client secret |
| `ICM_ACCESS_TOKEN` | OAuth access token |
| `ICM_REFRESH_TOKEN` | OAuth refresh token |
| `ICM_TRADING_PASSWORD` | Trading account password |
| `ICM_CTID_ACCOUNT_ID` | cTrader trader account ID |
| `ICM_ACCOUNT_ID` | IC Markets account ID |
| `ICM_MODE` | Must be `demo` for safety gate |
| `ICM_LIVE_HOST` | Live server host (for live credentials) |
| `ICM_LIVE_TRADE_PORT` | Live trade port (default 5212) |
| `ICM_LIVE_QUOTE_PORT` | Live quote port (default 5211) |
| `ICM_LIVE_ACCOUNT_LOGIN` | Live account login |
| `ICM_LIVE_SENDER_COMP_ID` | Live FIX sender comp ID |
| `ICM_LIVE_PASSWORD` | Live account password |
| `TELEGRAM_BOT_TOKEN` | Telegram bot API token |
| `TELEGRAM_CHAT_ID` | Telegram chat ID for alerts |
| `BRAVE_API_KEY` | Brave Search API key |

**Security rules:**

- Secrets live only in `.env` (never committed to git).
- `conf/icmarkets.json` and `conf/trading.json` hold non-secret configuration only.
- `lib/credentials.py` is the single point of contact for secrets.
- `require_demo_mode()` in both `lib/credentials.py` and `lib/trading_safety.py` refuses to proceed if mode is not `demo`.

## Safety System

The safety system is implemented in **`lib/trading_safety.py`** and enforces multiple layers of protection.

### Kill Switch

- **File-based kill switch:** Creating the file `/root/.openclaw/workspace/STOP_TRADING` immediately halts all trading across all bots.
- `check_kill_switch()` -- returns `True` if the kill switch file exists.
- `activate_kill_switch(reason)` -- creates the kill switch file with a timestamp and reason.
- `deactivate_kill_switch()` -- removes the kill switch file to resume trading.

### Drawdown Limits

- `MAX_DAILY_DRAWDOWN = 0.10` (10% of starting balance).
- `check_drawdown(current_balance, starting_balance)` -- returns whether the daily drawdown limit has been breached.

### Position Validation

- `MAX_RISK_PER_TRADE = 0.02` (2% of balance per trade).
- `MAX_POSITION_VOLUME = 100000` (1 standard lot max).
- `MAX_OPEN_POSITIONS = 3` (max simultaneous positions).
- `MIN_BALANCE_TO_TRADE = 10.0` (minimum balance threshold).
- `validate_position_size(volume, balance, symbol)` -- checks volume, balance minimums, and risk limits.
- `validate_price(price, symbol)` -- sanity-checks prices (non-zero, non-NaN, within reasonable ranges for JPY and gold pairs).

### Pre-Trade Gate

`pre_trade_checks(volume, balance, starting_balance, open_positions, mode, price, symbol)` runs all safety checks in sequence:

1. Kill switch check
2. Demo mode verification
3. Position size validation
4. Drawdown limit check
5. Max positions check
6. Price validation

A trade is only executed if all checks return `True`.

## Shared Libraries (`lib/`)

### `lib/credentials.py`

Centralized credential loader. Reads `.env` file on import, provides `get_icm_credentials()`, `get_icm_live_credentials()`, `get_trading_config()`, and `require_demo_mode()`. All bots should use this module instead of reading credentials directly.

### `lib/trading_safety.py`

Kill switch, drawdown limits, position size validation, price validation, and the unified `pre_trade_checks()` gate. Every trading bot must call `pre_trade_checks()` or at minimum `check_kill_switch()` before executing any trade.

### `lib/atomic_write.py`

Provides `atomic_json_write(filepath, data)` and `atomic_text_write(filepath, content)`. Writes to a temporary file first, then atomically renames to the target path. Prevents data corruption from mid-write crashes or power loss. Should be used for all state file writes.

### `lib/logging_config.py`

Provides `get_logger(name, log_file, level)`. Returns a logger with both console output and rotating file output (5 MB max, 3 backups). All logs are written to `/root/.openclaw/workspace/logs/`. Standardized format: `YYYY-MM-DD HH:MM:SS [LEVEL] name: message`.

### `lib/telegram.py`

Unified Telegram notification module. Replaces the legacy `send_alert.py`, `send_telegram.py`, `trade_alerts.py`, and `telegram_notify.py` scripts. Provides:

- `send_message(text, chat_id, parse_mode)` -- send any message
- `send_trade_alert(direction, symbol, price, reason)` -- formatted trade alert
- `send_error_alert(error, bot_name)` -- error notification
- `send_status_update(balance, positions, bot_name)` -- status update

Reads `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` from environment variables.
