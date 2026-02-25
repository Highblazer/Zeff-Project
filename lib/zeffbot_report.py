#!/usr/bin/env python3
"""
Zeff.bot Reporting Pipeline — CEO delivers fleet updates to Seth via Telegram.

Every bot action that matters flows through here. Zeff.bot doesn't just relay —
he gives you the executive summary: what happened, what it means, what's next.
"""

import os
import sys
import logging
from datetime import datetime, timezone

sys.path.insert(0, '/root/.openclaw/workspace')
from lib.credentials import _load_dotenv
_load_dotenv()
from lib.telegram import send_message

log = logging.getLogger('zeffbot_report')

# ── Header/footer for all messages ──

def _header():
    return "<b>⬡ ZEFF.BOT</b>\n"

def _ts():
    return datetime.now().strftime('%H:%M')


# ═══════════════════════════════════════════════════════════
#  NATALIA — Research & Skills Reports
# ═══════════════════════════════════════════════════════════

def report_research_complete(task: dict):
    """Natalia completed a research task. Summarize findings for Seth."""
    result = task.get('result', {})
    title = task.get('title', 'Unknown')
    query = result.get('query', title)
    sources = result.get('sources_count', 0)
    web = result.get('web_results', [])
    news = result.get('news_results', [])

    msg = _header()
    msg += f"<b>📡 RESEARCH COMPLETE</b>\n"
    msg += f"<i>Natalia</i> — {_ts()}\n\n"
    msg += f"<b>Query:</b> {query}\n"
    msg += f"<b>Sources:</b> {sources}\n\n"

    if web:
        msg += "<b>Key Findings:</b>\n"
        for r in web[:3]:
            desc = r.get('description', '')[:120]
            msg += f"• <b>{r['title'][:60]}</b>\n"
            if desc:
                msg += f"  {desc}\n"
    elif not web and not news:
        msg += "<i>No results returned — API may need attention.</i>\n"

    if news:
        msg += "\n<b>Latest News:</b>\n"
        for r in news[:2]:
            age = f" ({r['age']})" if r.get('age') else ''
            msg += f"• {r['title'][:60]}{age}\n"

    send_message(msg)


def report_report_complete(task: dict):
    """Natalia completed a full report."""
    result = task.get('result', {})
    topic = result.get('topic', task.get('title', 'Unknown'))
    sources = result.get('sources_count', 0)
    report_text = result.get('report', '')

    msg = _header()
    msg += f"<b>📋 REPORT READY</b>\n"
    msg += f"<i>Natalia</i> — {_ts()}\n\n"
    msg += f"<b>Topic:</b> {topic}\n"
    msg += f"<b>Sources:</b> {sources}\n\n"

    # Send first 500 chars of the report
    preview = report_text[:500].replace('<', '&lt;').replace('>', '&gt;')
    # Strip markdown headers for Telegram
    for h in ['## ', '# ', '---']:
        preview = preview.replace(h, '')
    msg += f"{preview}..."

    send_message(msg)


def report_skill_installed(skill_name: str, description: str, category: str,
                           revenue_impact: str = '', environment_impact: str = ''):
    """Natalia found and installed a new skill. Full breakdown for Seth."""
    msg = _header()
    msg += f"<b>🔧 NEW SKILL INSTALLED</b>\n"
    msg += f"<i>Natalia</i> — {_ts()}\n\n"
    msg += f"<b>Skill:</b> {skill_name}\n"
    msg += f"<b>Category:</b> {category}\n\n"
    msg += f"<b>What it does:</b>\n{description}\n\n"

    if environment_impact:
        msg += f"<b>Environment improvement:</b>\n{environment_impact}\n\n"
    if revenue_impact:
        msg += f"<b>Revenue potential:</b>\n{revenue_impact}\n"

    send_message(msg)


# ═══════════════════════════════════════════════════════════
#  TRADEBOT — Trade Execution & P&L Reports
# ═══════════════════════════════════════════════════════════

def report_trade_opened(symbol: str, direction: str, entry_price: float,
                        lot_size: float, stop_loss: float, take_profit: float,
                        reason: str = ''):
    """TradeBot opened a new position."""
    risk = abs(entry_price - stop_loss)
    reward = abs(take_profit - entry_price)
    rr_ratio = round(reward / risk, 1) if risk > 0 else 0

    emoji = "📗" if direction == "BUY" else "📕"

    msg = _header()
    msg += f"<b>{emoji} TRADE OPENED</b>\n"
    msg += f"<i>TradeBot</i> — {_ts()}\n\n"
    msg += f"<b>{direction} {symbol}</b> @ {entry_price:.5f}\n"
    msg += f"<b>Size:</b> {lot_size:.2f} lot\n"
    msg += f"<b>Stop Loss:</b> {stop_loss:.5f}\n"
    msg += f"<b>Take Profit:</b> {take_profit:.5f}\n"
    msg += f"<b>R:R Ratio:</b> 1:{rr_ratio}\n"
    if reason:
        msg += f"<b>Signal:</b> {reason}\n"

    send_message(msg)


def report_trade_closed(symbol: str, direction: str, entry_price: float,
                        close_price: float, lot_size: float, pnl: float = None):
    """TradeBot closed a position — report the outcome."""
    if pnl is None:
        if direction == 'BUY':
            pnl = (close_price - entry_price) * lot_size * 100000
        else:
            pnl = (entry_price - close_price) * lot_size * 100000

    won = pnl >= 0
    emoji = "✅" if won else "❌"
    outcome = "WIN" if won else "LOSS"

    msg = _header()
    msg += f"<b>{emoji} TRADE CLOSED — {outcome}</b>\n"
    msg += f"<i>TradeBot</i> — {_ts()}\n\n"
    msg += f"<b>{direction} {symbol}</b>\n"
    msg += f"<b>Entry:</b> {entry_price:.5f}\n"
    msg += f"<b>Close:</b> {close_price:.5f}\n"
    msg += f"<b>P&amp;L:</b> <b>{'🟢' if won else '🔴'} ${pnl:+.2f}</b>\n"

    send_message(msg)


def report_market_scan(task: dict):
    """TradeBot completed a market scan."""
    result = task.get('result', {})
    signals = result.get('signals', {})
    actionable = result.get('actionable', {})
    session = result.get('market_session', 'unknown')
    balance = result.get('balance', 0)
    open_pos = result.get('open_positions', 0)

    msg = _header()
    msg += f"<b>📊 MARKET SCAN</b>\n"
    msg += f"<i>TradeBot</i> — {_ts()}\n\n"
    msg += f"<b>Session:</b> {session}\n"
    msg += f"<b>Pairs scanned:</b> {len(signals)}\n"
    msg += f"<b>Actionable signals:</b> {len(actionable)}\n\n"

    for sym, data in signals.items():
        sig = data.get('signal', 'HOLD')
        price = data.get('price', 0)
        reason = data.get('reason', '')
        if sig == 'BUY':
            icon = '🟢'
        elif sig == 'SELL':
            icon = '🔴'
        else:
            icon = '⚪'
        msg += f"{icon} <b>{sym}</b> {price:.5f} — {sig} ({reason})\n"

    msg += f"\n<b>Balance:</b> ${balance:.2f} | <b>Open:</b> {open_pos}"

    send_message(msg)


def report_trade_analysis(task: dict):
    """TradeBot completed a trade analysis."""
    result = task.get('result', {})
    analysis = result.get('analysis', {})
    balance = result.get('balance', 0)

    msg = _header()
    msg += f"<b>🔍 TRADE ANALYSIS</b>\n"
    msg += f"<i>TradeBot</i> — {_ts()}\n\n"

    for sym, data in analysis.items():
        sig = data.get('signal', 'HOLD')
        price = data.get('price', 0)
        reason = data.get('reason', '')
        has_pos = data.get('has_position', False)

        if sig == 'BUY':
            icon = '🟢'
        elif sig == 'SELL':
            icon = '🔴'
        else:
            icon = '⚪'

        msg += f"{icon} <b>{sym}</b> {price:.5f} — {sig}\n"
        msg += f"   {reason}\n"
        if has_pos:
            pos = data.get('position', {})
            msg += f"   📌 Open: {pos.get('direction')} @ {pos.get('entry_price', 0):.5f}\n"

    msg += f"\n<b>Balance:</b> ${balance:.2f}"

    send_message(msg)


def report_portfolio(task: dict):
    """TradeBot portfolio/performance report."""
    result = task.get('result', {})
    stats = result.get('stats', {})
    positions = result.get('positions', {})

    msg = _header()
    msg += f"<b>💼 PORTFOLIO REPORT</b>\n"
    msg += f"<i>TradeBot</i> — {_ts()}\n\n"

    msg += f"<b>Balance:</b> ${stats.get('balance', 0):.2f}\n"
    msg += f"<b>Open Positions:</b> {stats.get('open_positions', 0)}\n"
    msg += f"<b>Total Closed:</b> {stats.get('total_closed', 0)}\n"
    msg += f"<b>Win Rate:</b> {stats.get('win_rate', 0):.1f}% ({stats.get('wins', 0)}W / {stats.get('losses', 0)}L)\n"
    msg += f"<b>Total P&amp;L:</b> ${stats.get('total_pnl', 0):.2f}\n"

    if positions:
        msg += "\n<b>Open Positions:</b>\n"
        for sym, pos in positions.items():
            d = pos.get('direction', '?')
            entry = pos.get('entry_price', 0)
            emoji = "📗" if d == "BUY" else "📕"
            msg += f"  {emoji} {d} {sym} @ {entry:.5f} ({pos.get('lot_size', 0):.2f}lot)\n"

    send_message(msg)


# ═══════════════════════════════════════════════════════════
#  TASK FAILURE
# ═══════════════════════════════════════════════════════════

def report_task_failed(task: dict):
    """A task failed after all retries."""
    msg = _header()
    msg += f"<b>⚠️ TASK FAILED</b>\n\n"
    msg += f"<b>Bot:</b> {task.get('assigned_to', '?')}\n"
    msg += f"<b>Task:</b> {task.get('title', '?')}\n"
    msg += f"<b>Type:</b> {task.get('task_type', '?')}\n"
    msg += f"<b>Error:</b> {task.get('error', 'Unknown')[:200]}\n"
    msg += f"<b>Retries:</b> {task.get('retries', 0)}\n"

    send_message(msg)


# ═══════════════════════════════════════════════════════════
#  DISPATCHER — route task results to the right formatter
# ═══════════════════════════════════════════════════════════

def report_task_completed(task: dict):
    """Main entry point: route a completed task to the right report formatter."""
    bot = task.get('assigned_to', '')
    task_type = task.get('task_type', '')

    try:
        if bot == 'natalia':
            if task_type == 'research':
                report_research_complete(task)
            elif task_type == 'report':
                report_report_complete(task)
            else:
                _report_generic(task)
        elif bot == 'tradebot':
            if task_type == 'market_scan':
                report_market_scan(task)
            elif task_type == 'trade_analysis':
                report_trade_analysis(task)
            elif task_type == 'report':
                report_portfolio(task)
            else:
                _report_generic(task)
        else:
            _report_generic(task)
    except Exception as e:
        log.error(f"Failed to send report for task {task.get('id')}: {e}")


def _report_generic(task: dict):
    """Fallback for unrecognized task types."""
    msg = _header()
    msg += f"<b>✅ TASK COMPLETE</b>\n\n"
    msg += f"<b>Bot:</b> {task.get('assigned_to', '?')}\n"
    msg += f"<b>Task:</b> {task.get('title', '?')}\n"
    msg += f"<b>Type:</b> {task.get('task_type', '?')}\n"

    send_message(msg)
