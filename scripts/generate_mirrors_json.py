#!/usr/bin/env python3
"""Generate mirrors.json and upload to Cloudflare R2.

Usage:
    python generate_mirrors_json.py \
        --mirrorlist /path/to/mirrorlist.arch4edu \
        --r2-account-id <account-id> \
        --r2-access-key-id <access-key> \
        --r2-secret-access-key <secret-key> \
        --r2-bucket <bucket-name>

All R2 credentials can also be provided via environment variables:
    R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone


def parse_mirrorlist(path: str) -> list[dict]:
    """Parse mirrorlist.arch4edu format into list of {country, url}."""
    mirrors = []
    country = "Unknown"
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("## ") and not line.startswith("###"):
                country = line[3:].strip()
            elif line.startswith("#Server = ") or line.startswith("Server = "):
                prefix = "#Server = " if line.startswith("#Server = ") else "Server = "
                url_template = line[len(prefix):]
                # Remove /$arch suffix to get base URL
                url = url_template.replace("/$arch", "").rstrip("/")
                mirrors.append({"country": country, "url": url + "/"})
    return mirrors


def check_mirror(url: str, timeout: int = 10) -> dict:
    """Check a mirror's /lastupdate endpoint and return status dict."""
    check_url = url.rstrip("/") + "/lastupdate"
    try:
        req = urllib.request.Request(
            check_url,
            method="GET",
            headers={"User-Agent": "arch4edu-mirror-checker/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return {"status": "error", "detail": f"HTTP {resp.status}"}
            body = resp.read().decode("utf-8").strip()
            try:
                ts = int(body)
                last_update = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                return {"status": "ok", "timestamp": ts, "last_update": last_update}
            except ValueError:
                return {"status": "error", "detail": f"Invalid timestamp: {body[:100]}"}
    except urllib.error.HTTPError as e:
        return {"status": "error", "detail": f"HTTP {e.code}"}
    except urllib.error.URLError as e:
        reason = str(e.reason)
        return {"status": "error", "detail": reason}
    except TimeoutError:
        return {"status": "error", "detail": "Timeout"}
    except Exception as e:
        return {"status": "error", "detail": type(e).__name__}


def upload_to_r2(data: dict, args: argparse.Namespace):
    """Upload JSON data to Cloudflare R2."""
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        print("Error: boto3 is required. Install with: pip install boto3", file=sys.stderr)
        sys.exit(1)

    account_id = args.r2_account_id or os.environ.get("R2_ACCOUNT_ID", "")
    access_key = args.r2_access_key_id or os.environ.get("R2_ACCESS_KEY_ID", "")
    secret_key = args.r2_secret_access_key or os.environ.get("R2_SECRET_ACCESS_KEY", "")
    bucket = args.r2_bucket or os.environ.get("R2_BUCKET", "")

    if not all([account_id, access_key, secret_key, bucket]):
        print("Error: R2 credentials are required. Pass via --args or environment variables.", file=sys.stderr)
        sys.exit(1)

    s3_endpoint = f"https://{account_id}.r2.cloudflarestorage.com"

    session = boto3.Session(
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
    )
    s3 = session.client("s3", endpoint_url=s3_endpoint, config=Config(signature_version="s3v4"))

    json_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")

    s3.put_object(
        Bucket=bucket,
        Key="mirrors.json",
        Body=json_bytes,
        ContentType="application/json",
        CacheControl="max-age=300",
    )
    print(f"Uploaded mirrors.json to R2 bucket: {bucket}")


def main():
    parser = argparse.ArgumentParser(description="Generate mirrors.json and upload to Cloudflare R2")
    parser.add_argument("--mirrorlist", required=True, help="Path to mirrorlist.arch4edu file")
    parser.add_argument("--r2-account-id", default="", help="Cloudflare R2 account ID")
    parser.add_argument("--r2-access-key-id", default="", help="Cloudflare R2 access key ID")
    parser.add_argument("--r2-secret-access-key", default="", help="Cloudflare R2 secret access key")
    parser.add_argument("--r2-bucket", default="", help="Cloudflare R2 bucket name")
    parser.add_argument("--timeout", type=int, default=10, help="HTTP request timeout per mirror (seconds)")
    parser.add_argument("--no-upload", action="store_true", help="Generate JSON only, skip R2 upload")
    args = parser.parse_args()

    print(f"Parsing mirrorlist: {args.mirrorlist}")
    mirrors = parse_mirrorlist(args.mirrorlist)
    print(f"Found {len(mirrors)} mirrors")

    results = []
    for i, mirror in enumerate(mirrors, 1):
        url = mirror["url"]
        print(f"[{i}/{len(mirrors)}] Checking {url}...", end=" ", flush=True)
        status = check_mirror(url, timeout=args.timeout)
        print(status["status"])

        results.append({
            "country": mirror["country"],
            "url": url,
            "status": status["status"],
            "timestamp": status.get("timestamp"),
            "last_update": status.get("last_update"),
            "detail": status.get("detail"),
        })

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(results),
        "mirrors": results,
    }

    # Print to stdout
    json_str = json.dumps(output, ensure_ascii=False, indent=2)
    print("\n--- mirrors.json ---")
    print(json_str)

    if not args.no_upload:
        print("\nUploading to R2...")
        upload_to_r2(output, args)
    else:
        print("\nSkipped upload (--no-upload)")


if __name__ == "__main__":
    main()
