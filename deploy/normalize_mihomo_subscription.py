#!/usr/bin/env python3
"""Convert a full Clash configuration into a Mihomo proxy-provider file."""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

import yaml


def normalize(source: Path, destination: Path) -> int:
    with source.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle)

    if not isinstance(document, dict):
        raise ValueError("subscription must contain a YAML mapping")

    proxies = document.get("proxies")
    if not isinstance(proxies, list) or not proxies:
        raise ValueError("subscription does not contain any proxies")

    valid_proxies = [
        proxy
        for proxy in proxies
        if isinstance(proxy, dict) and proxy.get("name") and proxy.get("type")
    ]
    if not valid_proxies:
        raise ValueError("subscription contains no valid proxy definitions")

    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            yaml.safe_dump(
                {"proxies": valid_proxies},
                handle,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, destination)
    except Exception:
        os.unlink(temporary_name)
        raise

    return len(valid_proxies)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    arguments = parser.parse_args()

    count = normalize(arguments.source, arguments.destination)
    print(f"Normalized {count} proxy nodes.")


if __name__ == "__main__":
    main()
