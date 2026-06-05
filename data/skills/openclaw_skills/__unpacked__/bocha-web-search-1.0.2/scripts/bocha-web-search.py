#!/usr/bin/env python3
"""Bocha Web Search API 调用脚本。

使用 Bocha Web Search API 进行联网搜索。

API 端点: POST https://api.bocha.cn/v1/web-search
认证方式: Bearer <BOCHA_API_KEY>
"""

import json
import os
import sys


def main():
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)
    
    try:
        input_json = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        print(json.dumps({"error": "Invalid JSON input"}))
        sys.exit(1)
    
    query = input_json.get("query")
    if not query:
        print(json.dumps({"error": "query field is required"}))
        sys.exit(1)
    
    # 获取 API Key
    api_key = os.environ.get("BOCHA_API_KEY")
    if not api_key:
        print(json.dumps({"error": "BOCHA_API_KEY environment variable not set"}))
        sys.exit(1)
    
    # 构建请求参数
    params = {
        "query": query,
        "freshness": input_json.get("freshness", "noLimit"),
        "summary": input_json.get("summary", True),
        "count": input_json.get("count", 10)
    }
    
    # 发送请求
    try:
        import urllib.request
        import urllib.error
        
        url = "https://api.bocha.cn/v1/web-search"
        data = json.dumps(params).encode("utf-8")
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Content-Length": str(len(data))
        }
        
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        
        with urllib.request.urlopen(req, timeout=30) as response:
            result = response.read().decode("utf-8")
            print(result)
            sys.exit(0)
    
    except urllib.error.HTTPError as e:
        error_data = e.read().decode("utf-8")
        print(json.dumps({"error": f"HTTP Error {e.code}", "details": error_data}))
        sys.exit(1)
    except urllib.error.URLError as e:
        print(json.dumps({"error": f"Network Error: {str(e)}"}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


def print_usage():
    usage = """Usage: bocha-web-search.py '<json>'

Required:
  query: string - Search query

Optional:
  freshness: 'noLimit'(default), 'oneDay', 'oneWeek', 'oneMonth', 'oneYear'
  summary: boolean - Whether to include web original content (default: true)
  count: integer - Number of results (default: 10, max: 50)

Example:
  bocha-web-search.py '{"query": "AI news", "freshness": "oneWeek", "count": 5}'
"""
    print(usage)


if __name__ == "__main__":
    main()