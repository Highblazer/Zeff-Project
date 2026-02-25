#!/usr/bin/env python3
"""
Natalia Runner — Chief Research Officer task execution loop.

Polls for pending tasks, executes research / report / deep_research handlers,
writes results back via the task dispatch system.

Usage:
    python employees/natalia-runner.py          # Run forever (poll loop)
    python employees/natalia-runner.py --once   # Process one task and exit
"""

import json
import os
import sys
import time
import argparse

# Ensure workspace root is on the path
sys.path.insert(0, '/root/.openclaw/workspace')

from lib.task_dispatch import get_pending_tasks, claim_task, complete_task, fail_task
from lib.logging_config import get_logger
from lib.browser_extract import extract_multiple

import requests

log = get_logger('natalia', log_file='natalia.log')

BOT_NAME = 'natalia'
POLL_INTERVAL = 10  # seconds between polls

# Brave Search API
BRAVE_API_KEY = os.environ.get('BRAVE_API_KEY', '')
BRAVE_WEB_URL = 'https://api.brave.com/res/v1/web/search'
BRAVE_NEWS_URL = 'https://api.brave.com/res/v1/news/search'
BRAVE_TIMEOUT = 15


# ═══════════════════════════════════════════════════════════
#  Brave Search helpers
# ═══════════════════════════════════════════════════════════

def _brave_search(query: str, count: int = 5, endpoint: str = 'web') -> list:
    """Run a Brave Search API query. Returns list of result dicts."""
    if not BRAVE_API_KEY:
        log.warning('BRAVE_API_KEY not set — search disabled')
        return []

    url = BRAVE_WEB_URL if endpoint == 'web' else BRAVE_NEWS_URL
    headers = {
        'Accept': 'application/json',
        'X-Subscription-Token': BRAVE_API_KEY,
    }
    params = {'q': query, 'count': min(count, 20)}

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=BRAVE_TIMEOUT)
        if resp.status_code != 200:
            log.error(f'Brave {endpoint} search failed: HTTP {resp.status_code}')
            return []
        data = resp.json()
    except Exception as e:
        log.error(f'Brave {endpoint} search error: {e}')
        return []

    if endpoint == 'web':
        raw = data.get('web', {}).get('results', [])
        return [
            {
                'title': r.get('title', ''),
                'url': r.get('url', ''),
                'description': r.get('description', ''),
            }
            for r in raw[:count]
        ]
    else:
        raw = data.get('results', [])
        return [
            {
                'title': r.get('title', ''),
                'url': r.get('url', ''),
                'description': r.get('description', ''),
                'age': r.get('age', ''),
            }
            for r in raw[:count]
        ]


# ═══════════════════════════════════════════════════════════
#  Content Extraction helpers
# ═══════════════════════════════════════════════════════════

def enrich_results_with_content(web_results: list, max_urls: int = 5,
                                budget: int = 60) -> list:
    """Extract full page content for top results and attach to each result dict.

    Adds 'full_content' (str) and 'extraction_meta' (dict) fields.
    Original snippet is preserved in 'description'.
    """
    urls = [r['url'] for r in web_results[:max_urls] if r.get('url')]
    if not urls:
        return web_results

    extractions = extract_multiple(urls, max_urls=max_urls, budget_seconds=budget)
    ext_map = {e['url']: e for e in extractions}

    for r in web_results:
        ext = ext_map.get(r.get('url'))
        if ext and ext['success']:
            r['full_content'] = ext['content']
            r['extraction_meta'] = {
                'method': ext['method'],
                'char_count': ext['char_count'],
                'title': ext['title'],
            }
        else:
            r['full_content'] = ''
            r['extraction_meta'] = {
                'method': '',
                'char_count': 0,
                'error': ext['error'] if ext else 'not attempted',
            }

    return web_results


# ═══════════════════════════════════════════════════════════
#  Summary builders
# ═══════════════════════════════════════════════════════════

def _build_summary(query: str, web_results: list, news_results: list,
                   excerpt_len: int = 300) -> str:
    """Build a markdown research summary from results."""
    lines = [f'# Research: {query}', '']

    if web_results:
        lines.append('## Web Results')
        for r in web_results:
            lines.append(f'### {r["title"]}')
            lines.append(f'**URL:** {r["url"]}')
            # Use full_content excerpt if available, else snippet
            if r.get('full_content'):
                excerpt = r['full_content'][:excerpt_len].strip()
                meta = r.get('extraction_meta', {})
                method = meta.get('method', 'unknown')
                lines.append(f'**Content ({method}, {meta.get("char_count", 0)} chars):**')
                lines.append(excerpt + '...')
            elif r.get('description'):
                lines.append(f'**Snippet:** {r["description"]}')
            lines.append('')

    if news_results:
        lines.append('## News Results')
        for r in news_results:
            age = f' ({r["age"]})' if r.get('age') else ''
            lines.append(f'- **{r["title"]}**{age}')
            lines.append(f'  {r["url"]}')
            if r.get('full_content'):
                excerpt = r['full_content'][:excerpt_len].strip()
                lines.append(f'  {excerpt}...')
            elif r.get('description'):
                lines.append(f'  {r["description"]}')
        lines.append('')

    if not web_results and not news_results:
        lines.append('*No results found.*')

    return '\n'.join(lines)


# ═══════════════════════════════════════════════════════════
#  Task Handlers
# ═══════════════════════════════════════════════════════════

def handle_research(task: dict) -> dict:
    """Standard research: web + news search. Optional content extraction via params.extract."""
    params = task.get('params', {})
    query = params.get('query', task.get('title', ''))
    count = params.get('count', 5)
    do_extract = params.get('extract', False)
    extract_count = params.get('extract_count', 3)

    log.info(f'Research: "{query}" (count={count}, extract={do_extract})')

    # Brave searches
    web_results = _brave_search(query, count=count, endpoint='web')
    news_results = _brave_search(query, count=count, endpoint='news')

    # Optional extraction
    if do_extract and web_results:
        log.info(f'Extracting content from top {extract_count} results')
        web_results = enrich_results_with_content(
            web_results, max_urls=extract_count, budget=60
        )

    summary = _build_summary(query, web_results, news_results, excerpt_len=300)

    return {
        'query': query,
        'summary': summary,
        'web_results': web_results,
        'news_results': news_results,
        'sources_count': len(web_results) + len(news_results),
        'extracted': do_extract,
    }


def handle_report(task: dict) -> dict:
    """Multi-query research report — runs several queries and combines results."""
    params = task.get('params', {})
    topic = params.get('topic', task.get('title', ''))
    queries = params.get('queries', [topic])

    log.info(f'Report: "{topic}" ({len(queries)} queries)')

    all_web = []
    all_news = []
    for q in queries:
        web = _brave_search(q, count=5, endpoint='web')
        news = _brave_search(q, count=3, endpoint='news')
        all_web.extend(web)
        all_news.extend(news)

    summary = _build_summary(topic, all_web, all_news, excerpt_len=300)

    return {
        'topic': topic,
        'report': summary,
        'queries_run': queries,
        'sources_count': len(all_web) + len(all_news),
        'web_results': all_web,
        'news_results': all_news,
    }


def handle_deep_research(task: dict) -> dict:
    """Deep research: web + news search with full content extraction on all top results.

    Always extracts. Higher time budget (120s). Richer excerpts (~500 chars).
    """
    params = task.get('params', {})
    query = params.get('query', task.get('title', ''))
    count = params.get('count', 8)
    max_extract = params.get('extract_count', 5)

    log.info(f'Deep research: "{query}" (count={count}, extract_count={max_extract})')

    # Brave searches — cast wider net
    web_results = _brave_search(query, count=count, endpoint='web')
    news_results = _brave_search(query, count=count, endpoint='news')

    # Always extract content from top results
    if web_results:
        log.info(f'Deep extracting content from top {max_extract} web results')
        web_results = enrich_results_with_content(
            web_results, max_urls=max_extract, budget=120
        )

    # Also try extracting from news
    if news_results:
        news_extract_count = min(3, len(news_results))
        log.info(f'Deep extracting content from top {news_extract_count} news results')
        news_results = enrich_results_with_content(
            news_results, max_urls=news_extract_count, budget=30
        )

    summary = _build_summary(query, web_results, news_results, excerpt_len=500)

    extracted_count = sum(
        1 for r in web_results + news_results
        if r.get('full_content')
    )

    return {
        'query': query,
        'summary': summary,
        'web_results': web_results,
        'news_results': news_results,
        'sources_count': len(web_results) + len(news_results),
        'extracted': True,
        'extracted_count': extracted_count,
    }


# ═══════════════════════════════════════════════════════════
#  Handler registry & dispatch
# ═══════════════════════════════════════════════════════════

TASK_HANDLERS = {
    'research': handle_research,
    'report': handle_report,
    'deep_research': handle_deep_research,
}


def process_task(task: dict):
    """Claim and execute a single task."""
    task_id = task['id']
    task_type = task.get('task_type', '')

    claimed = claim_task(task_id)
    if not claimed:
        log.warning(f'Could not claim task {task_id} — already taken?')
        return

    handler = TASK_HANDLERS.get(task_type)
    if not handler:
        fail_task(task_id, f'Unknown task type: {task_type}')
        log.error(f'Unknown task type "{task_type}" for task {task_id}')
        return

    log.info(f'Processing task {task_id} [{task_type}]: {task.get("title", "")}')

    try:
        result = handler(claimed)
        complete_task(task_id, result)
        log.info(f'Task {task_id} completed successfully')
    except Exception as e:
        log.exception(f'Task {task_id} failed: {e}')
        fail_task(task_id, str(e))


# ═══════════════════════════════════════════════════════════
#  Main loop
# ═══════════════════════════════════════════════════════════

def run_once():
    """Process the highest-priority pending task, if any."""
    tasks = get_pending_tasks(BOT_NAME)
    if not tasks:
        return False
    process_task(tasks[0])
    return True


def run_forever():
    """Poll for tasks forever."""
    log.info('Natalia runner started — polling for tasks')
    while True:
        try:
            tasks = get_pending_tasks(BOT_NAME)
            if tasks:
                process_task(tasks[0])
            else:
                time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            log.info('Natalia runner stopped by user')
            break
        except Exception as e:
            log.exception(f'Runner loop error: {e}')
            time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Natalia task runner')
    parser.add_argument('--once', action='store_true', help='Process one task and exit')
    args = parser.parse_args()

    if args.once:
        found = run_once()
        sys.exit(0 if found else 1)
    else:
        run_forever()
