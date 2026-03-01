#!/usr/bin/env python3
"""
Analyze build status from pages/index.md
Provides detailed failure categorization similar to analyze_actions_complete.py
"""

import re
from collections import defaultdict, Counter
from datetime import datetime

INDEX_FILE = 'pages/index.md'

def parse_index():
    stats = {
        'by_category': defaultdict(lambda: {'total':0, 'PUBLISHED':0, 'FAILED':0, 'STALE':0, 'BUILDING':0}),
        'by_status': Counter(),
        'fail_details': Counter(),
        'total': 0,
        'packages': []  # (category, pkgbase, status, detail, run_id)
    }

    # Match 6 columns: Category | Package | Status | Detail | Workflow | Timestamp
    pattern = re.compile(r'\|([^|]+)\|\[([^\]]+)\]\([^)]+\)\|([A-Z]+)\|([^|]*)\|([^|]*)\|([^|]*)\|')
    with open(INDEX_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            m = pattern.search(line)
            if m:
                category = m.group(1).strip()
                pkgbase = m.group(2)
                status = m.group(3)
                detail = m.group(4).strip()
                workflow = m.group(5).strip()
                # Extract run_id from workflow (e.g., "[1234567890](url)")
                run_id = ''
                if workflow:
                    run_match = re.search(r'\[(\d+)\]', workflow)
                    if run_match:
                        run_id = run_match.group(1)

                stats['total'] += 1
                stats['by_category'][category]['total'] += 1
                if status in stats['by_category'][category]:
                    stats['by_category'][category][status] += 1
                stats['by_status'][status] += 1
                stats['packages'].append((category, pkgbase, status, detail, run_id))

                if status == 'FAILED':
                    if detail:
                        simple = detail.split('.')[0].split('\n')[0].strip()
                        if len(simple) > 60:
                            simple = simple[:57] + '...'
                        stats['fail_details'][simple] += 1
                    else:
                        stats['fail_details']['(no detail)'] += 1
    return stats

def extract_missing_dependencies(detail):
    """Extract missing dependency package names from detail string (without version constraints)"""
    if not detail:
        return []
    lower = detail.lower()
    missing = []
    # Pattern: "Missing dependencies: pkg1, pkg2 (with version >=...)"
    if 'missing dependencies' in lower:
        match = re.search(r'Missing dependencies[:\s]+(.+)', detail, re.IGNORECASE)
        if match:
            deps_str = match.group(1)
            # Split by comma
            for dep in deps_str.split(','):
                dep = dep.strip()
                if not dep:
                    continue
                # Remove version constraints like ">=3.11.0", " (>= 14.1.0)"
                # Take only package name portion
                # Remove anything after first space, '>', '<', '('
                for sep in [' ', '>', '<', '(']:
                    if sep in dep:
                        dep = dep.split(sep)[0].strip()
                if dep:
                    missing.append(dep)
    # Pattern: "Failed to download dependencies: pkg"
    elif 'failed to download dependencies' in lower:
        match = re.search(r'Failed to download dependencies[:\s]+(.+)', detail, re.IGNORECASE)
        if match:
            deps_str = match.group(1)
            for dep in deps_str.split(','):
                dep = dep.strip()
                if dep:
                    missing.append(dep)
    return missing

def classify_failure(detail):
    """Classify failure reason - return icon only"""
    detail_lower = detail.lower()

    # Dependency related - 🔴
    if any(kw in detail_lower for kw in ['missing dependencies', 'dependency', 'could not resolve', 'failed to install']):
        return '🔴'
    # Package stage failures - ⚪
    elif 'failed in package' in detail_lower:
        return '⚪'
    # Build stage failures - ❌
    elif 'failed in build' in detail_lower or 'build failed' in detail_lower:
        return '❌'
    # Download failures - 🔴
    elif 'download' in detail_lower and 'failed' in detail_lower:
        return '🔴'
    # Version/cmp issues - 🟡
    elif 'greater than newver' in detail_lower or 'vercmp' in detail_lower:
        return '🟡'
    # Namcap
    elif 'namcap' in detail_lower:
        return '🔴'
    else:
        return '❓'

def print_report(stats):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    total = stats['total']
    packages = stats['packages']
    failed_pkgs = [p for p in packages if p[2] == 'FAILED']
    failed_count = len(failed_pkgs)
    success_count = stats['by_status'].get('PUBLISHED', 0)
    stale_count = stats['by_status'].get('STALE', 0)
    building_count = stats['by_status'].get('BUILDING', 0)

    # Compute block counts: how many other packages are blocked by each package
    # Count across ALL failures (not just this category)
    block_counts = Counter()
    for cat, pkgbase, status, detail, _ in packages:
        if status == 'FAILED' and detail:
            missing_deps = extract_missing_dependencies(detail)
            for dep in missing_deps:
                block_counts[dep] += 1

    print("="*70)
    print("📊 AUR Auto-Update Build Analysis (Detailed)")
    print(f"Generated: {now}")
    print("="*70)

    # Failed packages table
    if failed_pkgs:
        print(f"\n## ❌ Failed Packages ({failed_count})")
        # Count blocked packages (dependency issues)
        failure_types_temp = Counter()
        for _, _, _, detail, _ in failed_pkgs:
            if detail:
                ftype = classify_failure(detail)
                failure_types_temp[ftype] += 1
            else:
                failure_types_temp['❓'] += 1
        block_count = failure_types_temp.get('🔴', 0)
        if block_count > 0:
            print(f"🔴 Blocked by dependencies: {block_count} packages")
        print("| Package | Run ID | Blocked | Detail |")
        print("|---------|--------|---------|--------|")

        # Sort by package name
        for cat, pkgbase, status, detail, run_id in sorted(failed_pkgs, key=lambda x: x[1]):
            # Get blocked count: count how many other packages are missing this one
            pure_pkg = pkgbase.split('/', 1)[-1] if '/' in pkgbase else pkgbase
            blocked_num = block_counts.get(pure_pkg, 0)
            ftype = classify_failure(detail) if detail else '❓'
            detail_display = detail[:60] + ('...' if len(detail) > 60 else '')
            print(f"| {pkgbase} | {run_id} | {blocked_num} | {ftype} {detail_display} |")

    # Summary line - show status icons only, plus breakdown of failed types (without total failed count)
    print("\n" + "="*70)
    summary_parts = []
    if success_count > 0:
        summary_parts.append(f"📦{success_count}")
    if stale_count > 0:
        summary_parts.append(f"🟡{stale_count}")

    # Add detailed failure types breakdown (icons only, no text)
    if failed_pkgs:
        failure_types = Counter()
        for _, _, _, detail, _ in failed_pkgs:
            if detail:
                ftype = classify_failure(detail)
            else:
                ftype = '❓'
            failure_types[ftype] += 1
        # Append each icon count
        for ftype, count in failure_types.items():
            summary_parts.append(f"{ftype}{count}")

    if building_count > 0:
        summary_parts.append(f"🏗️{building_count}")

    summary = " ".join(summary_parts)
    print(f"Total: {total} packages ({summary})")

    # Per-category breakdown - same order and detail as total line
    for cat in sorted(stats['by_category'].keys()):
        c = stats['by_category'][cat]
        total_c = c['total']
        pub = c.get('PUBLISHED', 0)
        fail = c.get('FAILED', 0)
        stale = c.get('STALE', 0)
        building = c.get('BUILDING', 0)
        parts = [f"{cat}: {total_c} packages ("]
        if pub > 0:
            parts.append(f"📦{pub} ")
        if stale > 0:
            parts.append(f"🟡{stale} ")
        # Add failure type breakdown for this category (icons only)
        if fail > 0:
            cat_failures = [p for p in failed_pkgs if p[0] == cat]
            cat_failure_types = Counter()
            for _, _, _, detail, _ in cat_failures:
                if detail:
                    ftype = classify_failure(detail)
                else:
                    ftype = '❓'
                cat_failure_types[ftype] += 1
            for ftype, count in cat_failure_types.items():
                parts.append(f"{ftype}{count} ")
        if building > 0:
            parts.append(f"🏗️{building} ")
        parts.append(")")
        print("".join(parts))

    print("\n" + "="*70)
    print("*Note: Analysis based on current index.md state.*")

if __name__ == '__main__':
    stats = parse_index()
    print_report(stats)