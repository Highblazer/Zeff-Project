#!/usr/bin/env python3
"""Send Telegram alerts"""

import os
import sys

# Use the message module to send alerts
def alert(bot_name, message):
    """Send trade alert"""
    full_msg = f"🔔 *{bot_name}*\n{message}"
    print(f"ALERT: {full_msg}")
    return full_msg

if __name__ == "__main__":
    alert("Test", "This is a test alert")
