# OpenClaw Runbook

Operational procedures for managing the OpenClaw trading platform.

---

## 1. How to Rotate Credentials

### IC Markets API Credentials

1. **Generate new credentials** in the IC Markets cTrader portal (Settings > API).

2. **Update the `.env` file** at `/root/.openclaw/workspace/.env`:
   ```bash
   # Edit the .env file
   nano /root/.openclaw/workspace/.env

   # Update these values with the new credentials:
   ICM_CLIENT_ID=<new_client_id>
   ICM_API_SECRET=<new_api_secret>
   ICM_ACCESS_TOKEN=<new_access_token>
   ICM_REFRESH_TOKEN=<new_refresh_token>
   ICM_TRADING_PASSWORD=<new_password>
   ```

3. **Activate the kill switch** before restarting to prevent trades during the transition:
   ```bash
   python3 -c "
   import sys; sys.path.insert(0, '/root/.openclaw/workspace')
   from lib.trading_safety import activate_kill_switch
   activate_kill_switch('Credential rotation in progress')
   "
   ```

4. **Restart the trading bot** (see Section 3 below).

5. **Verify connectivity** by checking logs:
   ```bash
   tail -f /root/.openclaw/workspace/logs/paper_trading.log
   ```

6. **Deactivate the kill switch** once connectivity is confirmed (see Section 2 below).

### Telegram Bot Token

1. Create a new bot via BotFather on Telegram (or regenerate the token).
2. Update `TELEGRAM_BOT_TOKEN` in `.env`.
3. Restart any running bots. No kill switch needed since Telegram is alerting only.

### Brave Search API Key

1. Generate a new key at the Brave Search API dashboard.
2. Update `BRAVE_API_KEY` in `.env`.
3. Restart the agent process.

### Important Notes

- Never commit `.env` to version control.
- After rotation, verify the old credentials are revoked in the provider's portal.
- Keep a secure backup of credentials outside the server.

---

## 2. How to Activate/Deactivate the Kill Switch

The kill switch is a file-based mechanism. When the file `/root/.openclaw/workspace/STOP_TRADING` exists, all trading bots halt immediately on their next cycle.

### Activate (Stop All Trading)

**Option A -- Command line:**
```bash
python3 -c "
import sys; sys.path.insert(0, '/root/.openclaw/workspace')
from lib.trading_safety import activate_kill_switch
activate_kill_switch('Manual activation -- <reason>')
"
```

**Option B -- Direct file creation (works even if Python is broken):**
```bash
echo '{"activated": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'", "reason": "Emergency stop"}' > /root/.openclaw/workspace/STOP_TRADING
```

### Deactivate (Resume Trading)

**Option A -- Command line:**
```bash
python3 -c "
import sys; sys.path.insert(0, '/root/.openclaw/workspace')
from lib.trading_safety import deactivate_kill_switch
deactivate_kill_switch()
"
```

**Option B -- Direct file removal:**
```bash
rm /root/.openclaw/workspace/STOP_TRADING
```

### Verify Kill Switch Status

```bash
if [ -f /root/.openclaw/workspace/STOP_TRADING ]; then
    echo "KILL SWITCH IS ACTIVE:"
    cat /root/.openclaw/workspace/STOP_TRADING
else
    echo "Kill switch is NOT active. Trading is allowed."
fi
```

---

## 3. How to Start/Stop Trading Bots

### Start the Paper Trading Bot

```bash
cd /root/.openclaw/workspace
nohup python3 employees/paper-trading-runner.py > /dev/null 2>&1 &
echo $! > /tmp/paper-trading.pid
```

Or use the supervisor script:
```bash
bash /root/.openclaw/workspace/employees/tradebot_supervisor.sh
```

### Stop the Paper Trading Bot

**Graceful stop (preferred) -- activate the kill switch:**
```bash
python3 -c "
import sys; sys.path.insert(0, '/root/.openclaw/workspace')
from lib.trading_safety import activate_kill_switch
activate_kill_switch('Planned shutdown')
"
```
The bot will halt on its next check cycle (within ~60 seconds).

**Immediate stop -- kill the process:**
```bash
# If PID file exists:
kill $(cat /tmp/paper-trading.pid)

# Otherwise, find and kill:
ps aux | grep paper-trading-runner | grep -v grep
kill <PID>
```

### Start the Streamlit Dashboard

```bash
cd /root/.openclaw/workspace
nohup streamlit run python/streamlit_dashboard.py --server.port 8501 > /dev/null 2>&1 &
```

### Start the System Monitor

```bash
nohup python3 /root/.openclaw/workspace/system-monitor.py > /dev/null 2>&1 &
```

---

## 4. How to Check System Health

### Quick Status Check

```bash
# Check if trading bot is running
ps aux | grep paper-trading-runner | grep -v grep

# Check if dashboard is running
ps aux | grep streamlit | grep -v grep

# Check kill switch status
test -f /root/.openclaw/workspace/STOP_TRADING && echo "KILL SWITCH ACTIVE" || echo "Kill switch off"

# Check system resources
python3 -c "
import psutil
print(f'CPU: {psutil.cpu_percent()}%')
print(f'Memory: {psutil.virtual_memory().percent}%')
print(f'Disk: {psutil.disk_usage(\"/\").percent}%')
"
```

### Check Trading State

```bash
# View current trading state
python3 -c "
import json
with open('/root/.openclaw/workspace/paper-trading-state.json') as f:
    state = json.load(f)
print(f'Balance: \${state.get(\"balance\", 0):.2f}')
print(f'Open positions: {len(state.get(\"positions\", {}))}')
print(f'Total trades: {state.get(\"stats\", {}).get(\"total\", 0)}')
print(f'Win rate: {state.get(\"stats\", {}).get(\"win_rate\", 0)}%')
print(f'Last update: {state.get(\"last_update\", \"unknown\")}')
"
```

### Check Logs

```bash
# Recent trading bot logs
tail -50 /root/.openclaw/workspace/logs/paper_trading.log

# Recent errors across all logs
grep -i "error\|exception\|fail" /root/.openclaw/workspace/logs/*.log | tail -20

# Supervisor logs
tail -20 /root/.openclaw/workspace/logs/supervisor.log
```

### Check Trading Status File

```bash
cat /root/.openclaw/workspace/employees/trading_status.json
```

---

## 5. Emergency Procedures

### Scenario: Unexpected Large Loss

1. **Immediately activate the kill switch:**
   ```bash
   echo '{"activated": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'", "reason": "Unexpected loss"}' > /root/.openclaw/workspace/STOP_TRADING
   ```

2. **Verify all bots have stopped** (check logs stop producing trade entries):
   ```bash
   tail -f /root/.openclaw/workspace/logs/paper_trading.log
   ```

3. **Check current positions and balance:**
   ```bash
   cat /root/.openclaw/workspace/paper-trading-state.json | python3 -m json.tool
   ```

4. **Manually close any open positions** via the IC Markets cTrader web interface or the Streamlit dashboard.

5. **Investigate the cause** by reviewing recent logs:
   ```bash
   grep -A5 "TRADE OPENED\|TRADE CLOSED" /root/.openclaw/workspace/logs/paper_trading.log | tail -50
   ```

6. **Do not deactivate the kill switch** until the root cause is understood and addressed.

### Scenario: Bot Crash / Unresponsive

1. **Check if the process is running:**
   ```bash
   ps aux | grep paper-trading-runner | grep -v grep
   ```

2. **Check logs for the crash cause:**
   ```bash
   tail -100 /root/.openclaw/workspace/logs/paper_trading.log
   ```

3. **If the process is zombie/stuck, kill it:**
   ```bash
   kill -9 <PID>
   ```

4. **Restart the bot** (see Section 3).

### Scenario: Credentials Compromised

1. **Activate the kill switch immediately.**
2. **Revoke the compromised credentials** in the IC Markets portal / Telegram BotFather / Brave API dashboard.
3. **Generate new credentials.**
4. **Follow the credential rotation procedure** (Section 1).

### Scenario: Server Unreachable

1. Access the server via an alternative method (console, backup SSH key, provider dashboard).
2. Check if the server is running (`uptime`, `dmesg | tail`).
3. If the server rebooted, trading bots need to be restarted manually (they do not auto-start).
4. Check the trading state files to verify no data corruption.

### Scenario: API Rate Limiting / Connection Issues

1. The bot will log connection errors and retry on the next cycle (every 60 seconds).
2. If persistent, activate the kill switch.
3. Check IC Markets status page for outages.
4. If needed, increase `check_interval` in the bot config to reduce API call frequency.

---

## 6. How to Add a New Trading Bot or Employee

### Adding a New Trading Bot

1. **Create the bot script** in `/root/.openclaw/workspace/employees/`:
   ```bash
   cp /root/.openclaw/workspace/employees/paper-trading-runner.py \
      /root/.openclaw/workspace/employees/new-bot.py
   ```

2. **Import and use the shared libraries:**
   ```python
   import sys
   sys.path.insert(0, '/root/.openclaw/workspace')

   from lib.credentials import get_icm_credentials
   from lib.trading_safety import check_kill_switch, pre_trade_checks
   from lib.logging_config import get_logger
   from lib.atomic_write import atomic_json_write
   from lib.telegram import send_trade_alert, send_error_alert
   ```

3. **Implement required safety checks.** Every trading bot MUST:
   - Call `check_kill_switch()` at the start of every trading cycle.
   - Call `pre_trade_checks()` before every trade execution.
   - Use `get_icm_credentials()` for API credentials (never hardcode).
   - Use `atomic_json_write()` for state file persistence.
   - Use `get_logger()` for logging.

4. **Create a configuration entry** in `/root/.openclaw/workspace/conf/trading.json` if needed.

5. **Test in demo mode** (`ICM_MODE=demo`) before any live usage.

6. **Start the bot** using the procedures in Section 3.

### Adding a New Employee (Agent)

1. **Copy the employee template:**
   ```bash
   cp /root/.openclaw/workspace/employees/EMPLOYEE_TEMPLATE.md \
      /root/.openclaw/workspace/employees/new-employee.md
   ```

2. **Fill in the template** with the new employee's identity, mission, mandate, responsibilities, and tools access.

3. **Assign an employee number.** Current employees:
   - `#001` -- Zeff.bot (CEO)
   - `#002` -- TradeBot (Trading)
   - `#003` -- Natalia (Chief Research Officer)

4. **Update `AGENTS.md`** at `/root/.openclaw/workspace/AGENTS.md` to include the new employee.

5. **Update the dashboard** in `/root/.openclaw/workspace/python/streamlit_dashboard.py` to display the new employee in the employees list (around line 169).

6. **Complete the initialization checklist** in the employee's mission file, verifying all tools access, SOUL.md acknowledgment, and channel configuration.
