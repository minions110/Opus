#!/usr/bin/env python3
"""Tavily Search API (Python 版，不依赖 bash/jq)。

用法:
    python search.py '{"query": "your search query", "max_results": 5}'
    或通过环境变量传 JSON:
        set SEARCH_INPUT={"query":"abc"}
        python search.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


API_URL = "https://api.tavily.com/search"


def _print_usage() -> None:
    print("Usage: python search.py '<json>'")
    print("")
    print("Required:")
    print("  query: string - Search query (keep under 400 chars)")
    print("")
    print("Optional:")
    print("  search_depth: 'ultra-fast', 'fast', 'basic' (default), 'advanced'")
    print("  topic: 'general' (default), 'news', 'finance'")
    print("  max_results: 1-20 (default: 5)")
    print("  chunks_per_source: 1-5 (default: 3, advanced/fast depth only)")
    print("  time_range: 'day', 'week', 'month', 'year'")
    print("  start_date: 'YYYY-MM-DD'")
    print("  end_date: 'YYYY-MM-DD'")
    print("  include_domains: ['domain1.com', 'domain2.com']")
    print("  exclude_domains: ['domain1.com', 'domain2.com']")
    print("  country: country name (general topic only)")
    print("  include_answer: true/false or 'basic'/'advanced'")
    print("  include_raw_content: true/false or 'markdown'/'text'")
    print("  include_images: true/false")
    print("  include_image_descriptions: true/false")
    print("  include_favicon: true/false")
    print("")
    print("Environment:")
    print("  TAVILY_API_KEY  (必需)")


def _load_payload() -> dict:
    raw = ""
    if len(sys.argv) >= 2:
        raw = sys.argv[1].strip()
    if not raw:
        raw = (os.environ.get("SEARCH_INPUT") or "").strip()
    if not raw:
        _print_usage()
        sys.exit(1)

    # 容忍 PowerShell 吃掉双引号后变成 {query:abc} 的形态
    if raw.startswith("{") and not raw.startswith('{"'):
        import re
        fixed = re.sub(r'([{,]\s*)([A-Za-z_][\w-]*)(\s*:)', r'\1"\2"\3', raw)
        fixed = re.sub(r'(:\s*)([^",}\[\]\d]+?)(\s*[,}])', r'\1"\2"\3', fixed)
        raw = fixed

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Error: Invalid JSON input - {exc}")
        print(f"Input was: {raw}")
        sys.exit(1)

    if not isinstance(payload, dict):
        print("Error: JSON input must be an object")
        sys.exit(1)

    if not payload.get("query"):
        print("Error: 'query' field is required")
        sys.exit(1)

    return payload


def main() -> int:
    api_key = (os.environ.get("TAVILY_API_KEY") or "").strip()
    if not api_key:
        print("Error: TAVILY_API_KEY environment variable not set")
        return 1

    payload = _load_payload()
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "x-client-source": "claude-code-skill",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"Error: HTTP {exc.code}")
        print(detail)
        return exc.code or 1
    except urllib.error.URLError as exc:
        print(f"Error: network - {exc.reason}")
        return 1
    except TimeoutError:
        print("Error: request timed out")
        return 1

    # 美化 JSON 输出
    try:
        data = json.loads(raw)
        print(json.dumps(data, ensure_ascii=False, indent=2))
    except json.JSONDecodeError:
        print(raw)
    return 0


if __name__ == "__main__":
    sys.exit(main())
