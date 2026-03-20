#!/usr/bin/env python3
"""
Fleet Health Monitor — unified watchdog for ALL Zeff.bot agents.

Monitors every service in the fleet, detects failures, restarts crashed
services, updates system-status.json, and sends Telegram alerts.

Runs as a systemd service: fleet-health.service
Check interval: 60 seconds
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
from lib.atomic_write import atomic_json_write
from lib.logging_config import get_logger

log = get_logger('fleet_health', 'fleet_health.log')

CHECK_INTERVAL = 60
ALERT_COOLDOWN = 1800  # 30 min between same-type alerts
BOOT_GRACE_PERIOD = 300  # 5 min grace after boot before sending stale alerts
GLOBAL_RATE_LIMIT = 6  # max alerts per hour across all types
COOLDOWN_FILE = '/root/.openclaw/workspace/logs/.fleet_health_cooldowns.json'
STATUS_FILE = '/root/.openclaw/workspace/system-status.json'

# All fleet services and their status files
FLEET_SERVICES = {
    'tradebot': {
        'service': 'tradebot.service',
        'status_file': '/root/.openclaw/workspace/employees/trading_status.json',
        'stale_threshold': 300,  # 5 min
        'critical': True,
        'role': 'Chief Trading Officer',
        'employee_id': '002',
    },
    'natalia': {
        'service': 'natalia.service',
        'status_file': '/root/.openclaw/workspace/employees/natalia_status.json',
        'stale_threshold': 600,  # 10 min (polls every 15s but tasks can take time)
        'critical': False,
        'role': 'Chief Research Officer',
        'employee_id': '004',
    },
    'watchdog': {
        'service': 'tradebot-watchdog.service',
        'status_file': None,
        'stale_threshold': None,
        'critical': True,
        'role': 'TradeBot Watchdog',
        'employee_id': 'SYS',
    },
}


class FleetHealthMonitor:
    def __init__(self):
        self.last_alert_time = self._load_cooldowns()
        self.boot_time = time.time()
        self.alerts_this_hour = []  # timestamps of alerts sent

    def run(self):
        log.info('Fleet Health Monitor starting — watching all agents')
        # Don't send boot alert — it's noise. Just log it.

        while True:
            try:
                self._check_all()
            except Exception as e:
                log.error(f'Fleet health check error: {e}')
            time.sleep(CHECK_INTERVAL)

    def _check_all(self):
        results = {}
        for name, config in FLEET_SERVICES.items():
            result = self._check_service(name, config)
            results[name] = result

        self._write_system_status(results)

    def _check_service(self, name, config):
        """Check a single service and return its status dict."""
        result = {
            'name': name,
            'role': config['role'],
            'employee_id': config['employee_id'],
            'service_active': False,
            'status_fresh': None,
            'details': {},
        }

        # Check systemd service
        try:
            r = subprocess.run(
                ['systemctl', 'is-active', config['service']],
                capture_output=True, text=True, timeout=10
            )
            result['service_active'] = r.stdout.strip() == 'active'
        except Exception as e:
            log.error(f'Failed to check {config["service"]}: {e}')

        if not result['service_active']:
            log.warning(f'{name}: service is DOWN')
            self._alert(f'{name}_down',
                        f'{name} service is DOWN\n'
                        f'Role: {config["role"]}\n'
                        f'Attempting restart...')
            self._restart_service(name, config['service'])
            return result

        # Check status file freshness
        if config.get('status_file') and config.get('stale_threshold'):
            result['status_fresh'] = self._check_status_file(
                name, config['status_file'], config['stale_threshold']
            )
            # Read status details
            try:
                if os.path.isfile(config['status_file']):
                    with open(config['status_file'], 'r') as f:
                        result['details'] = json.load(f)
            except Exception:
                pass

        return result

    def _check_status_file(self, name, status_file, threshold):
        """Check if a status file is stale. Returns True if fresh."""
        if not os.path.isfile(status_file):
            return None  # No status file exists yet

        # Skip stale alerts during boot grace period — bots need time to warm up
        if (time.time() - self.boot_time) < BOOT_GRACE_PERIOD:
            return None

        try:
            mtime = os.path.getmtime(status_file)
            age = time.time() - mtime
            if age > threshold:
                log.warning(f'{name}: status file is {age:.0f}s old (threshold: {threshold}s)')
                self._alert(f'{name}_stale',
                            f'{name} status file is {age/60:.1f}min stale\n'
                            f'Threshold: {threshold/60:.0f}min\n'
                            f'Bot may be frozen or disconnected')
                return False
            return True
        except Exception as e:
            log.error(f'Failed to check {name} status file: {e}')
            return None

    def _restart_service(self, name, service):
        """Restart a systemd service."""
        try:
            log.info(f'Restarting {service}...')
            r = subprocess.run(
                ['systemctl', 'restart', service],
                capture_output=True, text=True, timeout=30
            )
            if r.returncode == 0:
                log.info(f'{service} restarted successfully')
                self._alert(f'{name}_restarted',
                            f'{name} has been RESTARTED successfully')
            else:
                log.error(f'{service} restart failed: {r.stderr}')
                self._alert(f'{name}_restart_failed',
                            f'FAILED to restart {name}\n'
                            f'Error: {r.stderr[:200]}')
        except Exception as e:
            log.error(f'Restart error for {service}: {e}')

    def _write_system_status(self, results):
        """Write aggregated system status to JSON."""
        now = datetime.now(timezone.utc)

        # System resources
        try:
            load = os.getloadavg()
            load_str = [f'{l:.2f}' for l in load]
        except Exception:
            load_str = ['N/A']

        try:
            import shutil
            disk = shutil.disk_usage('/')
            disk_used = f'{disk.used / (1024**3):.1f}G'
            disk_total = f'{disk.total / (1024**3):.0f}G'
            disk_pct = f'{disk.used / disk.total * 100:.0f}%'
        except Exception:
            disk_used = disk_total = disk_pct = 'N/A'

        try:
            with open('/proc/meminfo', 'r') as f:
                meminfo = f.read()
            total_kb = int([l for l in meminfo.split('\n') if 'MemTotal' in l][0].split()[1])
            avail_kb = int([l for l in meminfo.split('\n') if 'MemAvailable' in l][0].split()[1])
            mem_total_gb = total_kb / (1024**2)
            mem_used_gb = (total_kb - avail_kb) / (1024**2)
            mem_pct = (total_kb - avail_kb) / total_kb * 100
        except Exception:
            mem_total_gb = mem_used_gb = mem_pct = 0

        uptime_secs = time.time() - self.boot_time
        hours = int(uptime_secs // 3600)
        mins = int((uptime_secs % 3600) // 60)

        employees = {}
        for name, r in results.items():
            status = 'online' if r['service_active'] else 'offline'
            if r.get('status_fresh') is False:
                status = 'stale'
            employees[r['employee_id']] = {
                'name': name,
                'status': status,
                'role': r['role'],
                'details': r.get('details', {}),
            }

        status_data = {
            'timestamp': now.isoformat(),
            'uptime_seconds': int(uptime_secs),
            'uptime_human': f'{hours}h {mins}m',
            'system': {
                'load': load_str,
                'memory_used_gb': round(mem_used_gb, 1),
                'memory_total_gb': round(mem_total_gb, 1),
                'memory_percent': round(mem_pct, 1),
                'disk_used': disk_used,
                'disk_total': disk_total,
                'disk_percent': disk_pct,
            },
            'services': {name: 'active' if r['service_active'] else 'inactive'
                         for name, r in results.items()},
            'employees': employees,
        }

        try:
            atomic_json_write(STATUS_FILE, status_data)
        except Exception as e:
            log.error(f'Failed to write system status: {e}')

    def _alert(self, alert_type, text):
        """Send Telegram alert with per-type cooldown, global rate limit, and persistence."""
        now = time.time()
        last = self.last_alert_time.get(alert_type, 0)

        # Per-type cooldown
        if (now - last) < ALERT_COOLDOWN:
            return

        # Global rate limit: max N alerts per hour
        self.alerts_this_hour = [t for t in self.alerts_this_hour if now - t < 3600]
        if len(self.alerts_this_hour) >= GLOBAL_RATE_LIMIT:
            log.warning(f'Global rate limit hit ({GLOBAL_RATE_LIMIT}/hr) — suppressing {alert_type}')
            return

        self.last_alert_time[alert_type] = now
        self.alerts_this_hour.append(now)
        self._save_cooldowns()

        msg = (
            "<b>⬡ ZEFF.BOT</b>\n"
            "<b>🏥 FLEET HEALTH</b>\n"
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
                # Only keep entries less than 2 hours old
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
    monitor = FleetHealthMonitor()
    monitor.run()
