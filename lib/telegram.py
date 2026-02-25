#!/usr/bin/env python3
"""
Unified Telegram notification module for OpenClaw.
Replaces: send_alert.py, send_telegram.py, trade_alerts.py, telegram_notify.py
"""

import os
import json
import logging
from urllib.request import urlopen, Request
from urllib.error import URLError

logger = logging.getLogger('telegram')

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')


def send_message(text: str, chat_id: str = None, parse_mode: str = 'HTML') -> bool:
    """Send a Telegram message.

    Args:
        text: Message text (supports HTML formatting).
        chat_id: Override default chat ID.
        parse_mode: 'HTML' or 'Markdown'.

    Returns True on success.
    """
    token = BOT_TOKEN or os.environ.get('TELEGRAM_BOT_TOKEN', '')
    target = chat_id or CHAT_ID or os.environ.get('TELEGRAM_CHAT_ID', '')

    if not token:
        logger.warning(f"Telegram not configured (no TELEGRAM_BOT_TOKEN). Message: {text[:100]}")
        return False

    if not target:
        logger.warning(f"No TELEGRAM_CHAT_ID configured. Message: {text[:100]}")
        return False

    url = f'https://api.telegram.org/bot{token}/sendMessage'
    payload = json.dumps({
        'chat_id': target,
        'text': text,
        'parse_mode': parse_mode,
    }).encode('utf-8')

    req = Request(url, data=payload, headers={'Content-Type': 'application/json'})

    try:
        with urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                logger.info(f"Telegram message sent to {target}")
                return True
            else:
                logger.error(f"Telegram API returned {resp.status}")
                return False
    except URLError as e:
        logger.error(f"Telegram send failed: {e}")
        return False


def send_trade_alert(direction: str, symbol: str, price: float, reason: str = ""):
    """Send a formatted trade alert."""
    msg = (
        f"<b>Trade Alert</b>\n"
        f"<b>{direction}</b> {symbol} @ {price:.5f}\n"
    )
    if reason:
        msg += f"Reason: {reason}\n"
    return send_message(msg)


def send_error_alert(error: str, bot_name: str = ""):
    """Send an error notification."""
    source = f" ({bot_name})" if bot_name else ""
    return send_message(f"<b>Error{source}</b>\n{error}")


def send_status_update(balance: float, positions: int, bot_name: str = ""):
    """Send a status update."""
    source = f" - {bot_name}" if bot_name else ""
    return send_message(
        f"<b>Status Update{source}</b>\n"
        f"Balance: ${balance:.2f}\n"
        f"Open Positions: {positions}"
    )
