#!/usr/bin/env python3
"""
Generate builds.json from MySQL, upload to Cloudflare R2 via CF API.

Usage:
    python generate_status_json.py \
        --db-name cactus --db-user root --db-password secret \
        --cf-token YOUR_CLOUDFLARE_API_TOKEN \
        --cf-account-id YOUR_ACCOUNT_ID \
        --r2-bucket arch4edu
"""

import argparse
import json
import time
import logging
import hashlib

import pymysql
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

CF_API = 'https://api.cloudflare.com/client/v4'


def parse_args():
    p = argparse.ArgumentParser(description='Sync cactus build data to Cloudflare R2')

    p.add_argument('--db-host', default='127.0.0.1')
    p.add_argument('--db-port', type=int, default=3306)
    p.add_argument('--db-name', required=True)
    p.add_argument('--db-user', required=True)
    p.add_argument('--db-password', required=True)

    p.add_argument('--cf-token', required=True, help='Cloudflare API token')
    p.add_argument('--cf-account-id', required=True, help='Cloudflare Account ID')
    p.add_argument('--r2-bucket', default='arch4edu')

    return p.parse_args()


def generate_builds(args):
    aur_prefix = 'https://aur.archlinux.org/pkgbase/'
    workflow_prefix = 'https://github.com/arch4edu/cactus/actions/runs/'

    conn = pymysql.connect(
        host=args.db_host,
        port=args.db_port,
        user=args.db_user,
        password=args.db_password,
        database=args.db_name,
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT `key`, status, detail, workflow, timestamp FROM cactus_status')
            rows = cur.fetchall()
    finally:
        conn.close()

    packages = []
    for r in rows:
        parts = r['key'].split('/')
        category = '/'.join(parts[:-1]) if len(parts) > 1 else ''
        pkgbase = parts[-1] if parts else r['key']
        ts = int(r['timestamp'].timestamp()) if r['timestamp'] else 0
        packages.append({
            'key': r['key'],
            'category': category,
            'pkgbase': pkgbase,
            'status': r['status'],
            'detail': r['detail'],
            'workflow': r['workflow'],
            'workflow_url': f'{workflow_prefix}{r["workflow"]}' if r['workflow'] else '',
            'aur_url': f'{aur_prefix}{pkgbase}',
            'timestamp': ts,
        })

    return {
        'generated_at': int(time.time()),
        'total': len(packages),
        'packages': packages,
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
    log.info('=== sync_r2 start ===')

    log.info('Generating builds.json ...')
    builds = generate_builds(args)
    upload(args, 'status/builds.json', builds)

    log.info('=== done ===')


if __name__ == '__main__':
    main()
