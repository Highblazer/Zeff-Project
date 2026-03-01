#!/bin/bash
# TradeBot Supervisor - Keeps TradeBot running 24/5

LOG_FILE="/root/.openclaw/workspace/logs/tradebot_supervisor.log"
BOT_SCRIPT="/root/.openclaw/workspace/employees/tradebot_robust.py"
MAX_RESTARTS=100
RESTART_DELAY=5

echo "TradeBot Supervisor starting..." | tee -a $LOG_FILE

restart_count=0

while [ $restart_count -lt $MAX_RESTARTS ]; do
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Starting TradeBot (attempt $((restart_count+1)))" | tee -a $LOG_FILE
    
    # Run TradeBot
    python3 "$BOT_SCRIPT" >> $LOG_FILE 2>&1
    EXIT_CODE=$?
    
    echo "$(date '+%Y-%m-%d %H:%M:%S') - TradeBot exited with code $EXIT_CODE" | tee -a $LOG_FILE
    
    restart_count=$((restart_count + 1))
    
    if [ $restart_count -lt $MAX_RESTARTS ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') - Restarting in $RESTART_DELAY seconds..." | tee -a $LOG_FILE
        sleep $RESTART_DELAY
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S') - Max restarts reached, exiting" | tee -a $LOG_FILE
    fi
done

echo "TradeBot Supervisor stopped" | tee -a $LOG_FILE
