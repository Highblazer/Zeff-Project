#!/usr/bin/env python3
"""
Trading Safety Module — Kill switch, drawdown limits, position validation.
Every trading bot MUST import and call these checks before executing trades.
"""

import os
import json
import sys
from datetime import datetime, timezone

# Kill switch file — create this file to immediately halt ALL trading
KILL_SWITCH_PATH = '/root/.openclaw/workspace/STOP_TRADING'

# Safety configuration
MAX_RISK_PER_TRADE = 0.02       # 2% of balance per trade
MAX_DAILY_DRAWDOWN = 0.10       # 10% max daily drawdown
MAX_POSITION_VOLUME = 100000    # Max volume in units (1 standard lot)
MAX_OPEN_POSITIONS = 3          # Max simultaneous positions
MIN_BALANCE_TO_TRADE = 10.0     # Don't trade if balance below this


def check_kill_switch():
    """Check if kill switch is active. Returns True if trading should STOP."""
    if os.path.exists(KILL_SWITCH_PATH):
        print(f"KILL SWITCH ACTIVE — {KILL_SWITCH_PATH} exists. All trading halted.")
        return True
    return False


def require_demo_mode(mode: str):
    """Refuse to proceed if mode is not explicitly 'demo'."""
    if mode != 'demo':
        print(f"SAFETY: Refusing to trade. Mode must be 'demo', got '{mode}'.")
        print("Set mode to 'demo' in config or ICM_MODE=demo in .env")
        sys.exit(1)


def validate_position_size(volume: int, balance: float, symbol: str = "") -> tuple:
    """Validate position size before execution.

    Returns (is_valid, reason).
    """
    if volume <= 0:
        return False, f"Invalid volume: {volume}"

    if volume > MAX_POSITION_VOLUME:
        return False, f"Volume {volume} exceeds max {MAX_POSITION_VOLUME} units"

    if balance < MIN_BALANCE_TO_TRADE:
        return False, f"Balance ${balance:.2f} below minimum ${MIN_BALANCE_TO_TRADE}"

    # Risk check: estimate notional value
    risk_amount = balance * MAX_RISK_PER_TRADE
    # For forex, 1 lot = 100000 units, pip value ~$10
    # Rough check: volume shouldn't exceed 2% of balance in risk
    lot_size = volume / 100000
    estimated_risk = lot_size * 100  # ~$100 risk per lot with 10 pip stop
    if estimated_risk > risk_amount and balance > 100:
        return False, f"Estimated risk ${estimated_risk:.2f} exceeds 2% of balance (${risk_amount:.2f})"

    return True, "OK"


def check_drawdown(current_balance: float, starting_balance: float) -> tuple:
    """Check if daily drawdown limit has been breached.

    Returns (is_breached, drawdown_pct).
    """
    if starting_balance <= 0:
        return False, 0.0

    drawdown = (starting_balance - current_balance) / starting_balance
    if drawdown >= MAX_DAILY_DRAWDOWN:
        return True, drawdown

    return False, drawdown


def check_max_positions(current_count: int) -> bool:
    """Returns True if at max positions (should NOT open more)."""
    return current_count >= MAX_OPEN_POSITIONS


def validate_price(price: float, symbol: str = "") -> bool:
    """Validate that a price is reasonable (not 0, negative, or NaN)."""
    if price is None:
        return False
    try:
        price = float(price)
    except (TypeError, ValueError):
        return False

    if price <= 0:
        return False
    if price != price:  # NaN check
        return False

    # Sanity checks for common instruments
    if 'JPY' in symbol and price > 500:
        return False  # USDJPY shouldn't be > 500
    if 'XAU' in symbol and (price < 500 or price > 10000):
        return False  # Gold between 500 and 10000

    return True


def pre_trade_checks(volume: int, balance: float, starting_balance: float,
                     open_positions: int, mode: str, price: float = 0,
                     symbol: str = "") -> tuple:
    """Run ALL safety checks before placing a trade.

    Returns (can_trade, reason).
    """
    if check_kill_switch():
        return False, "Kill switch active"

    if mode != 'demo':
        return False, f"Not in demo mode (mode={mode})"

    is_valid, reason = validate_position_size(volume, balance, symbol)
    if not is_valid:
        return False, f"Position size: {reason}"

    is_breached, dd_pct = check_drawdown(balance, starting_balance)
    if is_breached:
        return False, f"Daily drawdown {dd_pct:.1%} exceeds {MAX_DAILY_DRAWDOWN:.0%} limit"

    if check_max_positions(open_positions):
        return False, f"At max positions ({MAX_OPEN_POSITIONS})"

    if price > 0 and not validate_price(price, symbol):
        return False, f"Invalid price: {price}"

    return True, "All checks passed"


def activate_kill_switch(reason: str = "Manual activation"):
    """Activate the kill switch — halts all trading."""
    with open(KILL_SWITCH_PATH, 'w') as f:
        f.write(json.dumps({
            'activated': datetime.now(timezone.utc).isoformat(),
            'reason': reason
        }))
    print(f"KILL SWITCH ACTIVATED: {reason}")


def deactivate_kill_switch():
    """Remove the kill switch file to resume trading."""
    if os.path.exists(KILL_SWITCH_PATH):
        os.remove(KILL_SWITCH_PATH)
        print("Kill switch deactivated. Trading may resume.")
