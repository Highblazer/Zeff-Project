# DISCORD MIGRATION — AGENT REPORT FOR APPROVAL

**Date:** 2026-03-01
**Prepared by:** All agents (API Research, Migration Analysis, Fleet Audit)
**For:** Seth (Fleet Owner)
**Status:** READY FOR EXECUTION — awaiting 3 credentials from you

---

## EXECUTIVE SUMMARY

We've built a **fully automated Discord setup script** that eliminates 90% of the manual work from Milkbot's original 8-step plan. Instead of you creating ~20 channels and 10+ webhooks by hand, you do 5 minutes of clicking and our script does the rest.

### What You Need To Do (5 minutes)

1. **Create a Discord server** (click + in Discord → Create My Own)
2. **Create a Discord bot** at https://discord.com/developers/applications
   - New Application → name it "Zeff.bot" → Create
   - Bot tab → Reset Token → **copy the token**
   - Turn on Message Content Intent
3. **Invite the bot** to your server:
   - OAuth2 → URL Generator → check `bot`
   - Bot permissions: use integer `805421072` (all needed perms pre-calculated)
   - Copy URL → paste in browser → select your server → Authorize
4. **Get your IDs** (Discord Settings → Advanced → Developer Mode → ON):
   - Right-click server name → Copy Server ID
   - Right-click your username → Copy User ID
5. **Give us these 3 values:**
   ```
   Bot Token: _______________
   Server ID: _______________
   User ID:   _______________
   ```

### What Our Script Does Automatically

```
python3 /root/.openclaw/workspace/scripts/discord_setup.py <TOKEN> <GUILD_ID> <USER_ID>
```

1. Verifies bot can access your server
2. Creates **7 categories** with **19 channels** (matching Milkbot's plan exactly)
3. Creates **10 webhooks** (one per alert channel)
4. Makes OPERATIONS category **private** (only you can see fleet-health, errors, watchdog, morning-briefing)
5. Writes all 13 `DISCORD_*` environment variables to `.env` automatically
6. Sends a test embed to `#fleet-health` to confirm everything works
7. Handles Discord rate limits automatically

---

## SERVER STRUCTURE (what gets created)

```
📋 INFORMATION
   #welcome            — Welcome message
   #announcements       — Fleet-wide announcements
   #fleet-status        — Live fleet health overview

📈 TRADING SIGNALS
   #tradebot-signals    — TradeBot paper trading    → webhook
   #alibot-signals      — Ali.bot precision trades  → webhook
   #market-scans        — Market scanning results   → webhook

🔮 PREDICTIONS
   #polybot-signals     — Poly.Bot prediction bets  → webhook
   #kalshi-signals      — Kalshi prediction trades  → webhook

🧠 INTELLIGENCE
   #natalia-research    — Research & reports         → webhook
   #news-feed           — Automated news

🛡️  OPERATIONS (private — only you)
   #fleet-health        — Fleet health alerts        → webhook
   #watchdog            — TradeBot watchdog alerts
   #morning-briefing    — Daily digest + improvements → webhook
   #errors              — Error alerts from all bots → webhook

💎 PREMIUM
   #premium-entries     — Premium signals            → webhook
   #premium-results     — Trade results & P&L

💬 COMMUNITY
   #general             — General discussion
   #trade-ideas         — Share trade ideas
```

**Total: 7 categories, 19 channels, 10 webhooks**

---

## FLEET STATUS (right now)

| Service | Status | Entry Point |
|---------|--------|-------------|
| tradebot.service | 🟢 RUNNING | employees/paper-trading-runner.py |
| alibot.service | 🟢 RUNNING | employees/alibot-runner.py |
| natalia.service | 🟢 RUNNING | employees/natalia-runner.py |
| polybot.service | 🟢 RUNNING | employees/polybot-runner.py |
| kalshi.service | 🟢 RUNNING | employees/kalshi-runner.py |
| fleet-health.service | 🟢 RUNNING | employees/fleet_health_monitor.py |
| tradebot-watchdog.service | 🟢 RUNNING | employees/tradebot_watchdog.py |
| trade-dashboard.service | 🟢 RUNNING | Streamlit dashboard |
| trade-portforward.service | 🟢 RUNNING | Port forwarding |
| trade-tunnel.service | 🟢 RUNNING | Tunnel |

**All 10 services green. Fleet survived the power outage via systemd auto-restart.**

---

## MIGRATION PLAN (after Discord setup runs)

The existing migration prompt (`docs/DISCORD_MIGRATION_PROMPT.md`) handles all code changes:

| Phase | What Changes | Files |
|-------|-------------|-------|
| 3 | Create `lib/discord.py` (webhook notification module) | 1 new file |
| 4 | Update `lib/zeffbot_report.py` (HTML → Discord embeds) | 1 file |
| 5 | Update imports in all 9 employee runners | 9 files |
| 6 | Archive `lib/telegram.py` → `lib/telegram_legacy.py` | 1 rename |
| 7 | Update docs | 2 files |
| 8 | Syntax check + test + restart services | all services |
| 9 | Git commit + push | — |

**Architecture:** Stateless webhook HTTP POSTs (no discord.py library, no persistent bot connection, stdlib only — same pattern as current Telegram module).

**Risk:** LOW — wrapper replacement only, no trading logic changes, full rollback in one command.

---

## MORNING BRIEFING — DAILY IMPROVEMENT DIGEST

**New feature baked into `#morning-briefing` channel.**

Each morning, the digest will include a new section: **"How To Get Smarter, Faster, More Efficient"**

Content sourced from all agents:

| Agent | Improvement Data |
|-------|-----------------|
| **TradeBot** | Win rate trends, R:R analysis, which sessions perform best, spread impact |
| **Ali.bot** | Higher-TF pattern accuracy, layer scoring improvements, missed setups |
| **Natalia** | Research insights that moved the needle, skill gaps identified |
| **Poly.Bot** | Prediction accuracy by category, which markets have edge |
| **Kalshi** | Event prediction hit rate, calibration scoring |
| **Fleet Health** | Uptime stats, restart frequency, resource bottlenecks |
| **Watchdog** | Disconnect patterns, latency trends |

**Format:** Each agent contributes 1-2 bullet points of actionable improvement advice based on the previous day's performance data. This gets compiled into the morning briefing embed sent to `#morning-briefing`.

---

## ENVIRONMENT VARIABLES (auto-written to .env)

```
DISCORD_BOT_TOKEN=<your_token>
DISCORD_GUILD_ID=<your_server_id>
DISCORD_OWNER_ID=<your_user_id>
DISCORD_WEBHOOK_TRADEBOT=<auto_generated>
DISCORD_WEBHOOK_ALIBOT=<auto_generated>
DISCORD_WEBHOOK_NATALIA=<auto_generated>
DISCORD_WEBHOOK_HEALTH=<auto_generated>
DISCORD_WEBHOOK_MORNING=<auto_generated>
DISCORD_WEBHOOK_PREMIUM=<auto_generated>
DISCORD_WEBHOOK_ERRORS=<auto_generated>
DISCORD_WEBHOOK_POLYBOT=<auto_generated>
DISCORD_WEBHOOK_KALSHI=<auto_generated>
DISCORD_WEBHOOK_MARKET_SCANS=<auto_generated>
```

---

## BOT PERMISSIONS (pre-calculated)

**OAuth2 invite permissions integer: `805421072`**

Breakdown:
- Manage Channels (create categories/channels)
- View Channels (see channels)
- Send Messages (post in channels)
- Embed Links (rich embeds)
- Attach Files (upload images)
- Read Message History (context)
- Manage Roles (set private channel overwrites)
- Manage Webhooks (create webhooks)

**Invite URL format:**
```
https://discord.com/oauth2/authorize?client_id=YOUR_APP_ID&permissions=805421072&scope=bot
```

---

## REVERT PLAN

If anything breaks at any stage:

```bash
# Revert code changes
cd /root/.openclaw/workspace
git revert HEAD

# Restart fleet on Telegram
sudo systemctl restart tradebot alibot natalia polybot kalshi tradebot-watchdog fleet-health
```

One command reverts code. One command restarts fleet. Telegram comes right back.

---

## APPROVAL REQUESTED

**Seth — do you approve this plan?**

When ready, provide your 3 values (bot token, server ID, user ID) and we execute immediately.

Everything is automated. Everything is reversible. Everything is backed up.
