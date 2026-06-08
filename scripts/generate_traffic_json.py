#!/usr/bin/env python3
"""
Generate traffic.json from Cloudflare Analytics, upload to R2 via CF API.

Uses a local cache to avoid re-querying historical days.
Each day is queried at most once; results are cached permanently.
Skips today (still in progress). Always uploads last 30 days total.

Usage:
    python generate_traffic_json.py \
        --cf-zone-id YOUR_ZONE_ID \
        --cf-token YOUR_CLOUDFLARE_API_TOKEN \
        --cf-account-id YOUR_ACCOUNT_ID \
        --r2-bucket arch4edu
"""

import argparse
import json
import time
import logging
import hashlib

import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

CF_API = 'https://api.cloudflare.com/client/v4'
CF_GRAPHQL = f'{CF_API}/graphql'


def parse_args():
    p = argparse.ArgumentParser(description='Generate traffic.json from Cloudflare Analytics')

    p.add_argument('-z', '--cf-zone-id', required=True, help='Cloudflare Zone ID')
    p.add_argument('-t', '--cf-token', required=True, help='Cloudflare API token (Analytics:Read)')
    p.add_argument('-a', '--cf-account-id', required=True, help='Cloudflare Account ID')
    p.add_argument('-b', '--r2-bucket', default='arch4edu')
    p.add_argument('-n', '--days', type=int, default=30, help='Number of days to include (default: 30)')
    p.add_argument('-c', '--cache', default='.traffic_cache.json', help='Local cache file path')

    return p.parse_args()


def query_day(zone_id: str, api_token: str, date_str: str) -> dict[str, int]:
    """Query one day of traffic by country. Returns {country: count}."""
    query = """
    query TrafficByCountry($zoneTag: String!, $since: String!, $until: String!) {
      viewer {
        zones(filter: { zoneTag: $zoneTag }) {
          httpRequestsAdaptiveGroups(
            limit: 300
            filter: { date_geq: $since, date_leq: $until }
          ) {
            count
            dimensions {
              clientCountryName
            }
          }
        }
      }
    }
    """

    headers = {
        'Authorization': f'Bearer {api_token}',
        'Content-Type': 'application/json',
    }
    payload = {
        'query': query,
        'variables': {'zoneTag': zone_id, 'since': date_str, 'until': date_str},
    }

    resp = requests.post(CF_GRAPHQL, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if data.get('errors'):
        for err in data['errors']:
            log.error(f"CF API error: {err.get('message', err)}")
        raise SystemExit(1)

    zones = data.get('data', {}).get('viewer', {}).get('zones', [])
    if not zones:
        return {}

    country_map = {}
    for group in zones[0].get('httpRequestsAdaptiveGroups', []):
        country = group['dimensions']['clientCountryName']
        count = group['count']
        country_map[country] = country_map.get(country, 0) + count

    return country_map


def generate_traffic(args):
    from datetime import datetime, timedelta, timezone
    from pathlib import Path

    # Load cache
    cache_path = Path(args.cache)
    cache = {}
    if cache_path.exists():
        with open(cache_path) as f:
            cache = json.load(f)
        log.info(f'Cache loaded: {len(cache)} days')

    # Determine date range: yesterday back N days (skip today)
    now = datetime.now(timezone.utc)
    target_dates = []
    for i in range(1, args.days + 1):
        day = now - timedelta(days=i)
        target_dates.append(day.strftime('%Y-%m-%d'))

    # Find missing dates
    missing = [d for d in target_dates if d not in cache]
    log.info(f'Target: {args.days} days, cached: {len(target_dates) - len(missing)}, to query: {len(missing)}')

    # Query missing days
    for date_str in missing:
        log.info(f'  querying {date_str} ...')
        cache[date_str] = query_day(args.cf_zone_id, args.cf_token, date_str)

    # Prune cache: only keep dates within our range
    target_set = set(target_dates)
    cache = {k: v for k, v in cache.items() if k in target_set}

    # Save cache
    with open(cache_path, 'w') as f:
        json.dump(cache, f, separators=(',', ':'))
    log.info(f'Cache saved: {len(cache)} days')

    # Aggregate across all cached days
    country_map = {}
    for day_data in cache.values():
        for country, count in day_data.items():
            country_map[country] = country_map.get(country, 0) + count

    countries = sorted(
        [{'country': k, 'requests': v} for k, v in country_map.items()],
        key=lambda x: x['requests'],
        reverse=True,
    )

    total_requests = sum(c['requests'] for c in countries)

    return {
        'generated_at': int(time.time()),
        'days': args.days,
        'total_requests': total_requests,
        'countries': countries,
    }


def upload(args, key: str, data: dict):
    """Upload JSON to R2 via Cloudflare API, skip if unchanged."""
    body = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    md5 = hashlib.md5(body).hexdigest()

    headers = {
        'Authorization': f'Bearer {args.cf_token}',
    }

    head_url = f'{CF_API}/accounts/{args.cf_account_id}/r2/buckets/{args.r2_bucket}/objects/{key}'
    resp = requests.head(head_url, headers=headers)
    if resp.status_code == 200:
        remote_etag = resp.headers.get('etag', '').strip('"')
        if remote_etag == md5:
            log.info(f'  {key}: unchanged, skip')
            return

    put_url = f'{CF_API}/accounts/{args.cf_account_id}/r2/buckets/{args.r2_bucket}/objects/{key}'
    resp = requests.put(
        put_url,
        headers={
            **headers,
            'Content-Type': 'application/json',
        },
        data=body,
    )
    if resp.status_code in (200, 201):
        log.info(f'  {key}: uploaded ({len(body)} bytes)')
    else:
        log.error(f'  {key}: upload failed ({resp.status_code}): {resp.text}')
        raise SystemExit(1)


def main():
    args = parse_args()
    log.info('=== traffic_json start ===')

    traffic = generate_traffic(args)
    upload(args, 'status/traffic.json', traffic)

    log.info('=== done ===')


if __name__ == '__main__':
    main()
