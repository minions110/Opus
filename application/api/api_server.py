"""application/api/api_server.py

智能体 HTTP API 服务。使用 Python 标准库，无需任何额外依赖。

启动方式:
    python application/api/api_server.py              # 默认 http://127.0.0.1:8765
    python application/api/api_server.py --port 9000  # 自定义端口
    python application/api/api_server.py --host 0.0.0.0

提供的 API:
    GET  /health               健康检查
    GET  /api/skills           列出所有技能 (?source=xxx 可过滤)
    GET  /api/skills/{name}    技能详情
    POST /api/ask              智能问答 body: {"query": "...", "top_k": 5}
    POST /api/run              运行技能脚本 body: {"skill": "...", "args": "..."}
    POST /api/ref              读取 references 文档 body: {"skill": "...", "file": "..."}
    POST /api/reload           重新加载技能
    POST /api/install          解压 zip + 重新加载 (详细报告)
    GET  /api/workflows        列出所有工作流
    GET  /api/workflows/{name} 某工作流定义
    POST /api/workflows/run    运行工作流 body: {"name": "...", "inputs": {...}}
    POST /api/workflows/reload 重新扫描工作流目录
    GET  /                     返回 web/index.html
    GET  /static/*             静态文件服务 (从 application/web/)

此外，服务端会维护一个简单的对话历史（基于 client session），
便于 web 前端实现连续对话。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

# ---------------------------------------------------------------------------
# 路径设置: 把项目根目录加入 sys.path，使 src.agent 包可导入
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 延迟导入 —— 只在这里真正加载 Agent，以便 hot-reload 时可重建
from src.agent.agent import Agent            # noqa: E402
from src.agent.executor import run_skill_script  # noqa: E402


# ---------------------------------------------------------------------------
# 全局 Agent 单例（带锁）
# ---------------------------------------------------------------------------

_agent_lock = threading.RLock()
_agent: Optional[Agent] = None


def get_agent() -> Agent:
    """首次调用会阻塞并初始化 Agent，之后始终返回同一实例。"""
    global _agent
    with _agent_lock:
        if _agent is None:
            cfg_path = PROJECT_ROOT / "config.yaml"
            logging.info("正在加载 Agent (config=%s)", cfg_path)
            _agent = Agent(str(cfg_path))
    return _agent


def reload_agent() -> dict:
    """重新创建 Agent（清空 history 与 skills 索引）。"""
    global _agent
    with _agent_lock:
        cfg_path = PROJECT_ROOT / "config.yaml"
        logging.info("重新加载 Agent")
        _agent = Agent(str(cfg_path))
        return _agent.reload_skills()


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _skill_to_dict(skill) -> Dict[str, Any]:
    """把 Skill 数据模型转换为 JSON-serializable dict。"""
    return {
        "name": skill.name,
        "source": skill.source,
        "source_root": getattr(skill, "source_root", skill.source),
        "description": skill.description,
        "body": getattr(skill, "body", "") or "",
        "scripts": list(getattr(skill, "scripts", []) or []),
        "references": list(getattr(skill, "references", []) or []),
        "assets": list(getattr(skill, "assets", []) or []),
        "path": str(getattr(skill, "path", "")),
    }


def _read_json_body(handler: BaseHTTPRequestHandler) -> Optional[dict]:
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0:
        return {}
    try:
        raw = handler.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        handler.send_json({"error": f"JSON 解析失败: {exc}"}, status=400)
        return None


# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------

class AgentHandler(BaseHTTPRequestHandler):
    """处理所有 HTTP 请求。"""

    server_version = "AgentServer/1.0"

    # 静音不需要的默认日志（可选: 通过 --verbose 开启）
    quiet_mode = False

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        if self.quiet_mode:
            return
        logging.info("HTTP: %s - %s", self.address_string(), format % args)

    # -------------------------------------------------------------
    # 辅助: 发送 JSON 响应
    # -------------------------------------------------------------
    def send_json(self, data: Any, status: int = 200, extra_headers: Optional[dict] = None) -> None:
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Cache-Control", "no-store")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    # -------------------------------------------------------------
    # 辅助: 发送静态文件
    # -------------------------------------------------------------
    def send_static(self, rel_path: str) -> None:
        web_root = PROJECT_ROOT / "application" / "web"
        safe_path = (web_root / rel_path).resolve()
        try:
            safe_path.relative_to(web_root)  # 防止 .. 路径穿越
        except ValueError:
            self.send_json({"error": "invalid path"}, status=403)
            return
        if not safe_path.is_file():
            self.send_json({"error": "not found"}, status=404)
            return
        ext = safe_path.suffix.lower()
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".ico": "image/x-icon",
        }.get(ext, "application/octet-stream")
        data = safe_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    # -------------------------------------------------------------
    # HTTP 方法
    # -------------------------------------------------------------
    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_json({"ok": True})

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)

        if path in ("/", ""):
            self.send_static("index.html")
            return

        if path.startswith("/static/"):
            self.send_static(path[len("/static/"):])
            return

        if path == "/health":
            ag = get_agent()
            self.send_json({
                "status": "ok",
                "total_skills": len(ag.list_skills()),
                "sources": ag.skills_by_source(),
            })
            return

        if path == "/api/skills":
            ag = get_agent()
            source_filter = (qs.get("source", [""])[0] or "").lower()
            skills = ag.list_skills(source=source_filter) if source_filter else ag.list_skills()
            self.send_json({
                "count": len(skills),
                "source": source_filter or None,
                "skills": [
                    {
                        "name": s.name,
                        "source": s.source,
                        "source_root": getattr(s, "source_root", s.source),
                        "description": s.description,
                        "has_scripts": bool(s.scripts),
                        "has_references": bool(s.references),
                    }
                    for s in skills
                ],
            })
            return

        if path.startswith("/api/skills/"):
            name = unquote(path[len("/api/skills/"):])
            ag = get_agent()
            s = ag.find_skill(name)
            if s is None:
                self.send_json({"error": f"未找到技能: {name}"}, status=404)
                return
            self.send_json(_skill_to_dict(s))
            return

        if path == "/api/workflows":
            ag = get_agent()
            workflows = ag.list_workflows() or []
            self.send_json({
                "count": len(workflows),
                "workflows": workflows,
            })
            return

        if path.startswith("/api/workflows/"):
            name = unquote(path[len("/api/workflows/"):])
            ag = get_agent()
            wf = ag.get_workflow(name)
            if wf is None:
                self.send_json({"error": f"未找到工作流: {name}"}, status=404)
                return
            self.send_json(wf)
            return

        self.send_json({"error": f"未知路由: {path}"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        body = _read_json_body(self)
        if body is None:
            return

        if path == "/api/ask":
            query = (body.get("query") or "").strip()
            if not query:
                self.send_json({"error": "query 不能为空"}, status=400)
                return
            top_k = int(body.get("top_k", 5))
            ag = get_agent()
            resp = ag.ask(query, top_k=top_k)
            self.send_json({
                "reply": resp.reply,
                "matched_skills": [
                    {
                        **_skill_to_dict(s),
                        "score": float(score),
                    }
                    for s, score in resp.matched_skills
                ],
                "history_count": len(ag.history),
            })
            return

        if path == "/api/run":
            skill_name = (body.get("skill") or "").strip()
            args_str = body.get("args") or ""
            if not skill_name:
                self.send_json({"error": "skill 不能为空"}, status=400)
                return
            ag = get_agent()
            s = ag.find_skill(skill_name)
            if s is None:
                self.send_json({"error": f"未找到技能: {skill_name}"}, status=404)
                return
            if not s.scripts:
                self.send_json({
                    "skill": s.name,
                    "error": "该技能没有可执行脚本",
                    "available_scripts": [],
                }, status=400)
                return
            result = run_skill_script(s, args=args_str.split() if args_str else None)
            self.send_json({
                "skill": s.name,
                "script": (result.action or ""),
                "returncode": result.returncode,
                "stdout": result.stdout or "",
                "stderr": result.stderr or "",
                "ok": result.returncode == 0,
            })
            return

        if path == "/api/ref":
            skill_name = (body.get("skill") or "").strip()
            filename = (body.get("file") or "").strip()
            if not skill_name or not filename:
                self.send_json({"error": "skill 与 file 都需要"}, status=400)
                return
            ag = get_agent()
            s = ag.find_skill(skill_name)
            if s is None:
                self.send_json({"error": f"未找到技能: {skill_name}"}, status=404)
                return
            # 直接读取（防止路径穿越）
            if "/" in filename or "\\" in filename or ".." in filename:
                self.send_json({"error": "不合法的文件名"}, status=400)
                return
            ref_path = s.path / "references" / filename
            if not ref_path.is_file():
                self.send_json({
                    "error": "文件不存在",
                    "available": list(s.references),
                }, status=404)
                return
            content = ref_path.read_text(encoding="utf-8", errors="replace")
            self.send_json({
                "skill": s.name,
                "file": filename,
                "content": content,
            })
            return

        if path == "/api/reload":
            info = reload_agent()
            self.send_json({"ok": True, "info": info})
            return

        if path == "/api/install":
            info = reload_agent()
            # 额外构造一份 "按源" 的报告
            ag = get_agent()
            by_source = {}
            for src, items in ag.skills_by_source().items():
                by_source[src] = {
                    "count": len(items),
                    "skills": [
                        {
                            "name": s.name,
                            "description": s.description,
                            "scripts": list(s.scripts),
                            "references": list(s.references),
                        }
                        for s in items[:50]
                    ],
                }
            self.send_json({
                "ok": True,
                "total": info.get("total"),
                "by_source": by_source,
                "zip_info": info.get("zip_by_source", {}),
            })
            return

        if path == "/api/workflows/reload":
            ag = get_agent()
            info = ag.reload_workflows()
            self.send_json({"ok": True, "info": info})
            return

        if path == "/api/workflows/run":
            name = (body.get("name") or "").strip()
            if not name:
                self.send_json({"error": "name 不能为空"}, status=400)
                return
            inputs = body.get("inputs") or {}
            if not isinstance(inputs, dict):
                self.send_json({"error": "inputs 必须是对象"}, status=400)
                return
            ag = get_agent()
            r = ag.run_workflow(name, inputs=inputs)
            self.send_json({
                "name": r.name,
                "ok": r.ok,
                "error": r.error,
                "steps": [
                    {
                        "id": s.step_id,
                        "action": s.action,
                        "ok": s.ok,
                        "error": s.error,
                        "output": s.output,
                    }
                    for s in r.steps
                ],
            })
            return

        self.send_json({"error": f"未知路由: {path}"}, status=404)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Agent HTTP API Server")
    parser.add_argument("--host", default="127.0.0.1",
                        help="监听地址（默认 127.0.0.1，局域网用 0.0.0.0）")
    parser.add_argument("--port", type=int, default=8765,
                        help="监听端口（默认 8765）")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="显示 HTTP 访问日志")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    AgentHandler.quiet_mode = not args.verbose

    # 预热: 启动时即加载一次 Agent，让首次请求不阻塞
    try:
        ag = get_agent()
        logging.info("已加载 %d 个技能", len(ag.list_skills()))
    except Exception as exc:
        logging.error("Agent 初始化失败: %s", exc)
        return 2

    server = ThreadingHTTPServer((args.host, args.port), AgentHandler)
    url = f"http://{args.host}:{args.port}"
    print("=" * 60)
    print(f" Agent API Server 已启动")
    print(f"  API:       {url}/api/*")
    print(f"  网页端:    {url}/")
    print(f"  健康检查:  {url}/health")
    print("=" * 60)
    print("  按 Ctrl+C 退出")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在退出...")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
