"""OPC 智能体 - 开发验证入口（万能接口）。

本文件用于快速开发/调试/验证 OPC 智能体的核心能力。
部署生产环境时应使用 `application/` 目录下的正式入口。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

# 项目根目录 + sys.path 调整
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _print_result(result) -> None:
    """统一打印 ExecResult。"""
    print(f"\n[执行结果]")
    print(f"  动作: {result.action}")
    print(f"  返回码: {result.returncode}")
    if result.stdout:
        print(f"  stdout:\n{result.stdout}")
    if result.stderr:
        print(f"  stderr:\n{result.stderr}")


# ---------------------------------------------------------------------------
# 子命令实现
# ---------------------------------------------------------------------------

def run_interactive() -> int:
    """启动交互式对话模式。"""
    from src.ui.cli import main as cli_main
    return cli_main(["--interactive"])


def run_query(query: str, top_k: int = 5) -> int:
    """快速测试意图匹配。"""
    from src.skill_scripts.skill import match_skills

    config_path = str(PROJECT_ROOT / "config.yaml")
    results = match_skills(config_path, query, top_k=top_k)

    if not results:
        print("没有匹配到相关技能。")
        return 0

    print(f"匹配到 {len(results)} 个相关技能:\n")
    for i, item in enumerate(results, 1):
        skill = item.get("skill", {})
        relevance = item.get("relevance", 0.0)
        print(f" {i}. [{skill.get('source')}] {skill.get('name')}  "
              f"(相关度 {relevance:.2f})")
        if skill.get("description"):
            desc = skill["description"]
            print(f"    {desc[:160]}")
        if skill.get("path"):
            print(f"    路径: {skill.get('path')}")
        print()
    return 0


def run_list(source: Optional[str] = None) -> int:
    """列出技能。"""
    from src.skill_scripts.skill import create_skill_manager

    config_path = str(PROJECT_ROOT / "config.yaml")
    mgr = create_skill_manager(config_path)
    skills = mgr.list_skills(source)

    if not skills:
        print("没有发现任何技能。")
        return 0

    print(f"共 {len(skills)} 个技能:\n")
    for skill in skills:
        print(f"  - [{skill.get('source')}] {skill.get('name')}")
        desc = skill.get("short_description") or skill.get("description") or ""
        if desc:
            print(f"      {desc[:160]}")
        scripts = skill.get("scripts") or []
        if scripts:
            print(f"      脚本: {', '.join(scripts)}")
    return 0


def run_skill_cmd(skill_name: str, script_name: Optional[str] = None,
                  args: Optional[List[str]] = None) -> int:
    """通过 SkillManager 运行某个技能脚本。"""
    from src.skill_scripts.skill import create_skill_manager

    config_path = str(PROJECT_ROOT / "config.yaml")
    mgr = create_skill_manager(config_path)
    skill = mgr.registry.get(skill_name)

    if not skill:
        print(f"[错误] 找不到技能: {skill_name}")
        print(f"可用技能: {[s.name for s in mgr.registry.list()]}")
        return 1

    print(f"执行技能: {skill.name}")
    print(f"技能路径: {skill.path}")
    if script_name:
        print(f"脚本: {script_name}")
    else:
        print(f"脚本: (自动挑选 / 默认)")
    if args:
        print(f"参数: {args}")
    print("-" * 60)

    result = mgr.execute_skill(skill_name, script_name=script_name, args=args)
    _print_result(result)
    return 0 if result.returncode == 0 else 1


def run_workflow(name: str, inputs_json: Optional[str] = None,
                 query: Optional[str] = None) -> int:
    """执行工作流。"""
    from src.workflow_scripts.workflow import (
        discover_workflows, WorkflowExecutor,
    )
    from src.agent.agent import Agent

    import yaml as _yaml

    # 读取配置
    config_path = PROJECT_ROOT / "config.yaml"
    try:
        data = _yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, _yaml.YAMLError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    workflow_roots = data.get("workflow_roots") or []

    # 解析 roots
    roots: List[dict] = []
    for r in workflow_roots:
        if not isinstance(r, dict):
            continue
        raw_path = str(r.get("path") or "").strip()
        if not raw_path:
            continue
        p = Path(raw_path)
        if not p.is_absolute():
            p = (PROJECT_ROOT / p).resolve()
        if p.is_dir():
            roots.append({"name": str(r.get("name") or ""), "path": p})

    workflows = discover_workflows(roots)

    if name not in workflows:
        print(f"[错误] 找不到工作流: {name}")
        print(f"可用工作流: {list(workflows.keys())}")
        return 1

    # 构建 inputs
    inputs: dict = {}
    if query:
        inputs["query"] = query
        print(f"[简化模式] 使用 query: {query}")

    if inputs_json:
        s = inputs_json.strip()
        try:
            extra = json.loads(s)
        except json.JSONDecodeError:
            # 尝试修复 PowerShell 常见的 {key:value} 格式
            import re
            fixed = re.sub(r'([{,]\s*)(\w+)(\s*:)', r'\1"\2"\3', s)
            fixed = re.sub(r'(:\s*)([^",}\[\]\d]+?)(\s*[,}])', r'\1"\2"\3', fixed)
            try:
                extra = json.loads(fixed)
            except json.JSONDecodeError:
                print(f"[错误] inputs 不是合法 JSON: {s}")
                return 1
        if isinstance(extra, dict):
            inputs.update(extra)

    # Agent + 执行器
    agent = Agent(str(config_path))
    executor = WorkflowExecutor(agent, workflows)

    print(f"执行工作流: {name}")
    print(f"输入参数: {inputs}")
    print("-" * 60)

    result = executor.run(name, inputs=inputs)

    print(f"\n[工作流] {result.name}  "
          f"{'成功' if getattr(result, 'ok', True) else '失败'}")

    # 打印步骤
    for step in getattr(result, "steps", []) or []:
        status = "OK" if getattr(step, "ok", True) else "FAIL"
        print(f"  - [{status}] {getattr(step, 'step_id', '?')} "
              f"({getattr(step, 'action', '')})")
        err = getattr(step, "error", None)
        if err:
            print(f"      错误: {err}")
        out = getattr(step, "output", None)
        if out is not None:
            out_text = str(out)
            if len(out_text) > 300:
                out_text = out_text[:300] + "..."
            print(f"      输出: {out_text}")

    if getattr(result, "error", None):
        print(f"\n最终错误: {result.error}")

    return 0 if getattr(result, "ok", True) else 1


def list_workflows() -> int:
    """列出所有工作流。"""
    from src.workflow_scripts.workflow import discover_workflows
    import yaml as _yaml

    config_path = PROJECT_ROOT / "config.yaml"
    try:
        data = _yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, _yaml.YAMLError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    raw_roots = data.get("workflow_roots") or []

    roots: List[dict] = []
    for r in raw_roots:
        if not isinstance(r, dict):
            continue
        raw_path = str(r.get("path") or "").strip()
        if not raw_path:
            continue
        p = Path(raw_path)
        if not p.is_absolute():
            p = (PROJECT_ROOT / p).resolve()
        if p.is_dir():
            roots.append({"name": str(r.get("name") or ""), "path": p})

    workflows = discover_workflows(roots)

    if not workflows:
        print("没有发现任何工作流。")
        print("请在 data/workflows/<name>/workflow.yaml 下定义工作流。")
        return 0

    print(f"共 {len(workflows)} 个工作流:\n")
    for name, wf in workflows.items():
        step_count = len(getattr(wf, "steps", []) or [])
        desc = (getattr(wf, "description", "") or "").strip().replace("\n", " ")
        print(f"  - {name}  ({step_count} 步)")
        if desc:
            print(f"      {desc[:160]}")
    return 0


def run_api_server(host: str = "127.0.0.1", port: int = 8765,
                   verbose: bool = False) -> int:
    """启动 HTTP API 服务（转发到 application/api/api_server.py）。"""
    api_path = PROJECT_ROOT / "application" / "api" / "api_server.py"
    cmd = [sys.executable, str(api_path), "--host", host, "--port", str(port)]
    if verbose:
        cmd.append("--verbose")

    print(f"启动 API 服务: http://{host}:{port}")
    print("按 Ctrl+C 停止服务")
    print()

    try:
        subprocess.run(cmd, check=False)
        return 0
    except KeyboardInterrupt:
        print("\n服务已停止")
        return 0


def run_full_cli(extra: Optional[List[str]] = None) -> int:
    """调用部署用的完整 CLI。"""
    cli_path = PROJECT_ROOT / "application" / "cli" / "main.py"
    cmd = [sys.executable, str(cli_path)] + (extra or [])
    try:
        subprocess.run(cmd, check=False)
        return 0
    except KeyboardInterrupt:
        print()
        return 0


def show_info() -> int:
    """显示项目信息。"""
    print("=" * 60)
    print(" OPC 智能体 - 开发验证工具")
    print("=" * 60)
    print()
    print("目录结构:")
    print(f"  项目根: {PROJECT_ROOT}")
    print("  main.py              # 本文件（开发入口）")
    print("  application/cli/main.py     # 部署 CLI")
    print("  application/api/api_server.py # 部署 API")
    print("  src/agent/           # 智能体核心")
    print("  src/skill_scripts/   # 技能加载与匹配")
    print("  src/workflow_scripts/ # 工作流引擎")
    print("  data/skills/         # 技能包（支持 .zip）")
    print("  data/workflows/      # 工作流定义")
    print()
    print("常用命令:")
    print("  python main.py --list                   # 列出技能")
    print("  python main.py -q \"搜索 web 应用\"          # 意图匹配")
    print("  python main.py -e search -a arg1        # 执行技能")
    print("  python main.py --workflows              # 列出工作流")
    print("  python main.py --workflow demo          # 运行 demo 工作流")
    print("  python main.py --api --host 0.0.0.0     # 启动 API")
    print("=" * 60)
    return 0


# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="opc-agent-dev",
        description="OPC 智能体 - 开发验证万能接口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n"
               "  python main.py -q \"构建 web 应用\"\n"
               "  python main.py --list\n"
               "  python main.py -e search -a arg1\n"
               "  python main.py --workflow demo\n"
               "  python main.py --api --host 0.0.0.0\n",
    )

    quick = parser.add_argument_group("快速操作")
    quick.add_argument("-q", "--query", metavar="TEXT",
                       help="快速测试意图匹配")
    quick.add_argument("-l", "--list", nargs="?", const="", metavar="SOURCE",
                       help="列出技能（可按来源过滤）")

    skill_group = parser.add_argument_group("技能执行")
    skill_group.add_argument("-e", "--execute", metavar="SKILL",
                             help="直接执行指定技能")
    skill_group.add_argument("-s", "--script", metavar="SCRIPT",
                             help="指定脚本名（默认自动挑选）")
    skill_group.add_argument("-a", "--arg", action="append", metavar="VAL",
                             dest="pos_args",
                             help="位置参数（可多次使用）")

    wf_group = parser.add_argument_group("工作流")
    wf_group.add_argument("--workflows", action="store_true",
                          help="列出所有工作流")
    wf_group.add_argument("-w", "--workflow", metavar="NAME",
                          help="执行指定工作流")
    wf_group.add_argument("--wf-query", metavar="TEXT",
                          help="配合 --workflow: 简化的 query 输入")
    wf_group.add_argument("--inputs", metavar="JSON",
                          help="配合 --workflow: JSON 输入参数")

    mode = parser.add_argument_group("启动模式")
    mode.add_argument("-i", "--interactive", action="store_true",
                      help="交互式对话模式（默认）")
    mode.add_argument("--api", action="store_true",
                      help="启动 HTTP API 服务")
    mode.add_argument("--cli", action="store_true",
                      help="调用部署用的完整 CLI")
    mode.add_argument("--info", action="store_true",
                      help="显示项目信息")

    api_opts = parser.add_argument_group("API 服务参数")
    api_opts.add_argument("--host", default="127.0.0.1",
                          help="API 监听地址")
    api_opts.add_argument("--port", type=int, default=8765,
                          help="API 监听端口")

    parser.add_argument("-v", "--verbose", action="store_true",
                        help="详细输出")
    parser.add_argument("--topk", type=int, default=5, help="匹配技能数")

    return parser


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # 按优先级分发
    if args.info:
        return show_info()

    if args.api:
        return run_api_server(args.host, args.port, args.verbose)

    if args.cli:
        return run_full_cli()

    if args.workflows:
        return list_workflows()

    if args.workflow:
        return run_workflow(args.workflow, args.inputs, args.wf_query)

    if args.query:
        return run_query(args.query, args.topk)

    if args.list is not None:
        return run_list(args.list or None)

    if args.execute:
        return run_skill_cmd(
            skill_name=args.execute,
            script_name=args.script,
            args=args.pos_args or [],
        )

    if args.interactive:
        return run_interactive()

    # 默认：交互式
    return run_interactive()


if __name__ == "__main__":
    raise SystemExit(main())
