#!/usr/bin/env python3
"""Onside's keys, in SSM Parameter Store, for the free-tier deployment.

    python onside_secrets.py                       copy the keys in ../.env to /onside/*
    python onside_secrets.py --set BLUESKY_APP_PASSWORD
                                            rotate one: asks for the new value
                                            (typing hidden), saves it to ../.env
                                            and to /onside/, and the worker picks
                                            it up within fifteen minutes
    python onside_secrets.py --list                which keys are stored (names only)

Values are never printed, never put on a command line and never pass through
CloudFormation. Standard SecureString parameters under the AWS-managed key
cost nothing.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

import boto3

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
PATH = "/onside"
KEYS = (
    "FOOTBALL_DATA_API_KEY",
    "BLUESKY_HANDLE",
    "BLUESKY_APP_PASSWORD",
    "REDDIT_CLIENT_ID",
    "REDDIT_CLIENT_SECRET",
    "X_BEARER_TOKEN",
    "X_MAX_READS_PER_DAY",
    "MASTODON_INSTANCE",
)


def read_env(path: Path = ENV_FILE) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and not name.strip().startswith("#"):
            out[name.strip()] = value.strip().strip('"').strip("'")
    return out


def write_env(name: str, value: str, path: Path = ENV_FILE) -> None:
    """Replace NAME=... in place, or append it; every other line is kept."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    for i, line in enumerate(lines):
        if line.partition("=")[0].strip() == name:
            lines[i] = f"{name}={value}"
            break
    else:
        lines.append(f"{name}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def put(ssm: object, name: str, value: str) -> None:
    ssm.put_parameter(  # type: ignore[attr-defined]
        Name=f"{PATH}/{name}", Value=value, Type="SecureString", Overwrite=True, Tier="Standard"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", metavar="NAME", choices=KEYS, help="rotate one key")
    ap.add_argument("--list", action="store_true", help="list the stored names")
    args = ap.parse_args(argv)
    ssm = boto3.client("ssm")

    if args.list:
        pages = ssm.get_paginator("get_parameters_by_path").paginate(Path=PATH)
        names = sorted(p["Name"] for page in pages for p in page["Parameters"])
        print("\n".join(names) or f"nothing under {PATH}")
        return 0

    if args.set:
        value = getpass.getpass(f"New value for {args.set} (typing is hidden): ").strip()
        if not value:
            print("Nothing entered; nothing changed.", file=sys.stderr)
            return 1
        write_env(args.set, value)
        put(ssm, args.set, value)
        print(f"{args.set}: saved to .env and {PATH}/{args.set}. The AWS worker picks it up "
              "within 15 minutes; locally, run `docker compose up -d social fixtures`.")
        return 0

    env = read_env()
    stored = [k for k in KEYS if env.get(k)]
    for k in stored:
        put(ssm, k, env[k])
    print(f"Stored {len(stored)} keys under {PATH}/: {', '.join(stored) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
