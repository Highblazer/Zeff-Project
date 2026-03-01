#!/usr/bin/env python3
"""
TradeBot with Telegram Notifications
"""

import json
import os
import subprocess
from datetime import datetime

def telegram_notify(bot_name, message):
    """Send Telegram notification"""
    full_msg = f"🔔 *{bot_name}*\n{message}"
    
    # Write to a notification file that can be picked up
    notif_file = '/tmp/trade_notification.txt'
    with open(notif_file, 'a') as f:
        f.write(f"{datetime.now().isoformat()} | {full_msg}\n")
    
    print(f"🔔 {full_msg}")
    return full_msg

# Test
if __name__ == "__main__":
    telegram_notify("TradeBot", "BUY EURUSD @ 1.1850 - 10% risk")
