#!/usr/bin/env python3
"""Bocha Web Search API 调用脚本。

优先使用环境变量 BOCHA_API_KEY；
若没有，则在当前工作目录 / 脚本所在目录向上查找 data/Opus.json 并读取 api_keys.bocha.api_key。
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional


def _load_from_opus_json() -> Optional[str]:
    """从 Opus.json 中查找 bocha API key。"""
    candidates = [Path.cwd() / "data" / "Opus.json",
                  Path(__file__).resolve().parent.parent.parent.parent.parent / "data" / "Opus.json",
                  Path(__file__).resolve().parent.parent / "data" / "Opus.json"]
    for candidate in candidates:
        try:
            if candidate.is_file():
                data = json.loads(candidate.read_text(encoding="utf-8"))
                api_keys = data.get("api_keys", {}) or {}
                skills = api_keys.get("skills", {}) or {}
                bocha = skills.get("bocha") or {}
                key = bocha.get("api_key")
                if key:
                    return str(key)
        except (OSError, json.JSONDecodeError):
            continue
    return None


def _print_and_exit(obj: dict, code: int) -> None:
    print(json.dumps(obj, ensure_ascii=False))
    sys.exit(code)


def main() -> None:
    if len(sys.argv) < 2:
        _print_and_exit({"error": "Missing JSON argument. 用法: bocha-web-search.py '{\"query\":\"...\"}'"}, 1)

    try:
        input_json = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        _print_and_exit({"error": "Invalid JSON input"}, 1)

    if not isinstance(input_json, dict):
        _print_and_exit({"error": "Input JSON must be an object"}, 1)

    query = input_json.get("query")
    if not query:
        _print_and_exit({"error": "query field is required"}, 1)

    api_key = os.environ.get("BOCHA_API_KEY") or _load_from_opus_json()
    if not api_key:
        _print_and_exit({
            "error": "BOCHA_API_KEY environment variable / Opus.json#api_keys.skills.bocha.api_key not set"
        }, 1)

    body = {
        "query": query,
        "freshness": input_json.get("freshness", "noLimit"),
        "summary": bool(input_json.get("summary", True)),
        "count": int(input_json.get("count", 10)),
    }

    try:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            "https://api.bocha.cn/v1/web-search",
            data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        # 正常输出：直接打印 JSON 响应
        print(raw)
        sys.exit(0)
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = ""
        _print_and_exit({"error": f"HTTP {exc.code}", "details": detail[:2000]}, 1)
    except urllib.error.URLError as exc:
        _print_and_exit({"error": f"network: {exc.reason}"}, 1)
    except TimeoutError:
        _print_and_exit({"error": "request timed out"}, 1)
    except OSError as exc:
        _print_and_exit({"error": f"OS error: {exc}"}, 1)


if __name__ == "__main__":
    main()
