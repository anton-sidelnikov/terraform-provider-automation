#!/usr/bin/env python3
"""Audit the reviewed documentation snapshot against public GitHub repositories."""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ORG = "opentelekomcloud-docs"
MARKER = "api-ref/source/index.rst"


def request(url: str, *, method: str = "GET") -> Request:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "otc-agent-catalog-audit/1"}
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {token}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    return Request(url, headers=headers, method=method)


def repositories() -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for page in range(1, 20):
        url = f"https://api.github.com/orgs/{ORG}/repos?type=public&per_page=100&page={page}"
        with urlopen(request(url), timeout=30) as response:  # nosec: fixed GitHub host
            values = json.load(response)
        if not values:
            break
        result.extend((item["name"], item["default_branch"]) for item in values if not item["archived"])
    return result


def has_api_ref(item: tuple[str, str]) -> str | None:
    name, branch = item
    url = f"https://raw.githubusercontent.com/{ORG}/{name}/{branch}/{MARKER}"
    try:
        with urlopen(request(url, method="HEAD"), timeout=20) as response:  # nosec: fixed GitHub host
            return name if response.status == 200 else None
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def main() -> int:
    catalog_path = Path("config/services.json")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    expected = set(catalog["eligible_docs_repositories"])
    mapped = {item["docs"] for item in catalog["mappings"]}
    with ThreadPoolExecutor(max_workers=8) as executor:
        actual = {name for name in executor.map(has_api_ref, repositories()) if name}
    report = {
        "schema_version": 1,
        "organization": ORG,
        "marker": MARKER,
        "actual_count": len(actual),
        "expected_count": len(expected),
        "added": sorted(actual - expected),
        "removed_or_unavailable": sorted(expected - actual),
        "unmapped_api_ref_repositories": sorted(actual - mapped),
        "status": "ok" if actual == expected else "drift",
    }
    output = Path("build/catalog-audit.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if actual == expected else 2


if __name__ == "__main__":
    sys.exit(main())
