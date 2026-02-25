#!/usr/bin/env python3
"""
CLI tool for creating tasks in the fleet dispatch system.

Usage:
    python create_task.py create <bot> <type> <title> [--params '{"key": "val"}'] [--priority N]
    python create_task.py status
    python create_task.py list [--status pending|in_progress|completed|failed]
    python create_task.py get <task_id>

Examples:
    python create_task.py create natalia research "AI trends 2026"
    python create_task.py create natalia research "AI trends" --params '{"extract": true, "extract_count": 3}'
    python create_task.py create natalia deep_research "AI agent revenue strategies"
    python create_task.py create tradebot market_scan "Scan all pairs"
    python create_task.py status
    python create_task.py list --status completed
    python create_task.py get abc12345
"""

import argparse
import json
import sys

sys.path.insert(0, '/root/.openclaw/workspace')

from lib.task_dispatch import create_task, get_task, list_tasks, get_dashboard_summary

# ── Valid task types per bot ───────────────────────────────

VALID_BOTS = {
    'natalia': ['research', 'report', 'deep_research'],
    'tradebot': ['trade_analysis', 'market_scan', 'report'],
}


def cmd_create(args):
    """Create a new task."""
    bot = args.bot.lower()
    task_type = args.type

    if bot not in VALID_BOTS:
        print(f'Error: Unknown bot "{bot}". Valid bots: {", ".join(VALID_BOTS.keys())}')
        sys.exit(1)

    if task_type not in VALID_BOTS[bot]:
        valid = ', '.join(VALID_BOTS[bot])
        print(f'Error: Invalid type "{task_type}" for {bot}. Valid types: {valid}')
        sys.exit(1)

    params = {}
    if args.params:
        try:
            params = json.loads(args.params)
        except json.JSONDecodeError as e:
            print(f'Error: Invalid JSON in --params: {e}')
            sys.exit(1)

    # For research/deep_research, set query from title if not in params
    if task_type in ('research', 'deep_research') and 'query' not in params:
        params['query'] = args.title

    # For report, set topic from title if not in params
    if task_type == 'report' and 'topic' not in params:
        params['topic'] = args.title

    task = create_task(
        title=args.title,
        assigned_to=bot,
        task_type=task_type,
        params=params,
        priority=args.priority,
        created_by='cli',
    )

    print(f'Task created: {task["id"]}')
    print(f'  Bot:      {task["assigned_to"]}')
    print(f'  Type:     {task["task_type"]}')
    print(f'  Title:    {task["title"]}')
    print(f'  Priority: {task["priority"]}')
    if params:
        print(f'  Params:   {json.dumps(params)}')


def cmd_status(args):
    """Show dashboard summary."""
    summary = get_dashboard_summary()
    counts = summary['counts']

    print('Fleet Task Status')
    print('─' * 40)
    print(f'  Pending:     {counts.get("pending", 0)}')
    print(f'  In Progress: {counts.get("in_progress", 0)}')
    print(f'  Completed:   {counts.get("completed", 0)}')
    print(f'  Failed:      {counts.get("failed", 0)}')
    print(f'  Total:       {summary["total"]}')

    recent = summary.get('recent', [])
    if recent:
        print(f'\nRecent Tasks (last {len(recent)}):')
        for t in recent[:5]:
            status_icon = {
                'pending': '⏳', 'in_progress': '🔄',
                'completed': '✅', 'failed': '❌',
            }.get(t['status'], '?')
            print(f'  {status_icon} [{t["id"]}] {t["assigned_to"]}/{t["task_type"]}: {t["title"][:50]}')


def cmd_list(args):
    """List tasks, optionally filtered by status."""
    tasks = list_tasks(status=args.status)
    if not tasks:
        print('No tasks found.')
        return

    print(f'Tasks{" (" + args.status + ")" if args.status else ""}:')
    print('─' * 60)
    for t in tasks:
        status_icon = {
            'pending': '⏳', 'in_progress': '🔄',
            'completed': '✅', 'failed': '❌',
        }.get(t['status'], '?')
        print(f'{status_icon} [{t["id"]}] {t["assigned_to"]}/{t["task_type"]}: {t["title"][:50]}')
        print(f'   Status: {t["status"]} | Priority: {t.get("priority", 5)} | Created: {t["created_at"][:19]}')


def cmd_get(args):
    """Get a single task by ID."""
    task = get_task(args.task_id)
    if not task:
        print(f'Task not found: {args.task_id}')
        sys.exit(1)

    print(json.dumps(task, indent=2))


def main():
    parser = argparse.ArgumentParser(description='Fleet task management CLI')
    sub = parser.add_subparsers(dest='command', help='Command')

    # create
    p_create = sub.add_parser('create', help='Create a new task')
    p_create.add_argument('bot', help=f'Bot name ({", ".join(VALID_BOTS.keys())})')
    p_create.add_argument('type', help='Task type')
    p_create.add_argument('title', help='Task title / query')
    p_create.add_argument('--params', default=None, help='JSON params string')
    p_create.add_argument('--priority', type=int, default=5, help='Priority 1-10 (default 5)')

    # status
    sub.add_parser('status', help='Show task queue status')

    # list
    p_list = sub.add_parser('list', help='List tasks')
    p_list.add_argument('--status', default=None,
                        choices=['pending', 'in_progress', 'completed', 'failed'],
                        help='Filter by status')

    # get
    p_get = sub.add_parser('get', help='Get task details')
    p_get.add_argument('task_id', help='Task ID')

    args = parser.parse_args()

    if args.command == 'create':
        cmd_create(args)
    elif args.command == 'status':
        cmd_status(args)
    elif args.command == 'list':
        cmd_list(args)
    elif args.command == 'get':
        cmd_get(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
