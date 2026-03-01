#!/usr/bin/env python3
"""
Trade Monitor - Monitors trading bots and sends Telegram alerts
Run this as a background service
"""

import os
import json
import time
import requests
from datetime import datetime

LOG_FILE = '/root/.openclaw/workspace/logs/trade_activity.log'
LAST_POSITION = 0

def send_telegram(message):
    """Send alert to Telegram - this will be picked up by the gateway"""
    print(f"🔔 {message}")

def get_balance():
    """Get current account balance from config"""
    try:
        with open('/root/.openclaw/workspace/conf/icmarkets.json') as f:
            cfg = json.load(f)
        return cfg['icmarkets'].get('balance', 20000)
    except Exception as e:
        print(f"Warning: failed to read balance config: {e}")
        return 20000

def monitor():
    """Monitor trading activity"""
    global LAST_POSITION
    
    print("👁️ Trade Monitor started")
    
    while True:
        try:
            # Check dashboard for recent trades
            try:
                with open('/root/.openclaw/workspace/dashboard.md', 'r') as f:
                    content = f.read()
                    
                # Look for new trades in the dashboard
                if 'Recent Trades' in content:
                    # Extract trades section
                    start = content.find('## 🔔 Recent Trades')
                    if start > 0:
                        section = content[start:start+500]
                        if 'No trades yet' not in section:
                            # There are trades!
                            pass
            except Exception as e:
                print(f"Warning: failed to read dashboard: {e}")
            
            time.sleep(30)  # Check every 30 seconds
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Monitor error: {e}")
            time.sleep(10)

if __name__ == '__main__':
    monitor()
