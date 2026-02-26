#!/usr/bin/env python3
"""
Morning Report — Sends a comprehensive overnight summary to Telegram.
Covers: TradeBot activity, Natalia research, system health.
Runs via cron at 07:00 CET daily.
"""

import json
import os
import sys
import glob
import html
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '/root/.openclaw/workspace')
from lib.credentials import _load_dotenv
_load_dotenv()
from lib.telegram import send_message

CET = timezone(timedelta(hours=1))


def _load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def _get_trading_summary():
    """Summarize TradeBot overnight activity."""
    state = _load_json('/root/.openclaw/workspace/employees/trading_state.json')
    balance = state.get('balance', 0)
    positions = state.get('positions', {})
    open_count = len(positions)

    # Count closed trades from log (last 12 hours)
    closed_count = 0
    errors = 0
    fills = 0
    try:
        with open('/var/log/tradebot.log') as f:
            cutoff = datetime.now() - timedelta(hours=12)
            for line in f:
                if '[CLOSED]' in line:
                    closed_count += 1
                if '[FILL]' in line:
                    fills += 1
                if '[ORDER ERROR]' in line:
                    errors += 1
    except Exception:
        pass

    # List open positions
    pos_lines = []
    for pid, pos in positions.items():
        sym = pos.get('symbol', '?')
        side = pos.get('side', '?')
        entry = pos.get('entry_price', 0)
        emoji = '📗' if side == 'BUY' else '📕'
        pos_lines.append(f"  {emoji} {side} {sym} @ {entry}")

    return {
        'balance': balance,
        'open_count': open_count,
        'closed_count': closed_count,
        'fills': fills,
        'errors': errors,
        'positions': pos_lines,
    }


def _get_natalia_summary():
    """Summarize Natalia's overnight research."""
    completed_dir = '/root/.openclaw/workspace/tasks/completed/'
    tasks_done = 0
    topics = []
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=12)
        for f in sorted(glob.glob(os.path.join(completed_dir, '*.json')), reverse=True):
            task = _load_json(f)
            if task.get('assigned_to') != 'natalia':
                continue
            completed_at = task.get('completed_at', '')
            if completed_at:
                try:
                    t = datetime.fromisoformat(completed_at.replace('Z', '+00:00'))
                    if t < cutoff:
                        continue
                except Exception:
                    pass
            tasks_done += 1
            title = task.get('title', '?')
            if len(topics) < 8:
                topics.append(f"  • {title[:60]}")
    except Exception:
        pass

    return {
        'tasks_done': tasks_done,
        'topics': topics,
    }


def _get_system_health():
    """Check service health."""
    services = {}
    for svc in ['tradebot', 'tradebot-watchdog', 'natalia']:
        try:
            ret = os.popen(f'systemctl is-active {svc}.service 2>/dev/null').read().strip()
            services[svc] = ret == 'active'
        except Exception:
            services[svc] = False
    return services


def _get_news_summary():
    """Get latest news intel summary."""
    feed = _load_json('/root/.openclaw/workspace/news/feed.json')
    article_count = feed.get('article_count', 0)
    last_collected = feed.get('last_collection_at', 'never')
    return {
        'article_count': article_count,
        'last_collected': last_collected[:16] if last_collected != 'never' else 'never',
    }


def send_morning_report():
    trade = _get_trading_summary()
    natalia = _get_natalia_summary()
    health = _get_system_health()
    news = _get_news_summary()

    now = datetime.now(CET)
    date_str = now.strftime('%A, %B %d %Y')

    # Build message
    msg = "<b>⬡ ZEFF.BOT</b>\n"
    msg += f"<b>☀️ MORNING BRIEFING</b>\n"
    msg += f"<i>{date_str}</i>\n\n"

    # System health
    all_ok = all(health.values())
    status_emoji = '🟢' if all_ok else '🔴'
    msg += f"<b>{status_emoji} SYSTEM STATUS</b>\n"
    for svc, ok in health.items():
        icon = '✅' if ok else '❌'
        msg += f"  {icon} {svc}\n"
    msg += "\n"

    # TradeBot
    msg += "<b>🤖 TRADEBOT — Overnight</b>\n"
    msg += f"  Balance: ${trade['balance']:.2f}\n"
    msg += f"  Open positions: {trade['open_count']}\n"
    msg += f"  Trades executed: {trade['fills']}\n"
    msg += f"  Positions closed: {trade['closed_count']}\n"
    if trade['errors'] > 0:
        msg += f"  Order errors: {trade['errors']}\n"
    if trade['positions']:
        msg += "  <b>Active:</b>\n"
        for p in trade['positions'][:5]:
            msg += f"  {html.escape(p)}\n"
        if len(trade['positions']) > 5:
            msg += f"  ... +{len(trade['positions']) - 5} more\n"
    msg += "\n"

    # Natalia
    msg += "<b>📡 NATALIA — Overnight</b>\n"
    msg += f"  Research tasks completed: {natalia['tasks_done']}\n"
    if natalia['topics']:
        msg += "  <b>Topics:</b>\n"
        for t in natalia['topics']:
            msg += f"  {html.escape(t)}\n"
    msg += "\n"

    # News
    msg += "<b>📰 NEWS INTEL</b>\n"
    msg += f"  Articles in feed: {news['article_count']}\n"
    msg += f"  Last collected: {news['last_collected']}\n\n"

    msg += "<i>Fleet operational. Ready for your command.</i>"

    send_message(msg)
    print(f"Morning report sent at {now.isoformat()}")


if __name__ == '__main__':
    send_morning_report()
