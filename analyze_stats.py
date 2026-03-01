#!/usr/bin/env python3
"""
Analyze build status from pages/index.md
Prints statistics to stdout
"""

import re
from collections import defaultdict, Counter
from datetime import datetime

INDEX_FILE = 'pages/index.md'

def parse_index():
    stats = {
        'by_arch': defaultdict(lambda: {'total':0, 'PUBLISHED':0, 'FAILED':0, 'STALE':0, 'BUILDING':0}),
        'by_status': Counter(),
        'fail_details': Counter(),
        'total': 0,
        'packages': []
    }

    pattern = re.compile(r'\|([^|]+)\|\[([^\]]+)\]\([^)]+\)\|([A-Z]+)\|([^|]*)\|')
    with open(INDEX_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            m = pattern.search(line)
            if m:
                category = m.group(1).strip()
                pkgbase = m.group(2)
                status = m.group(3)
                detail = m.group(4).strip()

                base_arch = category.split('/')[0] if '/' in category else category
                if base_arch not in ['aarch64', 'x86_64', 'any']:
                    base_arch = 'unknown'

                stats['total'] += 1
                stats['by_arch'][base_arch]['total'] += 1
                if status in stats['by_arch'][base_arch]:
                    stats['by_arch'][base_arch][status] += 1
                stats['by_status'][status] += 1
                stats['packages'].append((category, pkgbase, status, detail))

                if status == 'FAILED':
                    if detail:
                        simple = detail.split('.')[0].split('\n')[0].strip()
                        if len(simple) > 60:
                            simple = simple[:57] + '...'
                        stats['fail_details'][simple] += 1
                    else:
                        stats['fail_details']['(no detail)'] += 1
    return stats

def print_report(stats):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    lines = [
        f"# Build Status Analysis",
        f"*Generated: {now}*",
        "",
        f"## Overall Summary",
        f"- **Total packages**: {stats['total']}",
        "",
        "| Status | Count | Percentage |",
        "|--------|-------|------------|",
    ]

    for status in ['PUBLISHED', 'FAILED', 'STALE', 'BUILDING']:
        count = stats['by_status'].get(status, 0)
        pct = (count / stats['total'] * 100) if stats['total'] > 0 else 0
        lines.append(f"| {status} | {count} | {pct:.1f}% |")

    lines.extend([
        "",
        f"## By Architecture",
        "| Arch | Total | PUBLISHED | FAILED | STALE | BUILDING | Success Rate |",
        "|------|-------|-----------|--------|-------|----------|--------------|",
    ])

    for arch in sorted(stats['by_arch'].keys()):
        a = stats['by_arch'][arch]
        total = a['total']
        pub = a.get('PUBLISHED', 0)
        fail = a.get('FAILED', 0)
        stale = a.get('STALE', 0)
        building = a.get('BUILDING', 0)
        success = (pub / total * 100) if total > 0 else 0
        lines.append(f"| {arch} | {total} | {pub} | {fail} | {stale} | {building} | {success:.1f}% |")

    if stats['fail_details']:
        lines.extend([
            "",
            f"## Top Build Failure Reasons",
            "| Reason | Count |",
            "|--------|-------|",
        ])
        for reason, cnt in stats['fail_details'].most_common(10):
            lines.append(f"| {reason} | {cnt} |")

    stale_pkgs = [p for p in stats['packages'] if p[2] == 'STALE']
    if stale_pkgs:
        lines.extend([
            "",
            f"## Stale Packages ({len(stale_pkgs)})",
            "| Category | Package |",
            "|----------|---------|",
        ])
        for cat, pkgbase, _, _ in sorted(stale_pkgs, key=lambda x: x[1])[:50]:
            lines.append(f"| {cat} | {pkgbase} |")

    failed_pkgs = [p for p in stats['packages'] if p[2] == 'FAILED']
    if failed_pkgs:
        lines.extend([
            "",
            f"## Failed Packages ({len(failed_pkgs)})",
            "| Category | Package | Detail |",
            "|----------|---------|--------|",
        ])
        for cat, pkgbase, _, detail in sorted(failed_pkgs, key=lambda x: x[1])[:50]:
            detail_short = detail[:40] + ('...' if len(detail) > 40 else '')
            lines.append(f"| {cat} | {pkgbase} | {detail_short} |")

    lines.append("")
    lines.append("*Note: This analysis is based on the current `index.md` in the Pages repository.*")
    print('\n'.join(lines))

if __name__ == '__main__':
    stats = parse_index()
    print_report(stats)
