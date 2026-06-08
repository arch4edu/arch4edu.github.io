#!/usr/bin/env python3
"""
Generate mirrors.json from mirrorlist, upload to Cloudflare R2 via CF API.

Usage:
    python generate_mirrors_json.py \
        --mirrorlist /path/to/mirrorlist.arch4edu \
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


def parse_args():
    p = argparse.ArgumentParser(description='Generate mirrors.json and upload to R2')

    p.add_argument('-m', '--mirrorlist', required=True, help='Path to mirrorlist.arch4edu')
    p.add_argument('-t', '--cf-token', required=True, help='Cloudflare API token')
    p.add_argument('-a', '--cf-account-id', required=True, help='Cloudflare Account ID')
    p.add_argument('-b', '--r2-bucket', default='arch4edu')
    p.add_argument('-T', '--timeout', type=int, default=10, help='HTTP timeout per mirror (seconds)')

    return p.parse_args()


def parse_mirrorlist(path: str) -> list[dict]:
    mirrors = []
    country = 'Unknown'
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith('## ') and not line.startswith('###'):
                country = line[3:].strip()
            elif line.startswith('#Server = ') or line.startswith('Server = '):
                prefix = '#Server = ' if line.startswith('#Server = ') else 'Server = '
                url_template = line[len(prefix):]
                url = url_template.replace('/$arch', '').rstrip('/')
                mirrors.append({'country': country, 'url': url + '/'})
    return mirrors


def check_mirror(url: str, timeout: int = 10) -> dict:
    check_url = url.rstrip('/') + '/lastupdate'
    try:
        resp = requests.get(
            check_url,
            timeout=timeout,
            headers={'User-Agent': 'arch4edu-mirror-checker/1.0'},
        )
        if resp.status_code != 200:
            return {'status': 'error', 'detail': f'HTTP {resp.status_code}'}
        body = resp.text.strip()
        try:
            ts = int(body)
            return {'status': 'ok', 'timestamp': ts}
        except ValueError:
            return {'status': 'error', 'detail': f'Invalid timestamp: {body[:100]}'}
    except requests.exceptions.Timeout:
        return {'status': 'error', 'detail': 'Timeout'}
    except requests.exceptions.ConnectionError:
        return {'status': 'error', 'detail': 'ConnectionError'}
    except Exception as e:
        return {'status': 'error', 'detail': type(e).__name__}


def generate_mirrors(args):
    log.info(f'Parsing mirrorlist: {args.mirrorlist}')
    mirrors = parse_mirrorlist(args.mirrorlist)
    log.info(f'Found {len(mirrors)} mirrors')

    results = []
    for i, mirror in enumerate(mirrors, 1):
        url = mirror['url']
        log.info(f'  [{i}/{len(mirrors)}] {url}')
        status = check_mirror(url, timeout=args.timeout)
        results.append({
            'country': mirror['country'],
            'url': url,
            'status': status['status'],
            'timestamp': status.get('timestamp'),
            'detail': status.get('detail'),
        })

    return {
        'generated_at': int(time.time()),
        'total': len(results),
        'mirrors': results,
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
    log.info('=== mirrors_json start ===')

    mirrors = generate_mirrors(args)
    upload(args, 'status/mirrors.json', mirrors)

    log.info('=== done ===')


if __name__ == '__main__':
    main()
