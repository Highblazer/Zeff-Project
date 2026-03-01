# Discord Migration — Implementation Prompt

**Give this entire prompt to your Zeff.bot agent. It contains everything needed.**

---

## PROMPT START

You are implementing a migration of the Zeff.bot fleet notification system from Telegram to Discord. This is a targeted migration — only the Python alert system moves to Discord. The OpenClaw Telegram plugin stays on Telegram for now (agent chat with Seth). All bots stay in demo/paper mode. No trading logic changes. No strategy changes. Only the notification delivery layer changes.

**IMPORTANT RULES:**
- Do NOT modify any trading logic, strategy code, or risk management
- Do NOT touch `.env` credentials for trading (IC Markets, Brave, etc.)
- Do NOT change any systemd service files
- Do NOT restart running bots until ALL code changes are complete and tested
- Create a git commit BEFORE making any changes (safety checkpoint)
- Create a git commit AFTER all changes are complete
- Keep Telegram code in an archive — do NOT delete `lib/telegram.py`, rename it to `lib/telegram_legacy.py`

---

## PHASE 1: PRE-FLIGHT

### Step 1.1: Safety commit
```bash
cd /root/.openclaw/workspace
git add -A
git commit -m "Pre-Discord migration checkpoint — $(date '+%Y-%m-%d %H:%M')"
```

### Step 1.2: Verify current state
Confirm these files exist and read them to understand the current implementation:
- `/root/.openclaw/workspace/lib/telegram.py` (169 lines — the core module being replaced)
- `/root/.openclaw/workspace/lib/zeffbot_report.py` (333 lines — the reporter being updated)
- `/root/.openclaw/workspace/.env` (check for existing DISCORD_ variables)

---

## PHASE 2: DISCORD SETUP PREREQUISITES

### Step 2.1: Add Discord environment variables to `.env`

Append these lines to `/root/.openclaw/workspace/.env` (Seth must fill in the values after creating his Discord server and bot):

```
# === DISCORD ===
# Create server, bot, and webhooks first, then fill these in.
# Bot: https://discord.com/developers/applications → New Application → Bot → Copy Token
# Webhooks: Right-click channel → Edit Channel → Integrations → Webhooks → New Webhook → Copy URL
DISCORD_BOT_TOKEN=
DISCORD_GUILD_ID=
DISCORD_OWNER_ID=
DISCORD_WEBHOOK_TRADEBOT=
DISCORD_WEBHOOK_ALIBOT=
DISCORD_WEBHOOK_NATALIA=
DISCORD_WEBHOOK_HEALTH=
DISCORD_WEBHOOK_MORNING=
DISCORD_WEBHOOK_PREMIUM=
DISCORD_WEBHOOK_ERRORS=
DISCORD_WEBHOOK_PREDICTIONS=
DISCORD_WEBHOOK_POLYBOT=
DISCORD_WEBHOOK_KALSHI=
DISCORD_WEBHOOK_MARKET_SCANS=
```

### Step 2.2: Update `.env.example` with the same variables (placeholder values)

Add matching entries to `/root/.openclaw/workspace/.env.example` with placeholder values like `your_discord_bot_token_here`.

### Step 2.3: Install requests library (if not already installed)

```bash
pip install requests
```

---

## PHASE 3: CREATE `lib/discord.py`

Create the file `/root/.openclaw/workspace/lib/discord.py` with EXACTLY this implementation:

```python
#!/usr/bin/env python3
"""
Discord notification module for Zeff.bot fleet.

Replaces lib/telegram.py. Uses Discord webhooks (stateless HTTP POST)
for all alert delivery. No persistent bot connection required.

Webhook URLs are loaded from environment variables.
Each channel has its own webhook for routing.

Usage:
    from lib.discord import send_message, send_embed
    send_message("Hello from Zeff.bot")
    send_embed(embed_dict, webhook_url=WEBHOOK_TRADEBOT)
"""

import json
import os
import logging
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError

log = logging.getLogger('discord')

# --- Webhook URLs (loaded from .env) ---
DISCORD_WEBHOOK_DEFAULT = os.environ.get('DISCORD_WEBHOOK_HEALTH', '')
DISCORD_WEBHOOK_TRADEBOT = os.environ.get('DISCORD_WEBHOOK_TRADEBOT', '')
DISCORD_WEBHOOK_ALIBOT = os.environ.get('DISCORD_WEBHOOK_ALIBOT', '')
DISCORD_WEBHOOK_NATALIA = os.environ.get('DISCORD_WEBHOOK_NATALIA', '')
DISCORD_WEBHOOK_HEALTH = os.environ.get('DISCORD_WEBHOOK_HEALTH', '')
DISCORD_WEBHOOK_MORNING = os.environ.get('DISCORD_WEBHOOK_MORNING', '')
DISCORD_WEBHOOK_PREMIUM = os.environ.get('DISCORD_WEBHOOK_PREMIUM', '')
DISCORD_WEBHOOK_ERRORS = os.environ.get('DISCORD_WEBHOOK_ERRORS', '')
DISCORD_WEBHOOK_PREDICTIONS = os.environ.get('DISCORD_WEBHOOK_PREDICTIONS', '')
DISCORD_WEBHOOK_POLYBOT = os.environ.get('DISCORD_WEBHOOK_POLYBOT', '')
DISCORD_WEBHOOK_KALSHI = os.environ.get('DISCORD_WEBHOOK_KALSHI', '')
DISCORD_WEBHOOK_MARKET_SCANS = os.environ.get('DISCORD_WEBHOOK_MARKET_SCANS', '')

# --- Colors ---
COLOR_GREEN = 3066993     # #2ECC71 — BUY / success
COLOR_RED = 15158332      # #E74C3C — SELL / error
COLOR_GOLD = 15844367     # #F1C40F — warning
COLOR_BLUE = 3447003      # #3498DB — info
COLOR_PURPLE = 10181046   # #9B59B6 — research
COLOR_DARK = 2303786      # #23272A — neutral / system


def send_message(text: str, webhook_url: str = '', username: str = 'Zeff.bot') -> bool:
    """
    Send a plain text message to a Discord webhook.

    Drop-in replacement for lib/telegram.py send_message().
    If webhook_url is not provided, uses DISCORD_WEBHOOK_DEFAULT.

    Args:
        text: Message content (max 2000 chars, supports Discord markdown)
        webhook_url: Discord webhook URL (optional, falls back to default)
        username: Display name for the webhook message

    Returns:
        True on success, False on failure
    """
    target = webhook_url or DISCORD_WEBHOOK_DEFAULT
    if not target:
        log.warning('No Discord webhook URL configured — message not sent')
        return False

    # Strip HTML tags that were used for Telegram — Discord uses markdown
    import re
    clean_text = text
    clean_text = re.sub(r'<b>(.*?)</b>', r'**\1**', clean_text)
    clean_text = re.sub(r'<i>(.*?)</i>', r'*\1*', clean_text)
    clean_text = re.sub(r'<code>(.*?)</code>', r'`\1`', clean_text)
    clean_text = re.sub(r'<[^>]+>', '', clean_text)  # strip any remaining HTML

    # Discord max message length is 2000
    if len(clean_text) > 2000:
        clean_text = clean_text[:1997] + '...'

    payload = json.dumps({
        'content': clean_text,
        'username': username,
    }).encode('utf-8')

    try:
        req = Request(target, data=payload, headers={'Content-Type': 'application/json'})
        response = urlopen(req, timeout=10)
        if response.status in (200, 204):
            log.debug('Discord message sent')
            return True
        else:
            log.warning(f'Discord webhook returned status {response.status}')
            return False
    except URLError as e:
        log.error(f'Discord webhook error: {e}')
        return False
    except Exception as e:
        log.error(f'Discord send error: {e}')
        return False


def send_embed(embed: dict, webhook_url: str = '', username: str = 'Zeff.bot',
               content: str = '') -> bool:
    """
    Send a rich embed to a Discord webhook.

    Args:
        embed: Discord embed dict (title, description, color, fields, footer, etc.)
        webhook_url: Discord webhook URL
        username: Display name for the webhook message
        content: Optional text content above the embed

    Returns:
        True on success, False on failure
    """
    target = webhook_url or DISCORD_WEBHOOK_DEFAULT
    if not target:
        log.warning('No Discord webhook URL configured — embed not sent')
        return False

    payload = json.dumps({
        'content': content,
        'username': username,
        'embeds': [embed],
    }).encode('utf-8')

    try:
        req = Request(target, data=payload, headers={'Content-Type': 'application/json'})
        response = urlopen(req, timeout=10)
        if response.status in (200, 204):
            log.debug('Discord embed sent')
            return True
        else:
            log.warning(f'Discord webhook returned status {response.status}')
            return False
    except URLError as e:
        log.error(f'Discord webhook error: {e}')
        return False
    except Exception as e:
        log.error(f'Discord embed error: {e}')
        return False


def _now_str() -> str:
    """ISO timestamp in UTC."""
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')


def _now_display() -> str:
    """Human-readable timestamp."""
    return datetime.now(timezone.utc).strftime('%H:%M:%S UTC')


# =====================================================================
# CONVENIENCE FUNCTIONS — same names as telegram.py for easy migration
# =====================================================================

def send_trade_alert(direction: str, symbol: str, price: float, reason: str = '',
                     webhook_url: str = '') -> bool:
    """Send a trade alert embed."""
    is_buy = direction.upper() in ('BUY', 'LONG')
    color = COLOR_GREEN if is_buy else COLOR_RED
    emoji = '\U0001f4d7' if is_buy else '\U0001f4d5'  # 📗 / 📕

    embed = {
        'title': f'{emoji} {direction.upper()} {symbol}',
        'description': reason or 'Trade signal triggered',
        'color': color,
        'fields': [
            {'name': 'Price', 'value': f'`{price}`', 'inline': True},
        ],
        'footer': {'text': f'\u2b21 Zeff.bot | {_now_display()}'},
        'timestamp': _now_str(),
    }
    target = webhook_url or DISCORD_WEBHOOK_TRADEBOT
    return send_embed(embed, webhook_url=target)


def send_error_alert(error: str, bot_name: str = '', webhook_url: str = '') -> bool:
    """Send an error alert embed."""
    embed = {
        'title': '\u26a0\ufe0f Error' + (f' — {bot_name}' if bot_name else ''),
        'description': f'```\n{str(error)[:1500]}\n```',
        'color': COLOR_RED,
        'footer': {'text': f'\u2b21 Zeff.bot | {_now_display()}'},
        'timestamp': _now_str(),
    }
    target = webhook_url or DISCORD_WEBHOOK_ERRORS
    return send_embed(embed, webhook_url=target)


def send_status_update(balance: float, positions: int, bot_name: str = '',
                       webhook_url: str = '') -> bool:
    """Send a status update embed."""
    embed = {
        'title': f'\U0001f4ca Status Update' + (f' — {bot_name}' if bot_name else ''),
        'color': COLOR_BLUE,
        'fields': [
            {'name': 'Balance', 'value': f'`${balance:,.2f}`', 'inline': True},
            {'name': 'Open Positions', 'value': f'`{positions}`', 'inline': True},
        ],
        'footer': {'text': f'\u2b21 Zeff.bot | {_now_display()}'},
        'timestamp': _now_str(),
    }
    target = webhook_url or DISCORD_WEBHOOK_TRADEBOT
    return send_embed(embed, webhook_url=target)


def send_premium_signal(symbol: str, direction: str, price: float,
                        stop_loss: float, take_profit: float,
                        score: int = 0, layers: dict = None,
                        risk_reward: float = 0, session: str = '',
                        est_spread_pips: float = 0) -> bool:
    """
    Send a premium trading signal with full analysis breakdown.
    Routes to DISCORD_WEBHOOK_PREMIUM.
    """
    if not DISCORD_WEBHOOK_PREMIUM:
        return False

    is_buy = direction.upper() in ('BUY', 'LONG')
    color = COLOR_GREEN if is_buy else COLOR_RED
    emoji = '\U0001f4d7' if is_buy else '\U0001f4d5'
    layers = layers or {}

    # Layer breakdown
    layer_lines = []
    for key, label in [('a', 'Layer A (15M Trend)'), ('b', 'Layer B (5M Setup)'),
                       ('c', 'Layer C (1M Entry)'), ('news', 'News Bonus')]:
        val = layers.get(key, 0)
        icon = '\u2705' if val else '\u274c'
        layer_lines.append(f'{icon} {label}')

    embed = {
        'title': f'{emoji} {direction.upper()} {symbol}',
        'description': '\n'.join(layer_lines),
        'color': color,
        'fields': [
            {'name': 'Entry', 'value': f'`{price}`', 'inline': True},
            {'name': 'Stop Loss', 'value': f'`{stop_loss}`', 'inline': True},
            {'name': 'Take Profit', 'value': f'`{take_profit}`', 'inline': True},
            {'name': 'R:R', 'value': f'`1:{risk_reward:.1f}`', 'inline': True},
            {'name': 'Score', 'value': f'`{score}/7`', 'inline': True},
            {'name': 'Session', 'value': f'`{session}`', 'inline': True},
        ],
        'footer': {'text': f'\u2b21 Zeff.bot Premium | {_now_display()}'},
        'timestamp': _now_str(),
    }

    if est_spread_pips:
        embed['fields'].append({
            'name': 'Est. Spread', 'value': f'`{est_spread_pips:.1f} pips`', 'inline': True
        })

    return send_embed(embed, webhook_url=DISCORD_WEBHOOK_PREMIUM, username='Zeff.bot Premium')


def send_premium_close(symbol: str, direction: str, entry_price: float,
                       close_price: float, pnl: float, reason: str = '') -> bool:
    """
    Send a premium trade close notification with P&L.
    Routes to DISCORD_WEBHOOK_PREMIUM.
    """
    if not DISCORD_WEBHOOK_PREMIUM:
        return False

    is_win = pnl >= 0
    color = COLOR_GREEN if is_win else COLOR_RED
    result = '\u2705 WIN' if is_win else '\u274c LOSS'
    pnl_sign = '+' if pnl >= 0 else ''

    embed = {
        'title': f'{result} — {symbol} {direction.upper()} CLOSED',
        'description': reason or 'Position closed',
        'color': color,
        'fields': [
            {'name': 'Entry', 'value': f'`{entry_price}`', 'inline': True},
            {'name': 'Close', 'value': f'`{close_price}`', 'inline': True},
            {'name': 'P&L', 'value': f'**`{pnl_sign}${abs(pnl):.2f}`**', 'inline': True},
        ],
        'footer': {'text': f'\u2b21 Zeff.bot Premium | {_now_display()}'},
        'timestamp': _now_str(),
    }
    return send_embed(embed, webhook_url=DISCORD_WEBHOOK_PREMIUM, username='Zeff.bot Premium')
```

---

## PHASE 4: UPDATE `lib/zeffbot_report.py`

This file has 10 report functions that build HTML messages and call `send_message()` from telegram.py. Update it as follows:

### Step 4.1: Change the import (line 18)

Change:
```python
from lib.telegram import send_message
```
To:
```python
from lib.discord import send_message, send_embed, DISCORD_WEBHOOK_TRADEBOT, DISCORD_WEBHOOK_NATALIA, DISCORD_WEBHOOK_ERRORS, DISCORD_WEBHOOK_MARKET_SCANS, COLOR_GREEN, COLOR_RED, COLOR_BLUE, COLOR_PURPLE, COLOR_GOLD, COLOR_DARK, _now_str, _now_display
```

### Step 4.2: Rewrite each report function

Convert every `report_*` function from building an HTML string and calling `send_message(msg)` to building a Discord embed dict and calling `send_embed(embed, webhook_url=...)`.

**Mapping rules:**
- `<b>text</b>` → embed `title` or `**text**` in description
- `<i>text</i>` → `*text*` in description
- `<code>text</code>` → `` `text` `` in inline field values
- Emoji indicators → keep them in titles and field names
- HTML-escaped text → no escaping needed (Discord handles it)
- `send_message(msg)` → `send_embed(embed, webhook_url=TARGET_WEBHOOK)`

**Webhook routing for each function:**

| Function | Webhook Variable | Color |
|----------|-----------------|-------|
| `report_research_complete()` | `DISCORD_WEBHOOK_NATALIA` | `COLOR_PURPLE` |
| `report_report_complete()` | `DISCORD_WEBHOOK_NATALIA` | `COLOR_PURPLE` |
| `report_skill_installed()` | `DISCORD_WEBHOOK_NATALIA` | `COLOR_BLUE` |
| `report_trade_opened()` | `DISCORD_WEBHOOK_TRADEBOT` | `COLOR_GREEN` (BUY) or `COLOR_RED` (SELL) |
| `report_trade_closed()` | `DISCORD_WEBHOOK_TRADEBOT` | `COLOR_GREEN` (win) or `COLOR_RED` (loss) |
| `report_market_scan()` | `DISCORD_WEBHOOK_MARKET_SCANS` | `COLOR_BLUE` |
| `report_trade_analysis()` | `DISCORD_WEBHOOK_TRADEBOT` | `COLOR_BLUE` |
| `report_portfolio()` | `DISCORD_WEBHOOK_TRADEBOT` | `COLOR_DARK` |
| `report_task_failed()` | `DISCORD_WEBHOOK_ERRORS` | `COLOR_RED` |
| `report_task_completed()` | (routes to specific function above) | (varies) |

**Example conversion — `report_trade_opened()`:**

BEFORE (Telegram HTML):
```python
def report_trade_opened(result):
    direction = result.get('direction', 'BUY')
    emoji = '📗' if direction == 'BUY' else '📕'
    msg = (
        f"<b>⬡ ZEFF.BOT</b>\n"
        f"<b>{emoji} TRADE OPENED</b>\n\n"
        f"<b>{direction}</b> {result.get('symbol', '?')}\n"
        ...
    )
    send_message(msg)
```

AFTER (Discord embed):
```python
def report_trade_opened(result):
    direction = result.get('direction', 'BUY')
    is_buy = direction.upper() == 'BUY'
    emoji = '\U0001f4d7' if is_buy else '\U0001f4d5'
    symbol = result.get('symbol', '?')
    color = COLOR_GREEN if is_buy else COLOR_RED

    fields = [
        {'name': 'Entry', 'value': f"`{result.get('price', '?')}`", 'inline': True},
        {'name': 'Size', 'value': f"`{result.get('lot_size', '?')}`", 'inline': True},
    ]
    if result.get('stop_loss'):
        fields.append({'name': 'Stop Loss', 'value': f"`{result['stop_loss']}`", 'inline': True})
    if result.get('take_profit'):
        fields.append({'name': 'Take Profit', 'value': f"`{result['take_profit']}`", 'inline': True})
    if result.get('risk_reward'):
        fields.append({'name': 'R:R', 'value': f"`1:{result['risk_reward']:.1f}`", 'inline': True})

    embed = {
        'title': f'{emoji} {direction} {symbol}',
        'description': result.get('reason', ''),
        'color': color,
        'fields': fields,
        'footer': {'text': f'\u2b21 Zeff.bot TradeBot | {_now_display()}'},
        'timestamp': _now_str(),
    }
    send_embed(embed, webhook_url=DISCORD_WEBHOOK_TRADEBOT, username='Zeff.bot TradeBot')
```

Apply this same conversion pattern to ALL 10 report functions. Each one:
1. Builds an embed dict instead of an HTML string
2. Uses `send_embed()` instead of `send_message()`
3. Routes to the correct webhook URL
4. Uses the correct color constant

---

## PHASE 5: UPDATE ALL EMPLOYEE IMPORTS (9 files, 1 line each)

For each file below, change the telegram import to discord import. The function names stay the same.

### File 1: `employees/paper-trading-runner.py` (line 24)
Change:
```python
from lib.telegram import send_message as telegram_send, send_premium_signal
```
To:
```python
from lib.discord import send_message as telegram_send, send_premium_signal
```
NOTE: Keep the alias `telegram_send` so no other code in the file needs to change.

### File 2: `employees/alibot-runner.py` (line 31)
Change:
```python
from lib.telegram import send_message as telegram_send
```
To:
```python
from lib.discord import send_message as telegram_send
```

### File 3: `employees/natalia-runner.py` (line 24)
Change:
```python
from lib.telegram import send_message as _send_telegram
```
To:
```python
from lib.discord import send_message as _send_telegram
```

### File 4: `employees/polybot-runner.py` (line 50)
Change:
```python
from lib.telegram import send_message as telegram_send
```
To:
```python
from lib.discord import send_message as telegram_send
```

### File 5: `employees/kalshi-runner.py` (line 27)
Change:
```python
from lib.telegram import send_message as telegram_send
```
To:
```python
from lib.discord import send_message as telegram_send
```

### File 6: `employees/polymarket-runner.py` (line 34)
Change:
```python
from lib.telegram import send_message as telegram_send
```
To:
```python
from lib.discord import send_message as telegram_send
```

### File 7: `employees/fleet_health_monitor.py` (line 22)
Change:
```python
from lib.telegram import send_message
```
To:
```python
from lib.discord import send_message
```

### File 8: `employees/tradebot_watchdog.py` (line 32)
Change:
```python
from lib.telegram import send_message
```
To:
```python
from lib.discord import send_message
```

### File 9: `employees/morning_report.py` (line 18)
Change:
```python
from lib.telegram import send_message
```
To:
```python
from lib.discord import send_message
```

---

## PHASE 6: ARCHIVE TELEGRAM MODULE

```bash
mv /root/.openclaw/workspace/lib/telegram.py /root/.openclaw/workspace/lib/telegram_legacy.py
```

Do NOT delete it. Seth may want to dual-send or revert.

---

## PHASE 7: UPDATE DOCUMENTATION

### Step 7.1: Update `dashboard.md`

In the Infrastructure section, change:
```
| Notifications | Telegram (real-time alerts to fleet owner) |
```
To:
```
| Notifications | Discord webhooks (real-time alerts) + Telegram (OpenClaw agent chat) |
```

### Step 7.2: Update `TOOLS.md`

Add Discord to the tools list.

### Step 7.3: Update `.env.example`

Ensure all DISCORD_ variables are documented with placeholder values.

---

## PHASE 8: TESTING

### Step 8.1: Syntax check all modified files
```bash
cd /root/.openclaw/workspace
python3 -c "import lib.discord" && echo "discord.py OK"
python3 -c "import lib.zeffbot_report" && echo "zeffbot_report.py OK"
python3 -c "import importlib.util; spec = importlib.util.spec_from_file_location('test', 'employees/fleet_health_monitor.py'); print('fleet_health OK')"
python3 -c "import importlib.util; spec = importlib.util.spec_from_file_location('test', 'employees/tradebot_watchdog.py'); print('watchdog OK')"
python3 -c "import importlib.util; spec = importlib.util.spec_from_file_location('test', 'employees/morning_report.py'); print('morning_report OK')"
```

### Step 8.2: Send a test message (requires webhook URL in .env)
```python
import os, sys
sys.path.insert(0, '/root/.openclaw/workspace')
from lib.discord import send_message, send_embed, DISCORD_WEBHOOK_HEALTH, COLOR_GREEN
# Plain text test
send_message("Zeff.bot Discord integration test — if you see this, it works.", webhook_url=DISCORD_WEBHOOK_HEALTH)
# Embed test
send_embed({
    'title': 'Integration Test',
    'description': 'Discord webhook is operational.',
    'color': COLOR_GREEN,
    'fields': [
        {'name': 'Status', 'value': '`ONLINE`', 'inline': True},
        {'name': 'Mode', 'value': '`Demo`', 'inline': True},
    ],
    'footer': {'text': 'Zeff.bot Fleet'},
}, webhook_url=DISCORD_WEBHOOK_HEALTH)
```

### Step 8.3: If tests pass, restart services
```bash
sudo systemctl restart tradebot.service
sudo systemctl restart alibot.service
sudo systemctl restart natalia.service
sudo systemctl restart polybot.service
sudo systemctl restart kalshi.service
sudo systemctl restart tradebot-watchdog.service
sudo systemctl restart fleet-health.service
```

Wait 30 seconds, then check:
```bash
systemctl status tradebot.service --no-pager | head -5
systemctl status alibot.service --no-pager | head -5
systemctl status natalia.service --no-pager | head -5
systemctl status fleet-health.service --no-pager | head -5
```

All should show `active (running)`. If any service fails, check the log:
```bash
journalctl -u SERVICE_NAME -n 20 --no-pager
```

The error will likely be an import issue. Fix it and restart.

---

## PHASE 9: FINAL COMMIT

```bash
cd /root/.openclaw/workspace
git add -A
git commit -m "Migrate notification system from Telegram to Discord webhooks

- Created lib/discord.py — webhook-based notification module with rich embeds
- Updated lib/zeffbot_report.py — all 10 report functions now use Discord embeds
- Updated all 9 employee runner imports (telegram → discord)
- Archived lib/telegram_legacy.py (original Telegram module preserved)
- Added DISCORD_ environment variables to .env and .env.example
- Updated dashboard.md and documentation
- OpenClaw agent chat remains on Telegram (hybrid setup)

All bots remain in demo/paper mode. No trading logic changed."
```

Push to GitHub:
```bash
/root/.openclaw/workspace/backup_to_github.sh
```

---

## HOW TO REVERT (if anything breaks)

```bash
cd /root/.openclaw/workspace

# Restore Telegram module
mv lib/telegram_legacy.py lib/telegram.py

# Revert all import changes
git checkout HEAD~1 -- employees/paper-trading-runner.py
git checkout HEAD~1 -- employees/alibot-runner.py
git checkout HEAD~1 -- employees/natalia-runner.py
git checkout HEAD~1 -- employees/polybot-runner.py
git checkout HEAD~1 -- employees/kalshi-runner.py
git checkout HEAD~1 -- employees/polymarket-runner.py
git checkout HEAD~1 -- employees/fleet_health_monitor.py
git checkout HEAD~1 -- employees/tradebot_watchdog.py
git checkout HEAD~1 -- employees/morning_report.py
git checkout HEAD~1 -- lib/zeffbot_report.py

# Restart all services
sudo systemctl restart tradebot alibot natalia polybot kalshi tradebot-watchdog fleet-health

# Commit the revert
git add -A
git commit -m "Revert Discord migration — back to Telegram"
```

---

## BEFORE YOU START: Seth must do these manual steps first

1. **Create a Discord server** — name it "Binary Rogue" or whatever you want
2. **Create channels** matching the structure in this document
3. **Create a Discord bot** at https://discord.com/developers/applications
4. **Invite the bot** to the server with Send Messages, Embed Links, Manage Roles permissions
5. **Create webhooks** for each channel (right-click channel → Edit → Integrations → Webhooks)
6. **Paste all webhook URLs and bot token** into `/root/.openclaw/workspace/.env`
7. **Then give me the go-ahead** and I will execute Phases 3-9

## PROMPT END
