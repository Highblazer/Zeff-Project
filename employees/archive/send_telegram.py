#!/usr/bin/env python3
import sys
sys.path.insert(0, '/root/.openclaw/workspace')

# This simulates sending a telegram - in practice would use the message tool
def send_trade_alert(bot_name, message):
    """Send trade alert to Telegram"""
    alert_msg = f"🔔 *{bot_name}*\n{message}"
    print(f"TELEGRAM: {alert_msg}")
    return alert_msg

if __name__ == "__main__":
    import json
    msg = json.dumps({"action": "send", "message": "Test trade alert"})
    print(msg)
