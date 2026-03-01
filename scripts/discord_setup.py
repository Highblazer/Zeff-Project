#!/usr/bin/env python3
"""
Discord Server Setup Automation for Zeff.bot Fleet.

This script creates the full Discord server structure (categories, channels,
webhooks) via the Discord REST API, then writes all webhook URLs to .env.

PREREQUISITES (user must do manually):
1. Create a Discord server
2. Create a Discord bot at https://discord.com/developers/applications
3. Enable Message Content Intent in bot settings
4. Invite bot to server with permissions integer 805421072
   (Manage Channels, Manage Roles, Manage Webhooks, View Channel,
    Send Messages, Embed Links, Attach Files, Read Message History)
5. Get: Bot Token, Server (Guild) ID, Owner User ID

USAGE:
    python3 discord_setup.py <BOT_TOKEN> <GUILD_ID> <OWNER_USER_ID>

Or set environment variables:
    DISCORD_BOT_TOKEN, DISCORD_GUILD_ID, DISCORD_OWNER_ID
"""

import json
import os
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# ─── Discord API ───────────────────────────────────────────────
API_BASE = "https://discord.com/api/v10"

# Permission bit flags
VIEW_CHANNEL         = 1 << 10   # 1024
SEND_MESSAGES        = 1 << 11   # 2048
EMBED_LINKS          = 1 << 14   # 16384
ATTACH_FILES         = 1 << 15   # 32768
READ_MESSAGE_HISTORY = 1 << 16   # 65536
MANAGE_CHANNELS      = 1 << 4    # 16
MANAGE_ROLES         = 1 << 28   # 268435456
MANAGE_WEBHOOKS      = 1 << 29   # 536870912

OWNER_PERMS = VIEW_CHANNEL | SEND_MESSAGES | EMBED_LINKS | ATTACH_FILES | READ_MESSAGE_HISTORY
# = 117760

# ─── Server Structure ──────────────────────────────────────────
# (category_name, is_private, [(channel_name, topic, webhook_env_var or None)])
SERVER_STRUCTURE = [
    ("INFORMATION", False, [
        ("welcome",        "Welcome to the Zeff.bot fleet", None),
        ("announcements",  "Fleet-wide announcements",      None),
        ("fleet-status",   "Live fleet health overview",     None),
    ]),
    ("TRADING SIGNALS", False, [
        ("tradebot-signals", "TradeBot paper trading signals",   "DISCORD_WEBHOOK_TRADEBOT"),
        ("alibot-signals",   "Ali.bot higher-TF precision",     "DISCORD_WEBHOOK_ALIBOT"),
        ("market-scans",     "Market scanning results",         "DISCORD_WEBHOOK_MARKET_SCANS"),
    ]),
    ("PREDICTIONS", False, [
        ("polybot-signals",  "Poly.Bot prediction market trades",  "DISCORD_WEBHOOK_POLYBOT"),
        ("kalshi-signals",   "Kalshi prediction market trades",    "DISCORD_WEBHOOK_KALSHI"),
    ]),
    ("INTELLIGENCE", False, [
        ("natalia-research", "Natalia CRO research & reports",  "DISCORD_WEBHOOK_NATALIA"),
        ("news-feed",       "Automated news intelligence",      None),
    ]),
    ("OPERATIONS", True, [  # Private — owner only
        ("fleet-health",     "Fleet health monitor alerts",       "DISCORD_WEBHOOK_HEALTH"),
        ("watchdog",         "TradeBot watchdog alerts",          None),
        ("morning-briefing", "Daily morning digest + improvements", "DISCORD_WEBHOOK_MORNING"),
        ("errors",           "Error alerts from all bots",        "DISCORD_WEBHOOK_ERRORS"),
    ]),
    ("PREMIUM", False, [
        ("premium-entries",  "Premium trading signals (role-locked)", "DISCORD_WEBHOOK_PREMIUM"),
        ("premium-results",  "Premium trade results & P&L",          None),
    ]),
    ("COMMUNITY", False, [
        ("general",      "General discussion",   None),
        ("trade-ideas",  "Share trade ideas",     None),
    ]),
]

# ─── API Helpers ───────────────────────────────────────────────

def api_request(method, endpoint, body=None, bot_token=""):
    """Make a rate-limit-aware Discord API request."""
    url = f"{API_BASE}{endpoint}"
    headers = {
        "Authorization": f"Bot {bot_token}",
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode("utf-8") if body else None
    req = Request(url, data=data, headers=headers, method=method)

    try:
        resp = urlopen(req, timeout=15)
        return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        if e.code == 429:
            retry = json.loads(e.read().decode("utf-8"))
            wait = retry.get("retry_after", 2.0)
            print(f"  Rate limited — waiting {wait}s...")
            time.sleep(wait)
            resp = urlopen(Request(url, data=data, headers=headers, method=method), timeout=15)
            return json.loads(resp.read().decode("utf-8"))
        else:
            body_text = e.read().decode("utf-8") if e.fp else ""
            print(f"  ERROR {e.code}: {body_text}")
            raise
    except URLError as e:
        print(f"  Network error: {e}")
        raise


def create_category(guild_id, bot_token, name, private=False, owner_id=None):
    """Create a channel category."""
    payload = {"name": name, "type": 4}
    if private and owner_id:
        payload["permission_overwrites"] = [
            {"id": guild_id, "type": 0, "allow": "0", "deny": str(VIEW_CHANNEL)},
            {"id": owner_id, "type": 1, "allow": str(OWNER_PERMS), "deny": "0"},
        ]
    return api_request("POST", f"/guilds/{guild_id}/channels", payload, bot_token)


def create_text_channel(guild_id, bot_token, name, category_id, topic="",
                        private=False, owner_id=None):
    """Create a text channel under a category."""
    payload = {
        "name": name,
        "type": 0,
        "parent_id": category_id,
        "topic": topic,
    }
    if private and owner_id:
        payload["permission_overwrites"] = [
            {"id": guild_id, "type": 0, "allow": "0", "deny": str(VIEW_CHANNEL)},
            {"id": owner_id, "type": 1, "allow": str(OWNER_PERMS), "deny": "0"},
        ]
    return api_request("POST", f"/guilds/{guild_id}/channels", payload, bot_token)


def create_webhook(channel_id, bot_token, name="Zeff.bot"):
    """Create a webhook and return its URL."""
    data = api_request("POST", f"/channels/{channel_id}/webhooks",
                       {"name": name}, bot_token)
    return f"https://discord.com/api/webhooks/{data['id']}/{data['token']}"


def send_test_message(webhook_url):
    """Send a test embed to verify webhook works."""
    payload = json.dumps({
        "username": "Zeff.bot",
        "embeds": [{
            "title": "Fleet Online",
            "description": (
                "Discord integration is **active**.\n\n"
                "All channels created. All webhooks configured.\n"
                "Your fleet is ready for Discord."
            ),
            "color": 3066993,  # green
            "fields": [
                {"name": "Status", "value": "`ONLINE`", "inline": True},
                {"name": "Mode", "value": "`Paper Trading`", "inline": True},
                {"name": "Services", "value": "`10 active`", "inline": True},
            ],
            "footer": {"text": "Zeff.bot Fleet Health Monitor"},
        }],
    }).encode("utf-8")
    req = Request(webhook_url, data=payload,
                  headers={"Content-Type": "application/json"})
    resp = urlopen(req, timeout=10)
    return resp.status in (200, 204)


# ─── Main ──────────────────────────────────────────────────────

def main():
    # Get credentials from args or env
    if len(sys.argv) == 4:
        bot_token, guild_id, owner_id = sys.argv[1], sys.argv[2], sys.argv[3]
    else:
        bot_token = os.environ.get("DISCORD_BOT_TOKEN", "")
        guild_id = os.environ.get("DISCORD_GUILD_ID", "")
        owner_id = os.environ.get("DISCORD_OWNER_ID", "")

    if not all([bot_token, guild_id, owner_id]):
        print("Usage: python3 discord_setup.py <BOT_TOKEN> <GUILD_ID> <OWNER_USER_ID>")
        print("   Or set DISCORD_BOT_TOKEN, DISCORD_GUILD_ID, DISCORD_OWNER_ID env vars")
        sys.exit(1)

    print("=" * 60)
    print("  ZEFF.BOT DISCORD SERVER SETUP")
    print("=" * 60)
    print(f"  Guild: {guild_id}")
    print(f"  Owner: {owner_id}")
    print()

    # Verify bot can reach the guild
    print("[1/4] Verifying bot access...")
    try:
        guild = api_request("GET", f"/guilds/{guild_id}", bot_token=bot_token)
        print(f"  Connected to: {guild['name']}")
    except Exception as e:
        print(f"  FAILED: Cannot access guild. Check bot token and guild ID.")
        print(f"  Error: {e}")
        sys.exit(1)

    # Create all categories and channels
    print("\n[2/4] Creating categories and channels...")
    webhook_env_vars = {}  # env_var_name -> webhook_url

    for cat_name, is_private, channels in SERVER_STRUCTURE:
        privacy_tag = " (private)" if is_private else ""
        print(f"\n  Creating category: {cat_name}{privacy_tag}")
        cat = create_category(guild_id, bot_token, cat_name,
                              private=is_private, owner_id=owner_id)
        cat_id = cat["id"]
        time.sleep(0.5)

        for ch_name, ch_topic, webhook_var in channels:
            print(f"    #{ch_name}", end="")
            ch = create_text_channel(guild_id, bot_token, ch_name, cat_id,
                                     topic=ch_topic, private=is_private,
                                     owner_id=owner_id)
            ch_id = ch["id"]

            if webhook_var:
                wh_url = create_webhook(ch_id, bot_token, name="Zeff.bot")
                webhook_env_vars[webhook_var] = wh_url
                print(f" + webhook ({webhook_var})")
                time.sleep(0.3)
            else:
                print(" (no webhook needed)")

            time.sleep(0.3)

    # Write to .env
    print("\n[3/4] Writing credentials to .env...")
    env_path = "/root/.openclaw/workspace/.env"

    env_block = "\n\n# === DISCORD (auto-generated by discord_setup.py) ===\n"
    env_block += f"DISCORD_BOT_TOKEN={bot_token}\n"
    env_block += f"DISCORD_GUILD_ID={guild_id}\n"
    env_block += f"DISCORD_OWNER_ID={owner_id}\n"
    for var_name, url in sorted(webhook_env_vars.items()):
        env_block += f"{var_name}={url}\n"

    with open(env_path, "a") as f:
        f.write(env_block)
    print(f"  Written {3 + len(webhook_env_vars)} variables to {env_path}")

    # Send test message
    print("\n[4/4] Sending test message to #fleet-health...")
    health_url = webhook_env_vars.get("DISCORD_WEBHOOK_HEALTH", "")
    if health_url:
        try:
            send_test_message(health_url)
            print("  Test message sent! Check your #fleet-health channel.")
        except Exception as e:
            print(f"  Test message failed: {e}")
    else:
        print("  No health webhook found — skipping test.")

    # Summary
    print("\n" + "=" * 60)
    print("  SETUP COMPLETE")
    print("=" * 60)
    print(f"  Categories created: {len(SERVER_STRUCTURE)}")
    total_channels = sum(len(channels) for _, _, channels in SERVER_STRUCTURE)
    print(f"  Channels created:   {total_channels}")
    print(f"  Webhooks created:   {len(webhook_env_vars)}")
    print(f"  Env vars written:   {3 + len(webhook_env_vars)}")
    print()
    print("  NEXT STEP:")
    print("  Run the Discord migration prompt to update all bot code:")
    print("  → /root/.openclaw/workspace/docs/DISCORD_MIGRATION_PROMPT.md")
    print()
    print("  Or just tell Zeff.bot: 'Run the Discord migration'")
    print("=" * 60)

    return webhook_env_vars


if __name__ == "__main__":
    main()
