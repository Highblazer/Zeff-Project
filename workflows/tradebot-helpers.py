#!/usr/bin/env python3
"""
Lobster workflow helpers for TradeBot.
Each subcommand outputs JSON for piping between Lobster steps.
"""

import json
import sys
import os

sys.path.insert(0, '/root/.openclaw/workspace')


def cmd_safety_and_scan():
    """Run safety checks, then scan if safe. Single step combining both."""
    from lib.trading_safety import (
        check_kill_switch, check_drawdown, check_max_positions,
        MIN_BALANCE_TO_TRADE, MAX_OPEN_POSITIONS,
    )
    from datetime import datetime, timezone
    import requests

    # ── Safety checks ──
    state_path = '/root/.openclaw/workspace/employees/trading_state.json'
    config_path = '/root/.openclaw/workspace/employees/paper-trading-config.json'

    with open(state_path) as f:
        state = json.load(f)
    with open(config_path) as f:
        config = json.load(f)

    balance = state.get('balance', 0)
    starting = config.get('initial_balance', 200)
    open_count = len(state.get('positions', {}))
    existing = set(state.get('positions', {}).keys())
    connected = state.get('connected', False)
    mode = state.get('mode', 'unknown')

    checks = []
    can_trade = True

    if check_kill_switch():
        checks.append({'check': 'kill_switch', 'pass': False, 'detail': 'ACTIVE'})
        can_trade = False
    else:
        checks.append({'check': 'kill_switch', 'pass': True, 'detail': 'Off'})

    if mode != 'demo':
        checks.append({'check': 'mode', 'pass': False, 'detail': f'{mode}'})
        can_trade = False
    else:
        checks.append({'check': 'mode', 'pass': True, 'detail': 'demo'})

    if not connected:
        checks.append({'check': 'connection', 'pass': False, 'detail': 'Disconnected'})
        can_trade = False
    else:
        checks.append({'check': 'connection', 'pass': True, 'detail': 'Connected'})

    if balance < MIN_BALANCE_TO_TRADE:
        checks.append({'check': 'balance', 'pass': False, 'detail': f'${balance:.2f}'})
        can_trade = False
    else:
        checks.append({'check': 'balance', 'pass': True, 'detail': f'${balance:.2f}'})

    breached, dd_pct = check_drawdown(balance, starting)
    if breached:
        checks.append({'check': 'drawdown', 'pass': False, 'detail': f'{dd_pct:.1%}'})
        can_trade = False
    else:
        checks.append({'check': 'drawdown', 'pass': True, 'detail': f'{dd_pct:.1%}'})

    if check_max_positions(open_count):
        checks.append({'check': 'max_positions', 'pass': False, 'detail': f'{open_count}/{MAX_OPEN_POSITIONS}'})
        can_trade = False
    else:
        checks.append({'check': 'max_positions', 'pass': True, 'detail': f'{open_count}/{MAX_OPEN_POSITIONS}'})

    if not can_trade:
        failed = [c for c in checks if not c['pass']]
        reasons = ', '.join(f"{c['check']}: {c['detail']}" for c in failed)
        print(json.dumps({
            'status': 'blocked',
            'can_trade': False,
            'checks': checks,
            'balance': balance,
            'message': f'Trading blocked — {reasons}',
        }))
        sys.exit(1)

    # ── Market scan ──
    PAIRS = {
        'EURUSD': {'name': 'EUR/USD', 'type': 'forex', 'volume': 100000, 'risk_pips': 15, 'reward_pips': 45},
        'GBPUSD': {'name': 'GBP/USD', 'type': 'forex', 'volume': 100000, 'risk_pips': 20, 'reward_pips': 60},
        'USDJPY': {'name': 'USD/JPY', 'type': 'forex', 'volume': 100000, 'risk_pips': 20, 'reward_pips': 60},
        'AUDUSD': {'name': 'AUD/USD', 'type': 'forex', 'volume': 100000, 'risk_pips': 20, 'reward_pips': 60},
        'USDCAD': {'name': 'USD/CAD', 'type': 'forex', 'volume': 100000, 'risk_pips': 20, 'reward_pips': 60},
    }

    YAHOO_SYMBOLS = {
        'EURUSD': 'EURUSD=X', 'GBPUSD': 'GBPUSD=X', 'USDJPY': 'USDJPY=X',
        'AUDUSD': 'AUDUSD=X', 'USDCAD': 'USDCAD=X',
    }

    HIGH_VOLATILITY = {
        'tokyo_open': 0, 'london_open': 8, 'london_close': 17,
        'ny_open': 13, 'ny_close': 21,
    }

    def get_price(symbol):
        try:
            yahoo = YAHOO_SYMBOLS.get(symbol, symbol)
            headers = {'User-Agent': 'Mozilla/5.0'}
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo}"
            r = requests.get(url, headers=headers, timeout=10)
            data = r.json()
            if 'result' not in data['chart'] or not data['chart']['result']:
                return None, None
            price = data['chart']['result'][0]['meta']['regularMarketPrice']
            url2 = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo}?interval=1h&range=48h"
            r2 = requests.get(url2, headers=headers, timeout=10)
            data2 = r2.json()
            if 'result' not in data2['chart'] or not data2['chart']['result']:
                return price, None
            candles = data2['chart']['result'][0]['indicators']['quote'][0]
            highs = [h for h in candles.get('high', []) if h is not None]
            lows = [l for l in candles.get('low', []) if l is not None]
            closes = [c for c in candles.get('close', []) if c is not None]
            return price, {'highs': highs, 'lows': lows, 'closes': closes}
        except Exception:
            return None, None

    def calculate_ema(prices, period):
        if len(prices) < period:
            return None
        multiplier = 2 / (period + 1)
        ema = prices[0]
        for p in prices[1:]:
            ema = (p - ema) * multiplier + ema
        return ema

    def find_fvg(closes, highs, lows):
        fvgs = []
        if len(closes) < 3:
            return fvgs
        for i in range(2, len(closes)):
            if highs[i-2] < lows[i]:
                fvgs.append({'type': 'bullish', 'top': lows[i], 'bottom': highs[i-2]})
            if lows[i-2] > highs[i]:
                fvgs.append({'type': 'bearish', 'top': lows[i-2], 'bottom': highs[i]})
        return fvgs[-5:]

    def find_sr_levels(highs, lows, closes):
        if len(closes) < 20:
            return None, None
        current = closes[-1]
        resistance = None
        support = None
        for h in highs[-10:]:
            if h > current and (resistance is None or h < resistance):
                resistance = h
        for l in lows[-10:]:
            if l < current and (support is None or l > support):
                support = l
        return support, resistance

    def is_market_open():
        current_hour = datetime.now(timezone.utc).hour
        for market, open_hour in HIGH_VOLATILITY.items():
            if abs(current_hour - open_hour) <= 1:
                return True, market
        if 8 <= current_hour <= 17:
            return True, "london_session"
        if 13 <= current_hour <= 21:
            return True, "ny_session"
        return False, "outside_sessions"

    def get_signal(symbol, price, data):
        if not data or len(data.get('closes', [])) < 30:
            return 'HOLD', 'Insufficient data'
        closes = data['closes']
        highs = data['highs']
        lows = data['lows']
        in_session, session_name = is_market_open()
        fvgs = find_fvg(closes, highs, lows)
        support, resistance = find_sr_levels(highs, lows, closes)
        ema_20 = calculate_ema(closes, 20)
        ema_50 = calculate_ema(closes, 50)
        current_price = closes[-1]
        signals = []

        for fvg in fvgs:
            if fvg['type'] == 'bullish':
                if current_price < fvg['top'] and current_price > fvg['bottom']:
                    if support and current_price > support:
                        signals.append(('BUY', f'FVG + Support {session_name}'))
            elif fvg['type'] == 'bearish':
                if current_price > fvg['bottom'] and current_price < fvg['top']:
                    if resistance and current_price < resistance:
                        signals.append(('SELL', f'FVG + Resistance {session_name}'))

        if ema_20 and ema_50:
            if ema_20 > ema_50:
                if current_price >= ema_20 * 0.998:
                    signals.append(('BUY', f'Trend pullback {session_name}'))
            else:
                if current_price <= ema_20 * 1.002:
                    signals.append(('SELL', f'Trend pullback {session_name}'))

        if signals:
            return signals[0]
        return 'HOLD', 'No setup'

    in_session, session = is_market_open()
    scan_results = []

    for symbol, cfg in PAIRS.items():
        price, data = get_price(symbol)
        if not price or not data:
            scan_results.append({
                'symbol': symbol, 'price': None, 'signal': 'SKIP',
                'reason': 'No data', 'has_position': symbol in existing,
            })
            continue

        signal, reason = get_signal(symbol, price, data)
        scan_results.append({
            'symbol': symbol, 'price': round(price, 5), 'signal': signal,
            'reason': reason, 'has_position': symbol in existing,
            'risk_pips': cfg['risk_pips'], 'reward_pips': cfg['reward_pips'],
            'volume': cfg['volume'],
        })

    actionable = [s for s in scan_results
                  if s['signal'] in ('BUY', 'SELL') and not s['has_position']]

    print(json.dumps({
        'status': 'ok',
        'can_trade': True,
        'checks': checks,
        'balance': balance,
        'scan': scan_results,
        'actionable': actionable,
        'session': session,
        'in_session': in_session,
        'existing_positions': list(existing),
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }))


def cmd_build_orders():
    """Read scan results from stdin, build order proposals for the approval gate."""
    raw = sys.stdin.read()
    data = json.loads(raw)
    actionable = data.get('actionable', [])
    session = data.get('session', 'unknown')
    balance = data.get('balance', 0)

    if not actionable:
        # Output a summary even when nothing to trade
        scan = data.get('scan', [])
        lines = []
        for s in scan:
            if s.get('price'):
                icon = {'BUY': '+', 'SELL': '-', 'HOLD': '=', 'SKIP': '?'}.get(s['signal'], '?')
                pos = ' [OPEN]' if s.get('has_position') else ''
                lines.append(f"  [{icon}] {s['symbol']} {s['price']:.5f} — {s['signal']} ({s['reason']}){pos}")
            else:
                lines.append(f"  [?] {s['symbol']} — no data")

        result = {
            'orders': [],
            'prompt': f'Market scan complete ({session}). No new trades. Balance: ${balance:.2f}',
            'items': lines,
            'preview': '\n'.join(lines),
        }
        print(json.dumps(result))
        return

    orders = []
    items = []
    for setup in actionable:
        symbol = setup['symbol']
        signal = setup['signal']
        price = setup['price']
        risk = setup['risk_pips']
        reward = setup['reward_pips']

        multiplier = 0.01 if 'JPY' in symbol else 0.0001
        if signal == 'BUY':
            sl = round(price - (risk * multiplier), 5)
            tp = round(price + (reward * multiplier), 5)
        else:
            sl = round(price + (risk * multiplier), 5)
            tp = round(price - (reward * multiplier), 5)

        order = {
            'symbol': symbol, 'direction': signal, 'price': price,
            'stop_loss': sl, 'take_profit': tp,
            'risk_pips': risk, 'reward_pips': reward,
            'rr_ratio': f'1:{reward // risk}',
            'volume': setup['volume'],
            'lot_size': setup['volume'] / 10000000,
            'reason': setup['reason'], 'session': session,
        }
        orders.append(order)
        items.append(
            f"{signal} {symbol} @ {price:.5f} | SL {sl:.5f} | TP {tp:.5f} | "
            f"R:R {order['rr_ratio']} | {setup['reason']}"
        )

    prompt = (
        f"TradeBot: {len(orders)} trade(s) ready — {session} | "
        f"Balance: ${balance:.2f}\n\n" + '\n'.join(items) + "\n\nApprove execution?"
    )

    result = {
        'requiresApproval': {
            'prompt': prompt,
            'items': items,
            'preview': '\n'.join(items),
        },
        'orders': orders,
    }
    print(json.dumps(result))


def cmd_execute():
    """Read approved orders from stdin, dispatch to TradeBot engine."""
    raw = sys.stdin.read()
    data = json.loads(raw)
    orders = data.get('orders', [])

    if not orders:
        print(json.dumps({'executed': [], 'count': 0, 'message': 'No orders to execute'}))
        return

    from datetime import datetime, timezone
    from lib.atomic_write import atomic_json_write

    dispatch_path = '/root/.openclaw/workspace/employees/pending_orders.json'
    dispatch = {
        'source': 'lobster_workflow',
        'orders': orders,
        'created_at': datetime.now(timezone.utc).isoformat(),
    }
    atomic_json_write(dispatch_path, dispatch)

    executed = []
    for order in orders:
        executed.append({
            'symbol': order['symbol'],
            'direction': order['direction'],
            'price': order['price'],
            'sl': order['stop_loss'],
            'tp': order['take_profit'],
            'lot': order['lot_size'],
        })

    print(json.dumps({
        'executed': executed,
        'count': len(executed),
        'dispatch_path': dispatch_path,
        'message': f'{len(executed)} order(s) dispatched to TradeBot engine',
    }))


def cmd_report():
    """Generate a summary report of current state."""
    from datetime import datetime, timezone

    state_path = '/root/.openclaw/workspace/employees/trading_state.json'
    config_path = '/root/.openclaw/workspace/employees/paper-trading-config.json'

    with open(state_path) as f:
        state = json.load(f)
    with open(config_path) as f:
        config = json.load(f)

    balance = state.get('balance', 0)
    starting = config.get('initial_balance', 200)
    positions = state.get('positions', {})
    stats = state.get('stats', {})
    pnl_pct = ((balance - starting) / starting) * 100 if starting > 0 else 0

    report = {
        'balance': balance,
        'starting_balance': starting,
        'pnl_pct': round(pnl_pct, 2),
        'open_positions': len(positions),
        'positions': {},
        'stats': stats,
        'connected': state.get('connected', False),
        'mode': state.get('mode', 'unknown'),
        'generated_at': datetime.now(timezone.utc).isoformat(),
    }

    for sym, pos in positions.items():
        report['positions'][sym] = {
            'direction': pos.get('direction'),
            'entry': pos.get('entry_price'),
            'sl': pos.get('stop_loss'),
            'tp': pos.get('take_profit'),
            'lot': pos.get('lot_size'),
        }

    print(json.dumps(report))


if __name__ == '__main__':
    commands = {
        'safety-and-scan': cmd_safety_and_scan,
        'build-orders': cmd_build_orders,
        'execute': cmd_execute,
        'report': cmd_report,
    }

    if len(sys.argv) < 2 or sys.argv[1] not in commands:
        print(json.dumps({'error': f'Usage: {sys.argv[0]} <{"| ".join(commands.keys())}>'}))
        sys.exit(1)

    commands[sys.argv[1]]()
