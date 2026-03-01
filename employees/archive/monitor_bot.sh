#!/bin/bash
# TradeBot Monitor - Restarts bot if not running

BOT_SCRIPT="/root/.openclaw/workspace/employees/tradebot_kalshi.py"
LOG_FILE="/root/.openclaw/workspace/logs/kalshi.log"
STATUS_FILE="/root/.openclaw/workspace/employees/kalshi_status.json"
MAX_MINUTES=3

# Check if bot is running
if ! pgrep -f "tradebot_kalshi" > /dev/null; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Bot not running, restarting..." >> /root/.openclaw/workspace/logs/monitor.log
    
    # Start bot
    nohup python3 -u "$BOT_SCRIPT" > "$LOG_FILE" 2>&1 &
    
    sleep 5
    
    if pgrep -f "tradebot_kalshi" > /dev/null; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') - Bot restarted successfully" >> /root/.openclaw/workspace/logs/monitor.log
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S') - FAILED to restart bot!" >> /root/.openclaw/workspace/logs/monitor.log
    fi
else
    # Check last update time
    if [ -f "$STATUS_FILE" ]; then
        LAST_UPDATE=$(stat -c %Y "$STATUS_FILE" 2>/dev/null || echo "0")
        NOW=$(date +%s)
        DIFF=$((NOW - LAST_UPDATE))
        MINUTES=$((DIFF / 60))
        
        if [ $MINUTES -gt $MAX_MINUTES ]; then
            echo "$(date '+%Y-%m-%d %H:%M:%S') - Bot stale (no update in $MINUTES min), restarting..." >> /root/.openclaw/workspace/logs/monitor.log
            pkill -f "tradebot_kalshi"
            sleep 2
            nohup python3 -u "$BOT_SCRIPT" > "$LOG_FILE" 2>&1 &
        fi
    fi
fi

# Log status
echo "$(date '+%Y-%m-%d %H:%M:%S') - Monitor check complete" >> /root/.openclaw/workspace/logs/monitor.log
