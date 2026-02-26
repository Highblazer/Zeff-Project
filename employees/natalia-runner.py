#!/usr/bin/env python3
"""
Natalia Runner — Chief Research Officer service process.
Polls the task queue for research/report tasks and executes them
via Brave Search API (with DuckDuckGo fallback).
"""

import json
import os
import re
import sys
import time
import requests
from datetime import datetime, timezone

sys.path.insert(0, '/root/.openclaw/workspace')
from lib.atomic_write import atomic_json_write
from lib.logging_config import get_logger
from lib.task_dispatch import (
    get_pending_tasks, claim_task, complete_task, fail_task, check_timeouts,
    create_task,
)

log = get_logger('natalia', 'natalia.log')

POLL_INTERVAL = 15  # seconds
BOT_NAME = 'natalia'
STATUS_FILE = '/root/.openclaw/workspace/employees/natalia_status.json'
REPORT_INTERVAL = 3600  # send Telegram digest every 1 hour (seconds)

# Load API keys from environment / .env
from lib.credentials import _load_dotenv
_load_dotenv()

BRAVE_API_KEY = os.environ.get('BRAVE_SEARCH_API_KEY', '') or os.environ.get('BRAVE_API_KEY', '')


# ── Search backends ──

def brave_web_search(query: str, count: int = 5) -> list:
    """Search via Brave Web Search API."""
    if not BRAVE_API_KEY:
        return []
    try:
        resp = requests.get(
            'https://api.search.brave.com/res/v1/web/search',
            headers={'Accept': 'application/json', 'X-Subscription-Token': BRAVE_API_KEY},
            params={'q': query, 'count': min(count, 10)},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            results = []
            for r in data.get('web', {}).get('results', []):
                results.append({
                    'title': r.get('title', ''),
                    'url': r.get('url', ''),
                    'description': r.get('description', ''),
                })
            return results
    except Exception as e:
        log.warning(f'Brave web search failed: {e}')
    return []


def brave_news_search(query: str, count: int = 5) -> list:
    """Search via Brave News Search API."""
    if not BRAVE_API_KEY:
        return []
    try:
        resp = requests.get(
            'https://api.search.brave.com/res/v1/news/search',
            headers={'Accept': 'application/json', 'X-Subscription-Token': BRAVE_API_KEY},
            params={'q': query, 'count': min(count, 10)},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            results = []
            for r in data.get('results', []):
                results.append({
                    'title': r.get('title', ''),
                    'url': r.get('url', ''),
                    'description': r.get('description', ''),
                    'age': r.get('age', ''),
                })
            return results
    except Exception as e:
        log.warning(f'Brave news search failed: {e}')
    return []


def duckduckgo_search(query: str, count: int = 5) -> list:
    """Fallback search via DuckDuckGo HTML."""
    try:
        resp = requests.post(
            'https://html.duckduckgo.com/html/',
            data={'q': query},
            headers={'User-Agent': 'Mozilla/5.0'},
            timeout=15,
        )
        if resp.status_code == 200:
            pattern = r'<a class="result__a" href="([^"]+)"[^>]*>(.+?)</a>'
            matches = re.findall(pattern, resp.text)[:count]
            results = []
            for url, title in matches:
                clean_title = re.sub(r'<[^>]+>', '', title).strip()
                results.append({'title': clean_title, 'url': url, 'description': ''})
            return results
    except Exception as e:
        log.warning(f'DuckDuckGo search failed: {e}')
    return []


def search(query: str, count: int = 5) -> list:
    """Search using best available backend."""
    results = brave_web_search(query, count)
    if results:
        return results
    return duckduckgo_search(query, count)


# ── Task handlers ──

def handle_research(task: dict) -> dict:
    """Execute a research task: search web + news, compile findings."""
    params = task.get('params', {})
    query = params.get('query', task.get('title', ''))
    count = params.get('count', 5)

    log.info(f'Researching: {query}')

    web_results = search(query, count)
    news_results = brave_news_search(query, count) if BRAVE_API_KEY else []

    # Compile summary
    findings = []
    for r in web_results:
        findings.append(f"- {r['title']}: {r['description'][:150]}" if r['description'] else f"- {r['title']}")

    news_items = []
    for r in news_results:
        age = f" ({r['age']})" if r.get('age') else ''
        news_items.append(f"- {r['title']}{age}")

    summary = f"Research: {query}\n\nWeb Results ({len(web_results)}):\n"
    summary += '\n'.join(findings) if findings else '  No web results found.'
    if news_items:
        summary += f"\n\nNews ({len(news_results)}):\n" + '\n'.join(news_items)

    return {
        'summary': summary,
        'web_results': web_results,
        'news_results': news_results,
        'query': query,
        'sources_count': len(web_results) + len(news_results),
    }


def handle_report(task: dict) -> dict:
    """Generate a report by researching multiple queries."""
    params = task.get('params', {})
    topic = params.get('topic', task.get('title', ''))
    queries = params.get('queries', [topic])

    log.info(f'Generating report: {topic}')

    all_results = []
    for q in queries:
        results = search(q, 5)
        all_results.extend(results)

    sections = []
    for q in queries:
        q_results = [r for r in all_results if q.lower() in (r.get('title', '') + r.get('description', '')).lower()]
        if not q_results:
            q_results = all_results[:3]
        section = f"## {q}\n"
        for r in q_results[:3]:
            desc = r.get('description', 'No description')[:200]
            section += f"- **{r['title']}**: {desc}\n  Source: {r['url']}\n"
        sections.append(section)

    report = f"# Report: {topic}\n\nGenerated: {datetime.now(timezone.utc).isoformat()}\n\n"
    report += '\n\n'.join(sections)
    report += f"\n\n---\nTotal sources consulted: {len(all_results)}"

    return {
        'report': report,
        'topic': topic,
        'sources_count': len(all_results),
    }


TASK_HANDLERS = {
    'research': handle_research,
    'report': handle_report,
}


# ── Self-generating research topics ──
# Natalia rotates through these when idle — never stops working

_RESEARCH_TOPICS = [
    # AI & Tech landscape
    'latest AI model releases breakthroughs {month} {year}',
    'new AI agent frameworks tools launched {month} {year}',
    'LLM API updates pricing changes {month} {year}',
    'AI automation startups funding {month} {year}',
    'machine learning infrastructure trends {year}',
    # Trading & Markets
    'forex market outlook major pairs {month} {year}',
    'cryptocurrency market trends analysis {month} {year}',
    'economic calendar high impact events this week',
    'central bank interest rate decisions {month} {year}',
    'commodity prices gold oil forecast {month} {year}',
    # Revenue & Business
    'AI SaaS business ideas profitable {year}',
    'automated trading strategies performance {year}',
    'API monetization developer tools revenue {year}',
    'passive income automation AI tools {year}',
    # Tech skills
    'Python trading bot libraries frameworks {year}',
    'MCP Model Context Protocol new servers tools {year}',
    'cTrader Open API advanced features automation',
    'Streamlit dashboard advanced features examples {year}',
]

_topic_index = 0
_last_self_task_time = 0
_SELF_TASK_INTERVAL = 300  # generate a new task every 5 minutes when idle

# ── Hourly digest state ──
_completed_this_hour = []  # list of {'title': ..., 'type': ..., 'sources': ...}
_last_digest_time = time.time()


def _generate_self_task():
    """Create a research task from the rotating topic list."""
    global _topic_index, _last_self_task_time
    now = time.time()
    if now - _last_self_task_time < _SELF_TASK_INTERVAL:
        return  # too soon

    topic_template = _RESEARCH_TOPICS[_topic_index % len(_RESEARCH_TOPICS)]
    _topic_index += 1
    now_dt = datetime.now(timezone.utc)
    topic = topic_template.format(
        month=now_dt.strftime('%B'),
        year=now_dt.year,
    )

    create_task(
        title=topic,
        assigned_to='natalia',
        task_type='research',
        params={'query': topic},
        priority=8,
        created_by='natalia-auto',
    )
    _last_self_task_time = now
    log.info(f'Self-generated research task: {topic}')


# ── Hourly digest reporting ──

def _record_completed_task(task_data: dict, result: dict):
    """Record a completed task for the hourly digest."""
    _completed_this_hour.append({
        'title': task_data.get('title', 'Unknown'),
        'type': task_data.get('task_type', '?'),
        'sources': result.get('sources_count', 0) if isinstance(result, dict) else 0,
        'time': datetime.now(timezone.utc).strftime('%H:%M'),
    })


def _maybe_send_digest():
    """Send an hourly digest of completed research to Telegram."""
    global _last_digest_time
    now = time.time()
    if now - _last_digest_time < REPORT_INTERVAL:
        return
    _last_digest_time = now

    if not _completed_this_hour:
        return  # Nothing to report

    try:
        import html as _html
        from lib.telegram import send_message

        count = len(_completed_this_hour)
        total_sources = sum(t['sources'] for t in _completed_this_hour)

        msg = "<b>⬡ ZEFF.BOT</b>\n"
        msg += "<b>📡 NATALIA — HOURLY DIGEST</b>\n"
        msg += f"<i>{datetime.now().strftime('%H:%M')}</i>\n\n"
        msg += f"<b>Tasks completed:</b> {count}\n"
        msg += f"<b>Sources consulted:</b> {total_sources}\n\n"

        for t in _completed_this_hour:
            icon = "🔍" if t['type'] == 'research' else "📋"
            title = _html.escape(t['title'][:60])
            msg += f"{icon} {title} ({t['sources']} sources)\n"

        send_message(msg)
        log.info(f"Hourly digest sent: {count} tasks, {total_sources} sources")
    except Exception as e:
        log.error(f"Failed to send hourly digest: {e}")

    _completed_this_hour.clear()


# ── Main loop ──

def update_status(status: str, current_task: str = None):
    """Write liveness status for dashboard."""
    data = {
        'bot': BOT_NAME,
        'status': status,
        'current_task': current_task,
        'last_heartbeat': datetime.now(timezone.utc).isoformat(),
        'pid': os.getpid(),
        'brave_api': bool(BRAVE_API_KEY),
    }
    try:
        atomic_json_write(STATUS_FILE, data)
    except Exception as e:
        log.warning(f'Failed to write status: {e}')


def process_tasks():
    """Check for and process pending tasks."""
    # Check timeouts first
    timed_out = check_timeouts()
    for t in timed_out:
        log.warning(f"Task {t['id']} timed out")

    # Get pending tasks — if none, self-generate
    tasks = get_pending_tasks(BOT_NAME)
    if not tasks:
        _generate_self_task()
        tasks = get_pending_tasks(BOT_NAME)
        if not tasks:
            return

    for task_data in tasks:
        task_id = task_data['id']
        task_type = task_data.get('task_type', '')
        handler = TASK_HANDLERS.get(task_type)

        if not handler:
            log.warning(f"Unknown task type '{task_type}' for task {task_id}")
            claimed = claim_task(task_id)
            if claimed:
                fail_task(task_id, f"Unknown task type: {task_type}")
            continue

        # Claim the task
        claimed = claim_task(task_id)
        if not claimed:
            log.warning(f"Failed to claim task {task_id}")
            continue

        log.info(f"Processing task {task_id}: {task_data['title']} (type={task_type})")
        update_status('working', task_data['title'])

        try:
            result = handler(claimed)
            complete_task(task_id, result)
            _record_completed_task(claimed, result)
            log.info(f"Task {task_id} completed successfully")
        except Exception as e:
            log.error(f"Task {task_id} failed: {e}")
            fail_task(task_id, str(e))

    update_status('idle')


def main():
    log.info('=' * 50)
    log.info('Natalia Runner starting')
    log.info(f'Brave API: {"configured" if BRAVE_API_KEY else "not configured (using DuckDuckGo)"}')
    log.info(f'Poll interval: {POLL_INTERVAL}s')
    log.info('=' * 50)

    update_status('idle')

    while True:
        try:
            process_tasks()
            _maybe_send_digest()
        except Exception as e:
            log.error(f'Error in main loop: {e}')
            update_status('error')

        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    main()
