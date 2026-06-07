#!/usr/bin/env python3
"""DeepSeek Chat Completions 调用脚本（纯标准库，跨平台）。

用法:
    python deepseek.py '{"messages":[{"role":"user","content":"你好"}]}'
    python deepseek.py '{"system":"你是一个编辑","messages":[{"role":"user","content":"..."}]}'
    python deepseek.py '{"messages":[...],"model":"deepseek-chat","temperature":0.7}'

环境变量:
    DEEPSEEK_API_KEY   必需
    DEEPSEEK_BASE_URL  可选（默认 https://api.deepseek.com）
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional


API_BASE_DEFAULT = "https://api.deepseek.com"


def _print_usage_and_exit(code: int = 1) -> None:
    print("Usage: python deepseek.py '<json>'")
    print("JSON 顶层字段:")
    print("  messages     [{role, content}, ...]  必填")
    print("  system       string                 可选，追加为 system 消息")
    print("  model        string                 默认 deepseek-chat")
    print("  temperature  number                 默认 0.7")
    print("  max_tokens   number                 默认 2048")
    print("环境: DEEPSEEK_API_KEY (必填), DEEPSEEK_BASE_URL (可选)")
    sys.exit(code)


def _load_payload(arg: str) -> Dict[str, Any]:
    stripped = arg.strip()
    if not stripped:
        print(json.dumps({"error": "Empty JSON input"}, ensure_ascii=False))
        sys.exit(1)
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        print(json.dumps({"error": "Invalid JSON input"}, ensure_ascii=False))
        sys.exit(1)
    if not isinstance(payload, dict):
        print(json.dumps({"error": "JSON input must be an object"}, ensure_ascii=False))
        sys.exit(1)
    return payload


def _build_messages(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    messages = payload.get("messages") or []
    if not isinstance(messages, list) or not messages:
        # 兼容：直接用 content / prompt 字段
        prompt = payload.get("prompt") or payload.get("content") or payload.get("query") or ""
        if prompt:
            messages = [{"role": "user", "content": str(prompt)}]
        else:
            print(json.dumps({"error": "'messages' is required and must be a non-empty list"},
                              ensure_ascii=False))
            sys.exit(1)

    system_text = payload.get("system")
    if system_text:
        # 若 messages 里第一个已经是 role=system，则用其内容 + 合并；否则插开头
        if messages and isinstance(messages[0], dict) and messages[0].get("role") == "system":
            messages[0]["content"] = str(system_text) + "\n\n" + str(messages[0].get("content", ""))
        else:
            messages = [{"role": "system", "content": str(system_text)}] + list(messages)

    validated: List[Dict[str, str]] = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "user")
        content = str(m.get("content") or "")
        if content:
            validated.append({"role": role, "content": content})
    if not validated:
        print(json.dumps({"error": "no valid messages (all content empty)"}, ensure_ascii=False))
        sys.exit(1)
    return validated


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if not argv or argv[0] in ("-h", "--help"):
        _print_usage_and_exit(0 if (argv and argv[0] in ("-h", "--help")) else 1)

    api_key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not api_key:
        print(json.dumps({"error": "DEEPSEEK_API_KEY environment variable not set"},
                          ensure_ascii=False))
        sys.exit(1)

    base_url = (os.environ.get("DEEPSEEK_BASE_URL") or API_BASE_DEFAULT).rstrip("/")

    payload = _load_payload(argv[0])
    messages = _build_messages(payload)

    body_obj: Dict[str, Any] = {
        "model": str(payload.get("model") or "deepseek-chat"),
        "messages": messages,
        "temperature": float(payload.get("temperature") or 0.7),
        "max_tokens": int(payload.get("max_tokens") or 2048),
    }

    body = json.dumps(body_obj, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        base_url + "/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(json.dumps(
            {"error": f"HTTP {exc.code}", "details": detail[:2000]},
            ensure_ascii=False,
        ))
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(json.dumps({"error": f"network: {exc.reason}"}, ensure_ascii=False))
        sys.exit(1)
    except TimeoutError:
        print(json.dumps({"error": "request timed out"}, ensure_ascii=False))
        sys.exit(1)
    except OSError as exc:
        print(json.dumps({"error": f"OS error: {exc}"}, ensure_ascii=False))
        sys.exit(1)

    # 尝试解析并只打印 assistant 消息
    try:
        data = json.loads(raw)
        choices = data.get("choices") or []
        if choices:
            first = choices[0]
            message = first.get("message") or {}
            content = message.get("content")
            if content is not None:
                # 同时把完整响应打印到 stderr（便于调试）
                sys.stderr.write(json.dumps({"usage": data.get("usage"),
                                              "model": data.get("model")},
                                            ensure_ascii=False) + "\n")
                print(content)
                return 0
        # 没有解析到 choices/content：把原始 JSON 原样输出
        print(raw)
        return 0
    except json.JSONDecodeError:
        # 服务端返回非 JSON
        print(raw)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
