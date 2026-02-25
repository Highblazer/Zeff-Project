#!/usr/bin/env python3
"""
Task Dispatch System — file-based task queue for the bot fleet.

Tasks are JSON files that move between status directories:
    tasks/pending/      → New tasks waiting for pickup
    tasks/in_progress/  → Currently executing
    tasks/completed/    → Done with results
    tasks/failed/       → Failed after max retries
"""

import json
import os
import uuid
import shutil
from datetime import datetime, timezone
from typing import Optional

# Use atomic writes for crash safety
import sys
sys.path.insert(0, '/root/.openclaw/workspace')
from lib.atomic_write import atomic_json_write
import logging

_log = logging.getLogger('task_dispatch')


def _notify_zeffbot(task: dict, event: str):
    """Send task result to Zeff.bot for Telegram reporting. Non-blocking."""
    try:
        from lib.zeffbot_report import report_task_completed, report_task_failed
        if event == 'completed':
            report_task_completed(task)
        elif event == 'failed':
            report_task_failed(task)
    except Exception as e:
        _log.warning(f"Zeff.bot reporting failed for task {task.get('id')}: {e}")

TASKS_ROOT = '/root/.openclaw/workspace/tasks'
PENDING = os.path.join(TASKS_ROOT, 'pending')
IN_PROGRESS = os.path.join(TASKS_ROOT, 'in_progress')
COMPLETED = os.path.join(TASKS_ROOT, 'completed')
FAILED = os.path.join(TASKS_ROOT, 'failed')

MAX_RETRIES = 3
TASK_TIMEOUT_SECONDS = 300  # 5 minutes

# Ensure directories exist
for d in [PENDING, IN_PROGRESS, COMPLETED, FAILED]:
    os.makedirs(d, exist_ok=True)


def create_task(
    title: str,
    assigned_to: str,
    task_type: str,
    params: Optional[dict] = None,
    priority: int = 5,
    created_by: str = 'user',
) -> dict:
    """Create a new task and write it to pending/.

    Args:
        title: Human-readable task description.
        assigned_to: Bot name ('natalia', 'tradebot').
        task_type: Type string ('research', 'report', 'trade_analysis', 'market_scan').
        params: Arbitrary parameters for the task handler.
        priority: 1 (highest) to 10 (lowest), default 5.
        created_by: Who created this task.

    Returns:
        The full task dict (including generated id and path).
    """
    task_id = str(uuid.uuid4())[:8]
    now = datetime.now(timezone.utc).isoformat()

    task = {
        'id': task_id,
        'title': title,
        'assigned_to': assigned_to.lower(),
        'task_type': task_type,
        'params': params or {},
        'priority': priority,
        'status': 'pending',
        'created_by': created_by,
        'created_at': now,
        'updated_at': now,
        'claimed_at': None,
        'completed_at': None,
        'retries': 0,
        'result': None,
        'error': None,
    }

    filepath = os.path.join(PENDING, f'{task_id}.json')
    atomic_json_write(filepath, task)
    return task


def get_task(task_id: str) -> Optional[dict]:
    """Find and return a task by ID, searching all status directories."""
    for directory in [PENDING, IN_PROGRESS, COMPLETED, FAILED]:
        filepath = os.path.join(directory, f'{task_id}.json')
        if os.path.isfile(filepath):
            with open(filepath, 'r') as f:
                return json.load(f)
    return None


def get_pending_tasks(bot_name: str) -> list:
    """List pending tasks for a specific bot, sorted by priority (lowest number first)."""
    tasks = []
    for filename in os.listdir(PENDING):
        if not filename.endswith('.json'):
            continue
        filepath = os.path.join(PENDING, filename)
        try:
            with open(filepath, 'r') as f:
                task = json.load(f)
            if task.get('assigned_to') == bot_name.lower():
                tasks.append(task)
        except (json.JSONDecodeError, OSError):
            continue
    tasks.sort(key=lambda t: (t.get('priority', 5), t.get('created_at', '')))
    return tasks


def claim_task(task_id: str) -> Optional[dict]:
    """Move a task from pending/ to in_progress/. Returns the task or None."""
    src = os.path.join(PENDING, f'{task_id}.json')
    dst = os.path.join(IN_PROGRESS, f'{task_id}.json')

    if not os.path.isfile(src):
        return None

    try:
        with open(src, 'r') as f:
            task = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    task['status'] = 'in_progress'
    task['claimed_at'] = datetime.now(timezone.utc).isoformat()
    task['updated_at'] = datetime.now(timezone.utc).isoformat()

    atomic_json_write(dst, task)
    try:
        os.remove(src)
    except OSError:
        pass
    return task


def complete_task(task_id: str, result: dict) -> Optional[dict]:
    """Move a task from in_progress/ to completed/ with results."""
    src = os.path.join(IN_PROGRESS, f'{task_id}.json')
    dst = os.path.join(COMPLETED, f'{task_id}.json')

    if not os.path.isfile(src):
        return None

    try:
        with open(src, 'r') as f:
            task = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    task['status'] = 'completed'
    task['result'] = result
    task['completed_at'] = datetime.now(timezone.utc).isoformat()
    task['updated_at'] = datetime.now(timezone.utc).isoformat()

    atomic_json_write(dst, task)
    try:
        os.remove(src)
    except OSError:
        pass

    # Report to Zeff.bot → Telegram
    _notify_zeffbot(task, 'completed')

    return task


def fail_task(task_id: str, error: str) -> Optional[dict]:
    """Retry or move to failed/. Returns the task dict."""
    src = os.path.join(IN_PROGRESS, f'{task_id}.json')

    if not os.path.isfile(src):
        return None

    try:
        with open(src, 'r') as f:
            task = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    task['retries'] = task.get('retries', 0) + 1
    task['error'] = error
    task['updated_at'] = datetime.now(timezone.utc).isoformat()

    if task['retries'] < MAX_RETRIES:
        # Move back to pending for retry
        task['status'] = 'pending'
        dst = os.path.join(PENDING, f'{task_id}.json')
    else:
        # Exhausted retries — move to failed
        task['status'] = 'failed'
        dst = os.path.join(FAILED, f'{task_id}.json')

    atomic_json_write(dst, task)
    try:
        os.remove(src)
    except OSError:
        pass

    # Report permanent failures to Zeff.bot → Telegram
    if task['status'] == 'failed':
        _notify_zeffbot(task, 'failed')

    return task


def list_tasks(status: Optional[str] = None) -> list:
    """List all tasks, optionally filtered by status."""
    dirs = {
        'pending': PENDING,
        'in_progress': IN_PROGRESS,
        'completed': COMPLETED,
        'failed': FAILED,
    }

    if status and status in dirs:
        search_dirs = {status: dirs[status]}
    else:
        search_dirs = dirs

    tasks = []
    for dir_status, directory in search_dirs.items():
        if not os.path.isdir(directory):
            continue
        for filename in os.listdir(directory):
            if not filename.endswith('.json'):
                continue
            filepath = os.path.join(directory, filename)
            try:
                with open(filepath, 'r') as f:
                    tasks.append(json.load(f))
            except (json.JSONDecodeError, OSError):
                continue

    tasks.sort(key=lambda t: t.get('created_at', ''), reverse=True)
    return tasks


def check_timeouts() -> list:
    """Check in_progress tasks for timeouts. Move timed-out tasks back to pending."""
    timed_out = []
    now = datetime.now(timezone.utc)

    for filename in os.listdir(IN_PROGRESS):
        if not filename.endswith('.json'):
            continue
        filepath = os.path.join(IN_PROGRESS, filename)
        try:
            with open(filepath, 'r') as f:
                task = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        claimed_at = task.get('claimed_at')
        if not claimed_at:
            continue

        try:
            claimed_time = datetime.fromisoformat(claimed_at.replace('Z', '+00:00'))
            elapsed = (now - claimed_time).total_seconds()
        except (ValueError, TypeError):
            continue

        if elapsed > TASK_TIMEOUT_SECONDS:
            failed = fail_task(task['id'], f'Timeout after {elapsed:.0f}s')
            if failed:
                timed_out.append(failed)

    return timed_out


def get_dashboard_summary() -> dict:
    """Return counts and recent tasks for dashboard display."""
    counts = {}
    for status, directory in [('pending', PENDING), ('in_progress', IN_PROGRESS),
                               ('completed', COMPLETED), ('failed', FAILED)]:
        try:
            counts[status] = len([f for f in os.listdir(directory) if f.endswith('.json')])
        except OSError:
            counts[status] = 0

    recent = list_tasks()[:10]
    return {
        'counts': counts,
        'total': sum(counts.values()),
        'recent': recent,
    }
