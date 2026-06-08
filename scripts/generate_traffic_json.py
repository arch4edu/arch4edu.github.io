#!/usr/bin/env python3
"""
Generate traffic.json from Cloudflare Analytics, upload to R2 via CF API.

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
    p.add_argument('-n', '--days', type=int, default=7, help='Number of days to query (default: 7)')

    return p.parse_args()


def generate_traffic(args):
    from datetime import datetime, timedelta, timezone

    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime('%Y-%m-%d')

    query = """
    query TrafficByCountry($zoneTag: String!, $since: String!) {
      viewer {
        zones(filter: { zoneTag: $zoneTag }) {
          httpRequestsAdaptiveGroups(
            limit: 300
            filter: { date_geq: $since }
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
        'Authorization': f'Bearer {args.cf_token}',
        'Content-Type': 'application/json',
    }
    payload = {
        'query': query,
        'variables': {'zoneTag': args.cf_zone_id, 'since': since},
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
        log.error('No zone data returned')
        raise SystemExit(1)

    groups = zones[0].get('httpRequestsAdaptiveGroups', [])

    country_map = {}
    for group in groups:
        country = group['dimensions']['clientCountryName']
        count = group['count']
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

    # Check existing object to skip redundant upload
    head_url = f'{CF_API}/accounts/{args.cf_account_id}/r2/buckets/{args.r2_bucket}/objects/{key}'
    resp = requests.head(head_url, headers=headers)
    if resp.status_code == 200:
        remote_etag = resp.headers.get('etag', '').strip('"')
        if remote_etag == md5:
            log.info(f'  {key}: unchanged, skip')
            return

    # Upload
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

    log.info(f'Querying Cloudflare Analytics (last {args.days} days) ...')
    traffic = generate_traffic(args)
    upload(args, 'status/traffic.json', traffic)

    log.info('=== done ===')


if __name__ == '__main__':
    main()
