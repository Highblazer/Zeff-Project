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
import html as _html
import requests
from datetime import datetime, timezone

sys.path.insert(0, '/root/.openclaw/workspace')
from lib.atomic_write import atomic_json_write, atomic_text_write
from lib.logging_config import get_logger
from lib.task_dispatch import (
    get_pending_tasks, claim_task, complete_task, fail_task, check_timeouts,
    create_task,
)
from lib.telegram import send_message as _send_telegram

log = get_logger('natalia', 'natalia.log')

POLL_INTERVAL = 15  # seconds
BOT_NAME = 'natalia'
STATUS_FILE = '/root/.openclaw/workspace/employees/natalia_status.json'
REPORT_INTERVAL = 3600  # send Telegram digest every 1 hour (seconds)

MEMORY_DIR = '/root/.openclaw/workspace/memory'
RESEARCH_LOG = os.path.join(MEMORY_DIR, 'natalia-research.md')
TRADEBOT_INTEL = os.path.join(MEMORY_DIR, 'tradebot-intel-natalia.md')
OPPORTUNITIES_FILE = os.path.join(MEMORY_DIR, 'opportunities.md')
MAX_MEMORY_LINES = 200

# Deduplication: track titles already persisted (survives across cycles in same process)
_seen_titles: set = set()

# Staleness tracking: alert when no search results for too long
_last_successful_search = datetime.now(timezone.utc)
_staleness_alerted = False

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
        else:
            log.warning(f'Brave web search returned HTTP {resp.status_code}: {resp.text[:200]}')
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
        else:
            log.warning(f'Brave news search returned HTTP {resp.status_code}: {resp.text[:200]}')
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
    global _last_successful_search
    results = brave_web_search(query, count)
    if results:
        _last_successful_search = datetime.now(timezone.utc)
        return results
    results = duckduckgo_search(query, count)
    if results:
        _last_successful_search = datetime.now(timezone.utc)
    return results


# ── Intelligence classification ──

_CATEGORY_KEYWORDS = {
    'market_mover': [
        'breaking', 'crash', 'surge', 'plunge', 'rate cut', 'rate hike',
        'recession', 'inflation', 'fed ', 'ecb ', 'boj ', 'central bank',
        'sanctions', 'tariff', 'war', 'election', 'default', 'crisis',
        'rally', 'sell-off', 'volatility', 'gdp', 'employment', 'nonfarm',
    ],
    'revenue_opportunity': [
        'api', 'saas', 'monetiz', 'revenue', 'profit', 'income', 'pricing',
        'launch', 'beta', 'free tier', 'affiliate', 'marketplace',
        'integration', 'automat', 'tool', 'service', 'platform', 'startup',
    ],
    'tech_upgrade': [
        'release', 'update', 'version', 'framework', 'library', 'sdk',
        'open source', 'github', 'benchmark', 'performance', 'upgrade',
        'model', 'llm', 'gpt', 'claude', 'agent', 'mcp', 'ctrader',
    ],
    'risk_alert': [
        'hack', 'breach', 'vulnerab', 'exploit', 'scam', 'fraud', 'ban',
        'shutdown', 'outage', 'deprecated', 'discontinue', 'lawsuit', 'sec ',
    ],
}


def _classify_finding(title: str, description: str) -> str:
    """Classify a finding into a category based on keyword matching."""
    text = (title + ' ' + description).lower()
    scores = {}
    for category, keywords in _CATEGORY_KEYWORDS.items():
        scores[category] = sum(1 for kw in keywords if kw in text)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else 'landscape'


def _score_actionability(title: str, description: str, category: str) -> float:
    """Score 0-1 how actionable a finding is (can we act on this now?)."""
    text = (title + ' ' + description).lower()
    score = 0.3  # base
    action_words = ['launch', 'available', 'release', 'free', 'open', 'new',
                    'now', 'today', 'announce', 'live', 'beta', 'api']
    score += 0.05 * sum(1 for w in action_words if w in text)
    if category in ('revenue_opportunity', 'tech_upgrade'):
        score += 0.1
    if category == 'market_mover':
        score += 0.15
    return min(score, 1.0)


def _score_impact(title: str, description: str, category: str) -> float:
    """Score 0-1 potential revenue/edge impact."""
    text = (title + ' ' + description).lower()
    score = 0.2  # base
    impact_words = ['major', 'significant', 'billion', 'million', 'record',
                    'unprecedented', 'historic', 'breakthrough', 'disrupt',
                    'massive', 'critical', 'urgent', 'emergency', 'surprise']
    score += 0.06 * sum(1 for w in impact_words if w in text)
    if category == 'market_mover':
        score += 0.2
    elif category == 'revenue_opportunity':
        score += 0.15
    elif category == 'risk_alert':
        score += 0.1
    return min(score, 1.0)


def _analyze_results(web_results: list, news_results: list, source_category: str = '') -> list:
    """Analyze search results into scored intelligence findings."""
    findings = []
    seen_titles = set()
    for r in news_results + web_results:
        title = r.get('title', '').strip()
        if not title or title.lower() in seen_titles:
            continue
        seen_titles.add(title.lower())

        desc = r.get('description', '') or ''
        category = _classify_finding(title, desc)
        # If the source search category hints at a type, boost agreement
        if source_category == 'market_movers' and category != 'market_mover':
            # Re-check with lower threshold
            text = (title + ' ' + desc).lower()
            if any(kw in text for kw in ['market', 'forex', 'bank', 'rate', 'econom', 'crypto']):
                category = 'market_mover'

        actionability = _score_actionability(title, desc, category)
        impact = _score_impact(title, desc, category)

        findings.append({
            'title': title,
            'url': r.get('url', ''),
            'description': desc[:300],
            'category': category,
            'actionability_score': round(actionability, 2),
            'impact_score': round(impact, 2),
            'combined_score': round((actionability + impact) / 2, 2),
            'age': r.get('age', ''),
            'recommended_action': _suggest_action(category, actionability, impact, title),
        })

    # Sort by combined score descending
    findings.sort(key=lambda f: f['combined_score'], reverse=True)
    return findings


def _suggest_action(category: str, actionability: float, impact: float, title: str) -> str:
    """Generate a recommended action based on category and scores."""
    if category == 'market_mover' and impact > 0.6:
        return 'ALERT trading bots — potential market impact'
    if category == 'revenue_opportunity' and actionability > 0.5:
        return 'EVALUATE for integration — potential revenue'
    if category == 'tech_upgrade' and actionability > 0.5:
        return 'REVIEW for OpenClaw fleet upgrade'
    if category == 'risk_alert':
        return 'MONITOR — potential risk to operations'
    return 'LOG for awareness'


# ── Persistent memory writer ──

def _persist_intelligence(findings: list, task_title: str):
    """Write analyzed findings to persistent memory files.

    - natalia-research.md: all high-value findings (timestamped)
    - tradebot-intel-natalia.md: market-relevant intelligence for trading bots
    - opportunities.md: revenue ideas, tools to evaluate

    Deduplicates by title — same article never written twice.
    """
    if not findings:
        return

    os.makedirs(MEMORY_DIR, exist_ok=True)
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    # ── Dedup: seed _seen_titles from existing files on first call ──
    if not _seen_titles:
        for fp in (RESEARCH_LOG, TRADEBOT_INTEL, OPPORTUNITIES_FILE):
            if os.path.isfile(fp):
                try:
                    with open(fp, 'r') as fh:
                        for line in fh:
                            # Titles appear as **Title** in markdown
                            m = re.search(r'\*\*(.+?)\*\*', line)
                            if m:
                                _seen_titles.add(m.group(1).strip().lower())
                except Exception:
                    pass

    # Filter out findings we've already persisted
    new_findings = []
    for f in findings:
        key = f['title'].strip().lower()
        if key not in _seen_titles:
            new_findings.append(f)
            _seen_titles.add(key)

    if not new_findings:
        log.info('Persisted intelligence: 0 new (all duplicates filtered)')
        return

    # ── 1. natalia-research.md — all significant findings ──
    significant = [f for f in new_findings if f['combined_score'] >= 0.3]
    if significant:
        lines = [f'\n## {now} — {task_title}', '']
        for f in significant[:5]:
            cat_icon = {'market_mover': '📊', 'revenue_opportunity': '💰',
                        'tech_upgrade': '🔧', 'risk_alert': '⚠️'}.get(f['category'], '📋')
            lines.append(f"- {cat_icon} **[{f['category']}]** {f['title']}")
            lines.append(f"  Score: {f['combined_score']} | Action: {f['recommended_action']}")
            if f['description']:
                lines.append(f"  > {f['description'][:150]}")
            lines.append('')
        _append_to_memory(RESEARCH_LOG, '\n'.join(lines),
                          header='# Natalia Intelligence Log\n')

    # ── 2. tradebot-intel-natalia.md — market movers for trading bots ──
    market = [f for f in new_findings if f['category'] in ('market_mover', 'risk_alert')]
    if market:
        lines = [f'\n### {now}', '']
        for f in market[:5]:
            lines.append(f"- **{f['title']}** (impact: {f['impact_score']})")
            if f['description']:
                lines.append(f"  > {f['description'][:150]}")
            lines.append(f"  Action: {f['recommended_action']}")
            lines.append('')
        _append_to_memory(TRADEBOT_INTEL, '\n'.join(lines),
                          header='# Natalia Market Intelligence for Trading Bots\n'
                                 '> Analyzed findings — not just headlines\n')

    # ── 3. opportunities.md — revenue opportunities ──
    opps = [f for f in new_findings
            if f['category'] == 'revenue_opportunity' and f['actionability_score'] >= 0.4]
    if opps:
        lines = [f'\n### {now}', '']
        for f in opps[:3]:
            lines.append(f"- 💰 **{f['title']}**")
            lines.append(f"  Actionability: {f['actionability_score']} | Impact: {f['impact_score']}")
            if f['description']:
                lines.append(f"  > {f['description'][:150]}")
            lines.append(f"  Recommended: {f['recommended_action']}")
            lines.append('')
        _append_to_memory(OPPORTUNITIES_FILE, '\n'.join(lines),
                          header='# Revenue Opportunities & Tool Evaluations\n'
                                 '> Curated by Natalia intelligence analysis\n')

    log.info(f'Persisted intelligence: {len(significant)} research, '
             f'{len(market)} market, {len(opps)} opportunities')


def _append_to_memory(filepath: str, content: str, header: str = ''):
    """Append content to a memory file, capping at MAX_MEMORY_LINES."""
    existing = ''
    if os.path.isfile(filepath):
        with open(filepath, 'r') as f:
            existing = f.read()

    if not existing.strip():
        existing = header

    combined = existing.rstrip('\n') + '\n' + content + '\n'

    # Cap at MAX_MEMORY_LINES — prune oldest entries (keep header + newest)
    lines = combined.split('\n')
    if len(lines) > MAX_MEMORY_LINES:
        # Keep header (first 3 lines) + newest entries
        header_lines = lines[:3]
        keep_lines = lines[-(MAX_MEMORY_LINES - 3):]
        lines = header_lines + ['', '*(older entries pruned)*', ''] + keep_lines

    atomic_text_write(filepath, '\n'.join(lines))


# ── Market mover alert fast-path ──

_market_alert_count = 0


def _check_market_alerts(findings: list):
    """Send immediate Telegram alert for high-impact market movers."""
    global _market_alert_count
    for f in findings:
        if (f['category'] == 'market_mover'
                and f['impact_score'] > 0.7
                and f['actionability_score'] > 0.5):
            try:
                msg = "<b>⬡ ZEFF.BOT</b>\n"
                msg += "<b>🚨 MARKET ALERT</b>\n\n"
                msg += f"<b>{_html.escape(f['title'][:80])}</b>\n"
                msg += f"Impact: {f['impact_score']} | Actionability: {f['actionability_score']}\n"
                if f['description']:
                    msg += f"\n{_html.escape(f['description'][:200])}\n"
                msg += f"\n<i>Action: {_html.escape(f['recommended_action'])}</i>"
                _send_telegram(msg)
                _market_alert_count += 1
                log.info(f"MARKET ALERT sent: {f['title'][:60]}")
            except Exception as e:
                log.error(f"Failed to send market alert: {e}")


# ── Task handlers ──

def handle_intelligence(task: dict) -> dict:
    """Execute an intelligence task: search, analyze, classify, score, persist."""
    params = task.get('params', {})
    query = params.get('query', task.get('title', ''))
    source_category = params.get('category', '')
    count = params.get('count', 5)

    log.info(f'Intelligence scan: {query}')

    web_results = search(query, count)
    news_results = brave_news_search(query, count) if BRAVE_API_KEY else []

    # Analyze and score findings
    findings = _analyze_results(web_results, news_results, source_category)

    # Persist to memory files
    _persist_intelligence(findings, query)

    # Check for high-impact market alerts
    _check_market_alerts(findings)

    # Auto-generate evaluate tasks for high-scoring opportunities
    for f in findings[:2]:
        if (f['category'] == 'revenue_opportunity'
                and f['actionability_score'] >= 0.6
                and f['impact_score'] >= 0.5):
            create_task(
                title=f"Evaluate: {f['title'][:60]}",
                assigned_to='natalia',
                task_type='evaluate',
                params={'topic': f['title'], 'url': f['url'],
                        'description': f['description']},
                priority=4,
                created_by='natalia-intel',
            )
            log.info(f"Auto-generated evaluate task for: {f['title'][:50]}")

    # Build summary
    summary = f"Intelligence: {query}\n\nFindings ({len(findings)}):\n"
    for f in findings[:5]:
        summary += (f"- [{f['category']}] {f['title']} "
                     f"(action={f['actionability_score']}, impact={f['impact_score']})\n")
        summary += f"  → {f['recommended_action']}\n"

    return {
        'summary': summary,
        'findings': findings[:10],
        'query': query,
        'sources_count': len(web_results) + len(news_results),
        'findings_count': len(findings),
        'market_movers': len([f for f in findings if f['category'] == 'market_mover']),
        'opportunities': len([f for f in findings if f['category'] == 'revenue_opportunity']),
    }


def handle_evaluate(task: dict) -> dict:
    """Deep-dive evaluation of a tool, API, or opportunity."""
    params = task.get('params', {})
    topic = params.get('topic', task.get('title', ''))
    base_description = params.get('description', '')

    log.info(f'Evaluating: {topic}')

    # Run multiple focused queries
    eval_queries = [
        f'{topic} pricing cost',
        f'{topic} API integration guide',
        f'{topic} review comparison alternatives',
    ]

    all_results = []
    for q in eval_queries:
        results = search(q, 3)
        all_results.extend(results)

    # Extract pricing/effort/potential signals from results
    all_text = ' '.join(
        (r.get('title', '') + ' ' + r.get('description', '')).lower()
        for r in all_results
    )

    # Heuristic effort estimation
    effort = 'low'
    if any(w in all_text for w in ['complex', 'enterprise', 'custom', 'difficult']):
        effort = 'high'
    elif any(w in all_text for w in ['setup', 'configure', 'moderate', 'documentation']):
        effort = 'medium'

    # Heuristic revenue potential
    revenue = 'low'
    if any(w in all_text for w in ['revenue', 'profit', 'million', 'popular', 'growing']):
        revenue = 'high'
    elif any(w in all_text for w in ['monetize', 'income', 'market', 'demand']):
        revenue = 'medium'

    recommended = (effort != 'high' and revenue != 'low')

    # Build next steps
    next_steps = []
    if recommended:
        next_steps.append(f'Sign up / get API key for {topic}')
        next_steps.append('Build proof-of-concept integration')
        next_steps.append('Test with OpenClaw fleet')
    else:
        next_steps.append(f'Monitor {topic} for changes')
        next_steps.append('Revisit if effort decreases or revenue potential increases')

    evaluation = {
        'tool_name': topic,
        'description': base_description[:200] or f'Evaluation of {topic}',
        'integration_effort': effort,
        'revenue_potential': revenue,
        'recommended': recommended,
        'next_steps': next_steps,
        'sources_consulted': len(all_results),
    }

    # Write to opportunities.md
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    eval_lines = [
        f'\n### EVALUATION: {topic} ({now})',
        f'**Effort:** {effort} | **Revenue:** {revenue} | '
        f'**Recommended:** {"YES ✅" if recommended else "NO ❌"}',
        f'> {evaluation["description"]}',
        '',
        '**Next Steps:**',
    ]
    for step in next_steps:
        eval_lines.append(f'- {step}')
    eval_lines.append('')

    _append_to_memory(OPPORTUNITIES_FILE, '\n'.join(eval_lines),
                      header='# Revenue Opportunities & Tool Evaluations\n'
                             '> Curated by Natalia intelligence analysis\n')

    log.info(f'Evaluation complete: {topic} — recommended={recommended}')

    return {
        'summary': f"Evaluation: {topic} — effort={effort}, revenue={revenue}, recommended={recommended}",
        'evaluation': evaluation,
        'sources_count': len(all_results),
    }


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
    'intelligence': handle_intelligence,
    'evaluate': handle_evaluate,
}


# ── Self-generating intelligence topics (weighted dual-track) ──
# Natalia rotates through these when idle — never stops working.
# Higher-weight categories are sampled more frequently.

_INTELLIGENCE_TOPICS = {
    'market_movers': {  # weight: 3 — run 3x more often
        'weight': 3,
        'topics': [
            'breaking forex market news {month} {year}',
            'central bank surprise decisions {month} {year}',
            'geopolitical events affecting markets {month} {year}',
            'cryptocurrency regulatory news {month} {year}',
            'economic calendar high impact events this week',
        ],
    },
    'revenue_opportunities': {  # weight: 3
        'weight': 3,
        'topics': [
            'new AI APIs tools monetization {month} {year}',
            'automated trading strategies profitable {year}',
            'AI SaaS micro-products revenue {year}',
            'freelance automation AI services demand {year}',
            'API monetization developer tools revenue {year}',
        ],
    },
    'tech_upgrades': {  # weight: 2
        'weight': 2,
        'topics': [
            'AI agent framework comparison {year}',
            'cTrader API new features updates',
            'Python trading libraries new releases {year}',
            'MCP server new tools integrations {year}',
            'Streamlit dashboard advanced features examples {year}',
        ],
    },
    'landscape': {  # weight: 1
        'weight': 1,
        'topics': [
            'latest LLM model releases {month} {year}',
            'AI industry news summary {month} {year}',
            'new AI agent frameworks tools launched {month} {year}',
            'machine learning infrastructure trends {year}',
        ],
    },
}

# Build weighted topic list: each (category, topic) appears `weight` times
_WEIGHTED_TOPIC_LIST = []
for _cat, _info in _INTELLIGENCE_TOPICS.items():
    for _topic in _info['topics']:
        _WEIGHTED_TOPIC_LIST.extend([(_cat, _topic)] * _info['weight'])

_topic_index = 0
_last_self_task_time = 0
_SELF_TASK_INTERVAL = 300  # generate a new task every 5 minutes when idle

# ── Hourly digest state ──
_completed_this_hour = []  # list of {'title': ..., 'type': ..., 'sources': ..., ...}
_findings_persisted_this_hour = 0
_top_opportunity_this_hour = None  # best opportunity title
_last_digest_time = time.time()


def _generate_self_task():
    """Create an intelligence task from the weighted topic rotation."""
    global _topic_index, _last_self_task_time
    now = time.time()
    if now - _last_self_task_time < _SELF_TASK_INTERVAL:
        return  # too soon

    category, topic_template = _WEIGHTED_TOPIC_LIST[_topic_index % len(_WEIGHTED_TOPIC_LIST)]
    _topic_index += 1
    now_dt = datetime.now(timezone.utc)
    topic = topic_template.format(
        month=now_dt.strftime('%B'),
        year=now_dt.year,
    )

    create_task(
        title=topic,
        assigned_to='natalia',
        task_type='intelligence',
        params={'query': topic, 'category': category},
        priority=8,
        created_by='natalia-auto',
    )
    _last_self_task_time = now
    log.info(f'Self-generated intelligence task [{category}]: {topic}')


# ── Hourly digest reporting ──

def _record_completed_task(task_data: dict, result: dict):
    """Record a completed task for the hourly digest."""
    global _findings_persisted_this_hour, _top_opportunity_this_hour

    entry = {
        'title': task_data.get('title', 'Unknown'),
        'type': task_data.get('task_type', '?'),
        'sources': result.get('sources_count', 0) if isinstance(result, dict) else 0,
        'time': datetime.now(timezone.utc).strftime('%H:%M'),
    }

    if isinstance(result, dict):
        entry['findings_count'] = result.get('findings_count', 0)
        entry['market_movers'] = result.get('market_movers', 0)
        entry['opportunities'] = result.get('opportunities', 0)
        _findings_persisted_this_hour += entry['findings_count']

        # Track top opportunity
        findings = result.get('findings', [])
        for f in findings:
            if f.get('category') == 'revenue_opportunity':
                if (_top_opportunity_this_hour is None
                        or f.get('combined_score', 0) > _top_opportunity_this_hour.get('score', 0)):
                    _top_opportunity_this_hour = {
                        'title': f.get('title', ''),
                        'score': f.get('combined_score', 0),
                    }

    _completed_this_hour.append(entry)


def _maybe_send_digest():
    """Send an hourly digest of completed intelligence to Telegram."""
    global _last_digest_time, _findings_persisted_this_hour
    global _top_opportunity_this_hour, _market_alert_count
    now = time.time()
    if now - _last_digest_time < REPORT_INTERVAL:
        return
    _last_digest_time = now

    if not _completed_this_hour:
        return  # Nothing to report

    try:
        count = len(_completed_this_hour)
        total_sources = sum(t['sources'] for t in _completed_this_hour)
        total_market = sum(t.get('market_movers', 0) for t in _completed_this_hour)
        total_opps = sum(t.get('opportunities', 0) for t in _completed_this_hour)

        msg = "<b>⬡ ZEFF.BOT</b>\n"
        msg += "<b>📡 NATALIA — HOURLY INTELLIGENCE DIGEST</b>\n"
        msg += f"<i>{datetime.now().strftime('%H:%M')}</i>\n\n"
        msg += f"<b>Tasks completed:</b> {count}\n"
        msg += f"<b>Sources consulted:</b> {total_sources}\n"
        msg += f"<b>Findings persisted to memory:</b> {_findings_persisted_this_hour}\n"
        msg += f"<b>Market movers detected:</b> {total_market}\n"
        msg += f"<b>Revenue opportunities:</b> {total_opps}\n"
        msg += f"<b>Priority alerts sent:</b> {_market_alert_count}\n\n"

        if _top_opportunity_this_hour:
            opp_title = _html.escape(_top_opportunity_this_hour['title'][:60])
            msg += f"💰 <b>Top opportunity:</b> {opp_title}\n\n"

        for t in _completed_this_hour:
            icons = {
                'intelligence': '🧠', 'research': '🔍',
                'evaluate': '📊', 'report': '📋',
            }
            icon = icons.get(t['type'], '📋')
            title = _html.escape(t['title'][:60])
            msg += f"{icon} {title} ({t['sources']} src)\n"

        _send_telegram(msg)
        log.info(f"Hourly digest sent: {count} tasks, {total_sources} sources, "
                 f"{_findings_persisted_this_hour} findings persisted")
    except Exception as e:
        log.error(f"Failed to send hourly digest: {e}")

    _completed_this_hour.clear()
    _findings_persisted_this_hour = 0
    _top_opportunity_this_hour = None
    _market_alert_count = 0


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

    # Validate Brave API key at startup
    if BRAVE_API_KEY:
        try:
            test_resp = requests.get(
                'https://api.search.brave.com/res/v1/web/search',
                headers={'Accept': 'application/json', 'X-Subscription-Token': BRAVE_API_KEY},
                params={'q': 'test', 'count': 1},
                timeout=10,
            )
            if test_resp.status_code == 200:
                log.info('Brave API key validated successfully')
            else:
                log.error(f'Brave API key INVALID (HTTP {test_resp.status_code}): {test_resp.text[:200]}')
                _send_telegram(
                    '<b>⬡ NATALIA</b>\n'
                    f'<b>WARNING:</b> Brave API key invalid (HTTP {test_resp.status_code})\n'
                    'Falling back to DuckDuckGo only.\n'
                    'Please update BRAVE_SEARCH_API_KEY in .env'
                )
                # Don't exit — DuckDuckGo fallback still works
        except Exception as e:
            log.error(f'Brave API validation failed: {e}')
    else:
        log.warning('No Brave API key configured — using DuckDuckGo only')
        _send_telegram(
            '<b>⬡ NATALIA</b>\n'
            '<b>WARNING:</b> No Brave API key configured\n'
            'Using DuckDuckGo search only (limited results)'
        )

    while True:
        try:
            process_tasks()
            _maybe_send_digest()

            # Check for search staleness (no results for 2+ hours)
            global _staleness_alerted
            stale_seconds = (datetime.now(timezone.utc) - _last_successful_search).total_seconds()
            if stale_seconds > 7200 and not _staleness_alerted:
                _staleness_alerted = True
                log.warning(f'No successful searches for {stale_seconds/3600:.1f} hours')
                _send_telegram(
                    '<b>⬡ NATALIA</b>\n'
                    f'<b>WARNING:</b> No successful searches for {stale_seconds/3600:.1f} hours\n'
                    'Search backends may be down or API key expired'
                )
            elif stale_seconds < 3600:
                _staleness_alerted = False
        except Exception as e:
            log.error(f'Error in main loop: {e}')
            update_status('error')

        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    main()
