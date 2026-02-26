#!/usr/bin/env python3
"""
CLI helper for creating tasks in the dispatch queue.

Usage:
    python create_task.py <bot> <type> <title> [--params '{"key": "val"}'] [--priority N]

Examples:
    python create_task.py natalia research "AI agent trends 2026"
    python create_task.py natalia research "Bitcoin price analysis" --params '{"query": "bitcoin price prediction 2026"}'
    python create_task.py natalia report "Weekly market summary" --params '{"topic": "forex market", "queries": ["EUR/USD forecast", "GBP/USD analysis"]}'
    python create_task.py tradebot market_scan "Scan all pairs for setups"
    python create_task.py tradebot trade_analysis "Analyze EURUSD" --params '{"symbol": "EURUSD"}'
    python create_task.py tradebot report "Portfolio summary"
"""

import argparse
import json
import sys

sys.path.insert(0, '/root/.openclaw/workspace')
from lib.task_dispatch import create_task, get_task, list_tasks, get_dashboard_summary

VALID_BOTS = {
    'natalia': ['research', 'report'],
    'tradebot': ['trade_analysis', 'market_scan', 'report'],
}


def cmd_create(args):
    bot = args.bot.lower()
    if bot not in VALID_BOTS:
        print(f"Error: Unknown bot '{bot}'. Valid: {', '.join(VALID_BOTS.keys())}")
        sys.exit(1)

    valid_types = VALID_BOTS[bot]
    if args.type not in valid_types:
        print(f"Error: Invalid type '{args.type}' for {bot}. Valid: {', '.join(valid_types)}")
        sys.exit(1)

    params = {}
    if args.params:
        try:
            params = json.loads(args.params)
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON params: {e}")
            sys.exit(1)

    task = create_task(
        title=args.title,
        assigned_to=bot,
        task_type=args.type,
        params=params,
        priority=args.priority,
        created_by='cli',
    )

    print(f"Task created: {task['id']}")
    print(f"  Title:    {task['title']}")
    print(f"  Bot:      {task['assigned_to']}")
    print(f"  Type:     {task['task_type']}")
    print(f"  Priority: {task['priority']}")
    if params:
        print(f"  Params:   {json.dumps(params)}")


def cmd_list(args):
    tasks = list_tasks(status=args.status)
    if not tasks:
        print("No tasks found.")
        return

    for t in tasks:
        status_icon = {'pending': '.', 'in_progress': '>', 'completed': '+', 'failed': 'X'}.get(t['status'], '?')
        print(f"  [{status_icon}] {t['id']}  {t['assigned_to']:10s}  {t['task_type']:15s}  {t['title'][:50]}")


def cmd_status(args):
    summary = get_dashboard_summary()
    counts = summary['counts']
    print(f"Task Queue Status")
    print(f"  Pending:     {counts.get('pending', 0)}")
    print(f"  In Progress: {counts.get('in_progress', 0)}")
    print(f"  Completed:   {counts.get('completed', 0)}")
    print(f"  Failed:      {counts.get('failed', 0)}")
    print(f"  Total:       {summary['total']}")


def cmd_get(args):
    task = get_task(args.task_id)
    if not task:
        print(f"Task {args.task_id} not found.")
        sys.exit(1)
    print(json.dumps(task, indent=2))


def main():
    parser = argparse.ArgumentParser(description='Task Dispatch CLI')
    subparsers = parser.add_subparsers(dest='command')

    # create
    p_create = subparsers.add_parser('create', help='Create a new task')
    p_create.add_argument('bot', help='Bot name (natalia, tradebot)')
    p_create.add_argument('type', help='Task type')
    p_create.add_argument('title', help='Task title/description')
    p_create.add_argument('--params', help='JSON params', default=None)
    p_create.add_argument('--priority', type=int, default=5, help='Priority 1-10 (default 5)')

    # list
    p_list = subparsers.add_parser('list', help='List tasks')
    p_list.add_argument('--status', choices=['pending', 'in_progress', 'completed', 'failed'], default=None)

    # status
    subparsers.add_parser('status', help='Show queue status')

    # get
    p_get = subparsers.add_parser('get', help='Get task details')
    p_get.add_argument('task_id', help='Task ID')

    args = parser.parse_args()

    if args.command == 'create':
        cmd_create(args)
    elif args.command == 'list':
        cmd_list(args)
    elif args.command == 'status':
        cmd_status(args)
    elif args.command == 'get':
        cmd_get(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
