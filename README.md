# AI World Order — Zeff Project

Autonomous multi-agent fleet powered by [OpenClaw](https://docs.openclaw.ai), operating across forex, prediction markets, and research — coordinated through Telegram.

## Fleet

| # | Agent | Role | Domain |
|---|-------|------|--------|
| 001 | **Zeff.bot** | CEO | Strategic oversight, fleet coordination |
| 002 | **TradeBot** | Trading Strategist | Forex via IC Markets cTrader (FVG + S/R + EMA + Fib) |
| 004 | **Natalia** | Chief Research Officer | Web research, tool discovery, intelligence |

## Architecture

```
Telegram <-> OpenClaw Gateway (port 18789)
                 |
           MiniMax M2.5 (LLM)
                 |
        +--------+--------+
     Zeff.bot  TradeBot  Natalia
        |        |         |
        |   IC Markets   Brave Search
        |   cTrader API  Web Research
        |        |         |
        +---- Lobster Workflows ------+
                 |
           Task Dispatch
           Memory System
           Telegram Reports
```

## Key Components

- **`employees/`** — Agent definitions (identity, mandate, responsibilities)
- **`lib/`** — Shared Python libraries (safety, reporting, task dispatch)
- **`python/`** — Dashboard, API server, browser tools, helpers
- **`workflows/`** — Lobster workflow pipelines (approval-gated trade execution)
- **`skills/`** — OpenClaw skills (trading analysis, code review)
- **`docs/`** — Architecture docs and operational runbook
- **`memory/`** — Fleet research and knowledge base

## Dashboard

Streamlit dashboard on port 8501 — dark cyberpunk theme with live prices, fleet status, position tracking, task management, and system monitoring.

```bash
streamlit run python/streamlit_dashboard.py --server.port 8501
```

## Lobster Workflows

Deterministic trade execution pipelines with human approval gates:

```bash
lobster run --mode tool --file workflows/tradebot-cycle.yaml
```

Pipeline: Safety checks -> Market scan -> Order proposals -> **Approval gate** -> Execute -> Report

## Safety

- Kill switch (`STOP_TRADING` file)
- Demo mode enforced
- Max 2% risk per trade
- Max 10% daily drawdown
- Max 3 open positions
- All trades require stop loss + take profit
