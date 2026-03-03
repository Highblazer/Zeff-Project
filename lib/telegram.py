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


# ── Premium Signal Channel ──

PREMIUM_CHAT_ID = os.environ.get('TELEGRAM_PREMIUM_CHAT_ID', '')


def send_premium_signal(
    symbol: str,
    direction: str,
    price: float,
    stop_loss: float,
    take_profit: float,
    score: int,
    layers: dict,
    risk_reward: float = 3.0,
    session: str = "",
    est_spread_pips: float = 0,
):
    """Send a detailed premium signal to the paid Telegram channel.

    Includes entry/SL/TP, layer breakdown (VP/LS/VW/OF/News), and R:R after spread.
    """
    premium_id = PREMIUM_CHAT_ID or os.environ.get('TELEGRAM_PREMIUM_CHAT_ID', '')
    if not premium_id:
        logger.info("Premium channel not configured (no TELEGRAM_PREMIUM_CHAT_ID)")
        return False

    arrow = "BUY" if direction == 'BUY' else "SELL"

    msg = (
        f"<b>PREMIUM SIGNAL</b>\n"
        f"<b>{arrow} {symbol}</b>\n\n"
        f"Entry: <code>{price:.5f}</code>\n"
        f"Stop Loss: <code>{stop_loss:.5f}</code>\n"
        f"Take Profit: <code>{take_profit:.5f}</code>\n\n"
        f"<b>Signal Score:</b> {score}/10\n"
        f"  Volume Profile: {layers.get('vp', 0)}/2\n"
        f"  Liquidity Sweep: {layers.get('ls', 0)}/3\n"
        f"  Anchored VWAP: {layers.get('vw', 0)}/2\n"
        f"  Order Flow: {layers.get('of', 0)}/2\n"
        f"  News: {layers.get('news', 0)}/1\n\n"
        f"R:R (after spread): <b>1:{risk_reward:.1f}</b>\n"
    )
    if est_spread_pips:
        msg += f"Est. Spread: {est_spread_pips} pips\n"
    if session:
        msg += f"Session: {session}\n"

    msg += f"\n<i>{_now_str()}</i>"

    return send_message(msg, chat_id=premium_id)


def send_premium_close(
    symbol: str,
    direction: str,
    entry_price: float,
    close_price: float,
    pnl: float,
    reason: str = "",
):
    """Notify the premium channel about a trade close."""
    premium_id = PREMIUM_CHAT_ID or os.environ.get('TELEGRAM_PREMIUM_CHAT_ID', '')
    if not premium_id:
        return False

    result = "WIN" if pnl > 0 else "LOSS"
    msg = (
        f"<b>TRADE CLOSED — {result}</b>\n"
        f"{direction} {symbol}\n"
        f"Entry: {entry_price:.5f} -> Close: {close_price:.5f}\n"
        f"P&L: <b>${pnl:+.2f}</b>\n"
    )
    if reason:
        msg += f"Reason: {reason}\n"
    msg += f"\n<i>{_now_str()}</i>"

    return send_message(msg, chat_id=premium_id)


def _now_str():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
