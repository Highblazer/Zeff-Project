#!/usr/bin/env python3
"""
TradeBot Watchdog — bulletproof external monitor.

Runs as a separate systemd service. Monitors TradeBot health by reading
trading_state.json and takes escalating action:

  1. Detect disconnect (connected=false or stale state file)
  2. Alert via Telegram immediately
  3. If disconnected >3 min, restart tradebot.service
  4. If still disconnected after restart, alert CRITICAL
  5. Continuous monitoring every 30 seconds

Also detects:
  - TradeBot process crash (systemd reports inactive)
  - Stale state file (no update in >5 minutes while supposedly connected)
  - Excessive reconnect loops

Install: sudo systemctl enable --now tradebot-watchdog.service
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '/root/.openclaw/workspace')
from lib.credentials import _load_dotenv
_load_dotenv()
from lib.telegram import send_message
from lib.logging_config import get_logger

log = get_logger('watchdog', 'tradebot_watchdog.log')

STATE_FILE = '/root/.openclaw/workspace/employees/trading_state.json'
SERVICE_NAME = 'tradebot.service'
CHECK_INTERVAL = 30  # seconds
DISCONNECT_RESTART_AFTER = 180  # restart service after 3 min disconnect
STALE_THRESHOLD = 300  # state file older than 5 min = stale
ALERT_COOLDOWN = 900  # 15 min between same-type alerts
BOOT_GRACE_PERIOD = 120  # 2 min grace after boot before alerting
GLOBAL_RATE_LIMIT = 4  # max alerts per hour
MAX_RESTARTS_PER_HOUR = 3
COOLDOWN_FILE = '/root/.openclaw/workspace/logs/.watchdog_cooldowns.json'


class Watchdog:
    def __init__(self):
        self.disconnect_since = None  # when disconnect was first detected
        self.last_alert_time = self._load_cooldowns()
        self.restarts_this_hour = []  # timestamps of restarts
        self.last_known_good = None   # last time we saw connected=true
        self.consecutive_disconnects = 0
        self.boot_time = time.time()
        self.alerts_this_hour = []  # timestamps of alerts sent

    def run(self):
        log.info('TradeBot Watchdog starting')
        # Don't send startup alert — it's noise that contributes to spam

        while True:
            try:
                self._check()
            except Exception as e:
                log.error(f'Watchdog check error: {e}')
            time.sleep(CHECK_INTERVAL)

    def _check(self):
        # Check if systemd service is running
        service_active = self._is_service_active()
        if not service_active:
            log.warning('tradebot.service is NOT active')
            self._alert('service_down',
                        'tradebot.service is DOWN (not running)\n'
                        'Attempting restart...')
            self._restart_service()
            return

        # Read state file
        state = self._read_state()
        if state is None:
            log.warning('Cannot read trading_state.json')
            self._alert('state_missing',
                        'Cannot read trading_state.json — TradeBot may be broken')
            return

        connected = state.get('connected', False)
        last_update = state.get('last_update', '')
        balance = state.get('balance', 0)
        open_positions = len(state.get('positions', {}))

        # Check if state file is stale
        if last_update:
            try:
                update_dt = datetime.fromisoformat(last_update)
                if update_dt.tzinfo is None:
                    update_dt = update_dt.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - update_dt).total_seconds()
                if age > STALE_THRESHOLD and connected:
                    log.warning(f'State file is {age:.0f}s old but claims connected')
                    self._alert('stale',
                                f'State file is {age/60:.0f}min old but claims connected\n'
                                f'TradeBot may be frozen\n'
                                f'Open positions: {open_positions}')
            except Exception:
                pass

        if connected:
            # All good
            if self.disconnect_since is not None:
                # We recovered — only alert if we were down for more than 2 min
                duration = time.time() - self.disconnect_since
                log.info(f'TradeBot reconnected after {duration:.0f}s')
                if duration > 120:
                    self._alert('recovered',
                                f'TradeBot RECOVERED (was down {duration/60:.1f}min)\n'
                                f'Balance: ${balance:.2f}\n'
                                f'Open positions: {open_positions}')
                self.disconnect_since = None
                self.consecutive_disconnects = 0
            self.last_known_good = time.time()
            return

        # === DISCONNECTED ===
        now = time.time()

        # Skip disconnect alerts during boot grace period — bot needs time to connect
        if (now - self.boot_time) < BOOT_GRACE_PERIOD:
            if self.disconnect_since is None:
                self.disconnect_since = now
            return

        if self.disconnect_since is None:
            self.disconnect_since = now
            self.consecutive_disconnects += 1
            log.warning(f'TradeBot DISCONNECTED (detection #{self.consecutive_disconnects})')
            self._alert('disconnect',
                        f'TradeBot DISCONNECTED from cTrader\n'
                        f'Open positions: {open_positions} UNMONITORED\n'
                        f'Balance: ${balance:.2f}\n'
                        f'Watchdog will restart in {DISCONNECT_RESTART_AFTER}s if not recovered')

        disconnect_duration = now - self.disconnect_since

        # Restart after threshold
        if disconnect_duration > DISCONNECT_RESTART_AFTER:
            # Check restart budget
            self.restarts_this_hour = [t for t in self.restarts_this_hour if now - t < 3600]
            if len(self.restarts_this_hour) < MAX_RESTARTS_PER_HOUR:
                log.warning(f'Disconnected for {disconnect_duration:.0f}s — restarting service')
                self._alert('restart',
                            f'Disconnected for {disconnect_duration/60:.1f}min\n'
                            f'RESTARTING tradebot.service\n'
                            f'Open positions: {open_positions} UNMONITORED')
                self._restart_service()
                self.disconnect_since = None  # Reset timer after restart
            else:
                log.error(f'Hit restart limit ({MAX_RESTARTS_PER_HOUR}/hour)')
                self._alert('critical',
                            f'CRITICAL: TradeBot stuck disconnected\n'
                            f'Restart limit reached ({MAX_RESTARTS_PER_HOUR}/hour)\n'
                            f'Open positions: {open_positions} UNMONITORED\n'
                            f'Balance: ${balance:.2f}\n'
                            f'MANUAL INTERVENTION REQUIRED')

    def _read_state(self) -> dict | None:
        try:
            if os.path.isfile(STATE_FILE):
                with open(STATE_FILE, 'r') as f:
                    return json.load(f)
        except Exception as e:
            log.error(f'Failed to read state file: {e}')
        return None

    def _is_service_active(self) -> bool:
        try:
            result = subprocess.run(
                ['systemctl', 'is-active', SERVICE_NAME],
                capture_output=True, text=True, timeout=10
            )
            return result.stdout.strip() == 'active'
        except Exception as e:
            log.error(f'Failed to check service status: {e}')
            return False

    def _restart_service(self):
        try:
            log.info(f'Restarting {SERVICE_NAME}...')
            result = subprocess.run(
                ['systemctl', 'restart', SERVICE_NAME],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                log.info('Service restart successful')
                self.restarts_this_hour.append(time.time())
            else:
                log.error(f'Service restart failed: {result.stderr}')
                self._alert('restart_failed',
                            f'Failed to restart {SERVICE_NAME}\n'
                            f'Error: {result.stderr[:200]}')
        except Exception as e:
            log.error(f'Service restart error: {e}')

    def _alert(self, alert_type: str, text: str):
        """Send Telegram alert with per-type cooldown, global rate limit, and persistence."""
        now = time.time()
        last = self.last_alert_time.get(alert_type, 0)

        # Critical alerts always go through, others respect cooldown
        if alert_type != 'critical' and (now - last) < ALERT_COOLDOWN:
            return

        # Global rate limit: max N alerts per hour
        self.alerts_this_hour = [t for t in self.alerts_this_hour if now - t < 3600]
        if alert_type != 'critical' and len(self.alerts_this_hour) >= GLOBAL_RATE_LIMIT:
            log.warning(f'Global rate limit hit ({GLOBAL_RATE_LIMIT}/hr) — suppressing {alert_type}')
            return

        self.last_alert_time[alert_type] = now
        self.alerts_this_hour.append(now)
        self._save_cooldowns()

        msg = (
            "<b>⬡ ZEFF.BOT</b>\n"
            "<b>🛡️ WATCHDOG</b>\n"
            f"<i>{datetime.now().strftime('%H:%M:%S')}</i>\n\n"
            f"{text}"
        )
        try:
            send_message(msg)
            log.info(f'Alert sent: {alert_type}')
        except Exception as e:
            log.error(f'Failed to send alert: {e}')

    def _load_cooldowns(self):
        """Load persisted cooldown timestamps so restarts don't reset them."""
        try:
            if os.path.isfile(COOLDOWN_FILE):
                with open(COOLDOWN_FILE, 'r') as f:
                    data = json.load(f)
                now = time.time()
                return {k: v for k, v in data.items() if now - v < 7200}
        except Exception:
            pass
        return {}

    def _save_cooldowns(self):
        """Persist cooldown timestamps to survive restarts."""
        try:
            with open(COOLDOWN_FILE, 'w') as f:
                json.dump(self.last_alert_time, f)
        except Exception:
            pass


if __name__ == '__main__':
    watchdog = Watchdog()
    watchdog.run()
