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
MAX_RISK_PER_TRADE = 0.05       # 5% of balance per trade (tight SL keeps actual risk low)
MAX_DAILY_DRAWDOWN = 0.15       # 15% max daily drawdown
MAX_POSITION_VOLUME = 10000000  # Max volume in units (varies by instrument)
MAX_OPEN_POSITIONS = 5          # Max simultaneous positions
MIN_BALANCE_TO_TRADE = 10.0     # Don't trade if balance below this
MIN_RR_RATIO = 2.0              # Minimum reward:risk ratio after spread deduction


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


def _estimate_notional(volume: int, price: float, symbol: str, asset_type: str) -> float:
    """Estimate the notional USD exposure of a position.

    cTrader volume units (confirmed from broker P&L):
      - Forex: volume / 10000000 = standard lots (100000 vol = 0.01 lot)
      - Crypto/Commodity/Index CFDs: volume / 100 = contract units
        (e.g. 100 vol = 1.0 unit of BTC/Gold/S&P)
    """
    if asset_type == 'forex':
        units = volume / 100.0  # 100000 vol = 1000 currency units
        return units  # ~USD equivalent for major pairs
    elif asset_type == 'crypto':
        coin_units = volume / 100.0
        return coin_units * price
    elif asset_type in ('commodity', 'index'):
        contract_units = volume / 100.0
        return contract_units * price
    # Fallback — treat as forex
    return volume / 100.0


def _get_cfd_pip_value(symbol: str, asset_type: str) -> float:
    """Get the price distance per pip for CFD instruments."""
    if symbol == 'XNGUSD':
        return 0.001    # Natural gas: 3 decimals
    elif symbol in ('JP225', 'US30'):
        return 1.0      # Whole-number indices
    elif asset_type == 'index':
        return 0.1      # Most indices move in 0.10 increments
    else:
        return 0.01     # crypto, commodity (metals, oil)


def estimate_dollar_risk(volume: int, price: float, sl_distance_pips: float,
                         symbol: str, asset_type: str) -> float:
    """Calculate the actual dollar amount at risk for a trade.

    This is the REAL risk — what you lose if price moves from entry to stop loss.

    cTrader volume mapping (confirmed from broker P&L):
      - Forex: volume / 10000000 = standard lots
        0.01 lot = 100000 vol; pip value per lot = $10 (non-JPY) / $6.60 (JPY)
      - Crypto/Commodity/Index CFDs: volume / 100 = contract units
        risk = units * sl_pips * pip_value
    """
    if asset_type == 'forex':
        lot_size = volume / 10000000.0  # e.g., 100000 vol = 0.01 lot
        if 'JPY' in symbol:
            pip_value_per_lot = 6.60
        else:
            pip_value_per_lot = 10.0
        return lot_size * pip_value_per_lot * sl_distance_pips
    else:
        units = volume / 100.0  # 100 vol = 1.0 contract unit
        pip_val = _get_cfd_pip_value(symbol, asset_type)
        price_distance = sl_distance_pips * pip_val
        return abs(units * price_distance)


def validate_position_size(volume: int, balance: float, symbol: str = "",
                           price: float = 0.0, asset_type: str = "forex",
                           sl_pips: float = 0.0) -> tuple:
    """Validate position size before execution.

    Asset-aware validation that checks actual dollar risk, not just forex lots.
    Returns (is_valid, reason).
    """
    if volume <= 0:
        return False, f"Invalid volume: {volume}"

    if volume > MAX_POSITION_VOLUME:
        return False, f"Volume {volume} exceeds max {MAX_POSITION_VOLUME} units"

    if balance < MIN_BALANCE_TO_TRADE:
        return False, f"Balance ${balance:.2f} below minimum ${MIN_BALANCE_TO_TRADE}"

    max_risk_amount = balance * MAX_RISK_PER_TRADE

    # Primary check: actual dollar risk using SL distance
    if price > 0 and sl_pips > 0:
        dollar_risk = estimate_dollar_risk(volume, price, sl_pips, symbol, asset_type)
        if dollar_risk > max_risk_amount:
            return False, (f"Dollar risk ${dollar_risk:.2f} exceeds {MAX_RISK_PER_TRADE:.0%} "
                           f"of balance (${max_risk_amount:.2f}) "
                           f"[{symbol} vol={volume} SL={sl_pips}pips]")

    # Notional exposure: no hard cap — demo CFDs use broker-managed margin.
    # Dollar risk check above is the real guard.

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
    if 'JPY' in symbol and 'XAU' not in symbol and price > 500:
        return False
    if symbol == 'XAUUSD' and (price < 500 or price > 10000):
        return False
    if symbol == 'BTCUSD' and (price < 1000 or price > 500000):
        return False
    if symbol == 'ETHUSD' and (price < 50 or price > 50000):
        return False

    return True


def validate_rr(risk_pips: float, reward_pips: float, est_spread_pips: float = 0.0,
                min_rr: float = MIN_RR_RATIO) -> tuple:
    """Validate that effective reward:risk ratio meets minimum threshold.

    Deducts estimated spread from reward to get the real execution R:R.
    Returns (is_valid, effective_rr, reason).
    """
    if risk_pips <= 0:
        return False, 0.0, "risk_pips must be > 0"
    effective_reward = reward_pips - est_spread_pips
    if effective_reward <= 0:
        return False, 0.0, f"Reward {reward_pips} - spread {est_spread_pips} <= 0"
    effective_rr = effective_reward / risk_pips
    if effective_rr < min_rr:
        return False, effective_rr, (f"R:R {effective_rr:.2f}:1 < minimum {min_rr}:1 "
                                     f"(reward={reward_pips} - spread={est_spread_pips} = {effective_reward} vs risk={risk_pips})")
    return True, effective_rr, "OK"


def pre_trade_checks(volume: int, balance: float, starting_balance: float,
                     open_positions: int, mode: str, price: float = 0,
                     symbol: str = "", asset_type: str = "forex",
                     sl_pips: float = 0.0, reward_pips: float = 0.0,
                     est_spread_pips: float = 0.0) -> tuple:
    """Run ALL safety checks before placing a trade.

    Returns (can_trade, reason).
    """
    if check_kill_switch():
        return False, "Kill switch active"

    if mode != 'demo':
        return False, f"Not in demo mode (mode={mode})"

    is_valid, reason = validate_position_size(
        volume, balance, symbol, price=price,
        asset_type=asset_type, sl_pips=sl_pips,
    )
    if not is_valid:
        return False, f"Position size: {reason}"

    is_breached, dd_pct = check_drawdown(balance, starting_balance)
    if is_breached:
        return False, f"Daily drawdown {dd_pct:.1%} exceeds {MAX_DAILY_DRAWDOWN:.0%} limit"

    if check_max_positions(open_positions):
        return False, f"At max positions ({MAX_OPEN_POSITIONS})"

    if price > 0 and not validate_price(price, symbol):
        return False, f"Invalid price: {price}"

    # R:R validation — reject trades where spread eats the reward
    if reward_pips > 0 and sl_pips > 0:
        rr_valid, eff_rr, rr_reason = validate_rr(sl_pips, reward_pips, est_spread_pips)
        if not rr_valid:
            return False, f"R:R check: {rr_reason}"

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
