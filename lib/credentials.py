#!/usr/bin/env python3
"""
Centralized credential loader for OpenClaw.
Loads secrets from environment variables (via .env file), never from plaintext JSON.
"""

import os
import sys


def _load_dotenv():
    """Load .env file if present."""
    env_paths = [
        os.path.join(os.path.dirname(__file__), '..', '.env'),
        '/root/.openclaw/workspace/.env',
    ]
    for env_path in env_paths:
        env_path = os.path.abspath(env_path)
        if os.path.isfile(env_path):
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' in line:
                        key, _, value = line.partition('=')
                        os.environ.setdefault(key.strip(), value.strip())
            return


_load_dotenv()


def get_icm_credentials():
    """Return IC Markets credentials from environment variables."""
    return {
        'client_id': os.environ.get('ICM_CLIENT_ID', ''),
        'api_secret': os.environ.get('ICM_API_SECRET', ''),
        'access_token': os.environ.get('ICM_ACCESS_TOKEN', ''),
        'refresh_token': os.environ.get('ICM_REFRESH_TOKEN', ''),
        'trading_password': os.environ.get('ICM_TRADING_PASSWORD', ''),
        'ctid_trader_account_id': int(os.environ.get('ICM_CTID_ACCOUNT_ID', '0')),
        'account_id': os.environ.get('ICM_ACCOUNT_ID', ''),
        'mode': os.environ.get('ICM_MODE', 'demo'),
    }


def get_icm_live_credentials():
    """Return IC Markets LIVE credentials. Requires explicit confirmation."""
    return {
        'host': os.environ.get('ICM_LIVE_HOST', ''),
        'trade_port': int(os.environ.get('ICM_LIVE_TRADE_PORT', '5212')),
        'quote_port': int(os.environ.get('ICM_LIVE_QUOTE_PORT', '5211')),
        'account_login': os.environ.get('ICM_LIVE_ACCOUNT_LOGIN', ''),
        'sender_comp_id': os.environ.get('ICM_LIVE_SENDER_COMP_ID', ''),
        'password': os.environ.get('ICM_LIVE_PASSWORD', ''),
    }


def get_trading_config():
    """Return trading parameters (non-secret, can stay in JSON)."""
    import json
    config_path = os.path.join(os.path.dirname(__file__), '..', 'conf', 'trading.json')
    config_path = os.path.abspath(config_path)
    if os.path.isfile(config_path):
        with open(config_path, 'r') as f:
            return json.load(f)
    return {
        'symbols': ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD'],
        'max_positions': 3,
        'risk_per_trade': 0.02,
        'stop_loss_pct': 1.5,
        'take_profit_pct': 4.5,
        'lot_size': 1000,
    }


def require_demo_mode():
    """Safety guard: refuse to proceed if mode is not explicitly 'demo'."""
    mode = os.environ.get('ICM_MODE', '')
    if mode != 'demo':
        print("SAFETY: Refusing to run. ICM_MODE must be explicitly set to 'demo'.")
        print(f"Current ICM_MODE: '{mode}'")
        sys.exit(1)
