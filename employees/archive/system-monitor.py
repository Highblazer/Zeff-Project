#!/usr/bin/env python3
"""System Status Monitor - Generates system-status.json"""

import json
import subprocess
import os
from datetime import datetime

def get_status():
    # Uptime
    with open('/proc/uptime') as f:
        uptime_seconds = float(f.read().split()[0])
    
    # Memory
    with open('/proc/meminfo') as f:
        meminfo = f.read()
    mem_total = int([l for l in meminfo.split('\n') if 'MemTotal' in l][0].split()[1]) / 1024
    mem_available = int([l for l in meminfo.split('\n') if 'MemAvailable' in l][0].split()[1]) / 1024
    mem_used = mem_total - mem_available
    
    # Disk
    result = subprocess.run(['df', '-h', '/'], capture_output=True, text=True)
    disk_parts = result.stdout.strip().split('\n')[1].split()
    disk_used = disk_parts[2]
    disk_total = disk_parts[1]
    disk_pct = disk_parts[4]
    
    # Services
    services = {
        'tradebot': 'active',
        'trade-dashboard': 'active',
        'trade-tunnel': 'inactive',
    }
    
    # Check actual service status
    for svc in services:
        result = subprocess.run(['systemctl', 'is-active', f'{svc}.service'], capture_output=True, text=True)
        if result.returncode == 0:
            services[svc] = 'active'
        else:
            services[svc] = 'inactive'
    
    # Gateway status
    result = subprocess.run(['systemctl', 'is-active', 'gateway'], capture_output=True, text=True)
    gateway = 'active' if result.returncode == 0 else 'inactive'
    
    # Load average
    with open('/proc/loadavg') as f:
        load = f.read().split()[:3]
    
    return {
        'timestamp': datetime.now().isoformat(),
        'uptime_seconds': int(uptime_seconds),
        'uptime_human': f"{int(uptime_seconds // 3600)}h {int((uptime_seconds % 3600) // 60)}m",
        'system': {
            'load': load,
            'memory_used_gb': round(mem_used / 1024, 1),
            'memory_total_gb': round(mem_total / 1024, 1),
            'memory_percent': round(mem_used / mem_total * 100, 1),
            'disk_used': disk_used,
            'disk_total': disk_total,
            'disk_percent': disk_pct,
        },
        'services': services,
        'gateway': gateway,
        'employees': {
            '001': {'name': 'Zeff.bot (CEO)', 'status': 'online', 'role': 'CEO'},
            '002': {'name': 'Dropship', 'status': 'onhold', 'role': 'E-commerce'},
            '003': {'name': 'TradeBot', 'status': 'online', 'role': 'Trading'},
            '004': {'name': '[TBD]', 'status': 'pending', 'role': 'TBD'},
        },
        'pending': [
            'IC Markets API (TradeBot)',
            'Shopify API (Dropship)',
        ],
    }

if __name__ == '__main__':
    status = get_status()
    with open('/root/.openclaw/workspace/system-status.json', 'w') as f:
        json.dump(status, f, indent=2)
    print(f"Updated: {status['timestamp']}")
