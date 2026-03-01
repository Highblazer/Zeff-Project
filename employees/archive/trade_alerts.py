#!/usr/bin/env python3
"""Telegram notifications for trading bots"""

import os
import sys
sys.path.insert(0, '/root/.openclaw/workspace')

# This will be called by the trading bots
def send_trade_alert(bot_name, message):
    """Send trade alert to Telegram"""
    alert = f"🔔 *{bot_name}*\n{message}"
    print(f"TELEGRAM_ALERT: {alert}")
    return alert

if __name__ == "__main__":
    # Test
    send_trade_alert("TradeBot", "BUY EURUSD @ 1.1850")
