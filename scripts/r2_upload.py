"""R2 upload helpers used by upload-r2.yml and backfill.yml.

Two subcommands:

  upload-version <version> <dist_dir>
    Uploads every file in <dist_dir> to versions/<version>/<filename> and
    writes versions/<version>/manifest.json. No global state mutation.
    Safe to run in parallel for different versions.

  rebuild-index
    Lists versions/*/manifest.json on the bucket, reads each, and writes a
    fresh versions.json to the bucket root. Idempotent; reflects whatever
    is currently in the bucket. Run once after a batch of uploads.

Reads the same env vars as the workflow steps:
  ENDPOINT, BUCKET, R2_KEY_ID, R2_APP_KEY
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError


def _client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["ENDPOINT"],
        aws_access_key_id=os.environ["R2_KEY_ID"],
        aws_secret_access_key=os.environ["R2_APP_KEY"],
        region_name="auto",
    )


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def upload_version(version: str, dist_dir: Path) -> None:
    bucket = os.environ["BUCKET"]
    s3 = _client()

    manifest = {
        "version": version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": {},
    }
    for p in sorted(dist_dir.iterdir()):
        if not p.is_file():
            continue
        manifest["files"][p.name] = {"size": p.stat().st_size, "sha256": _sha256(p)}

    for name in manifest["files"]:
        key = f"versions/{version}/{name}"
        print(f"  PUT {key}", flush=True)
        s3.upload_file(
            str(dist_dir / name), bucket, key,
            ExtraArgs={"CacheControl": "public, max-age=300"},
        )

    s3.put_object(
        Bucket=bucket,
        Key=f"versions/{version}/manifest.json",
        Body=json.dumps(manifest, indent=2).encode(),
        ContentType="application/json",
        CacheControl="public, max-age=300",
    )
    print(f"Uploaded {len(manifest['files'])} files for version {version}", flush=True)


def rebuild_index() -> None:
    bucket = os.environ["BUCKET"]
    s3 = _client()

    # List every versions/*/manifest.json
    paginator = s3.get_paginator("list_objects_v2")
    manifest_keys = []
    for page in paginator.paginate(Bucket=bucket, Prefix="versions/"):
        for obj in page.get("Contents", []) or []:
            key = obj["Key"]
            if key.endswith("/manifest.json"):
                manifest_keys.append(key)

    versions = []
    for key in manifest_keys:
        try:
            obj = s3.get_object(Bucket=bucket, Key=key)
            m = json.loads(obj["Body"].read())
        except (ClientError, json.JSONDecodeError) as e:
            print(f"  skip {key}: {e}", flush=True)
            continue
        versions.append({
            "version": m["version"],
            "published_at": m.get("generated_at"),
            "manifest": key,
            "file_count": len(m.get("files", {})),
        })

    versions.sort(key=lambda v: v["version"])
    index = {
        "versions": versions,
        "latest": versions[-1]["version"] if versions else None,
    }
    s3.put_object(
        Bucket=bucket,
        Key="versions.json",
        Body=json.dumps(index, indent=2).encode(),
        ContentType="application/json",
        CacheControl="public, max-age=60",
    )
    print(f"Rebuilt versions.json: {len(versions)} versions, latest={index['latest']}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    up = sub.add_parser("upload-version", help="Upload one version's artifacts")
    up.add_argument("version")
    up.add_argument("dist_dir")

    sub.add_parser("rebuild-index", help="Rebuild top-level versions.json")

    args = parser.parse_args()
    if args.cmd == "upload-version":
        upload_version(args.version, Path(args.dist_dir))
    elif args.cmd == "rebuild-index":
        rebuild_index()
    else:
        parser.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
