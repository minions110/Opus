"""OPC 智能体 - 开发验证入口（万能接口）。

本文件用于快速开发/调试/验证 OPC 智能体的核心能力。
部署生产环境时应使用 `application/` 目录下的正式入口。
"""

from __future__ import annotations

import argparse
import json
import os
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
    from src.skill.skill import match_skills

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
    from src.skill.skill import create_skill_manager

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
    from src.skill.skill import create_skill_manager

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


def execute_skill(skill_name: str, *pos_args, **kwargs) -> int:
    """直接执行技能脚本，支持灵活的参数传递。
    
    用法:
        execute_skill("search", "query", max_results=5)
        execute_skill("search", query="AI news", topic="news")
    
    平台适配:
        - Windows: 直接使用 Smart Shell Executor（PowerShell 模拟）
        - Linux/macOS: 使用原生 bash
    """
    from src.skill.skill import create_skill_manager
    from src.agent.executor import _run_with_powershell_emulation

    config_path = str(PROJECT_ROOT / "config.yaml")
    mgr = create_skill_manager(config_path)
    skill = mgr.registry.get(skill_name)

    if not skill:
        print(f"[错误] 找不到技能: {skill_name}")
        print(f"可用技能: {[s.name for s in mgr.registry.list()]}")
        return 1

    print(f"执行技能: {skill.name}")
    print(f"技能路径: {skill.path}")
    print(f"位置参数: {pos_args}")
    print(f"关键字参数: {kwargs}")
    print("-" * 60)

    if kwargs:
        import json
        json_args = json.dumps(kwargs)
        args_list = [json_args]
    elif pos_args:
        args_list = list(pos_args)
    else:
        args_list = None

    # 找到脚本路径
    from src.agent.executor import _pick_executable
    
    # 从 Opus.json 加载 API Key
    opus_json_path = PROJECT_ROOT / "data" / "Opus.json"
    api_keys_env = {}
    if opus_json_path.exists():
        try:
            with open(opus_json_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                skills_keys = config.get("api_keys", {}).get("skills", {})
                for key_name, key_info in skills_keys.items():
                    if key_info.get("enabled", False) and key_info.get("api_key"):
                        env_var_name = f"{key_name.upper()}_API_KEY"
                        api_keys_env[env_var_name] = key_info["api_key"]
        except (json.JSONDecodeError, OSError):
            pass
    
    skill_obj = mgr.registry.get(skill_name)
    if skill_obj:
        script_path = _pick_executable(skill_obj)
        if script_path and script_path.exists():
            # 根据脚本类型选择执行方式
            if script_path.suffix == ".py":
                # Python 脚本直接执行
                print(f"[Python] 直接执行 Python 脚本: {script_path.name}")
                cmd = [sys.executable, str(script_path)] + (args_list or [])
                # 合并环境变量
                env = {**os.environ, **api_keys_env, "PYTHONIOENCODING": "utf-8"}
                try:
                    proc = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=False,
                        timeout=120,
                        env=env,
                    )
                    print("\n[执行结果]")
                    print(f"  动作: run: python {script_path.name}")
                    print(f"  返回码: {proc.returncode}")
                    if proc.stdout:
                        try:
                            stdout_str = proc.stdout.decode('utf-8')
                        except UnicodeDecodeError:
                            stdout_str = proc.stdout.decode('gbk', errors='replace')
                        print(f"  stdout:\n{stdout_str}")
                    if proc.stderr:
                        try:
                            stderr_str = proc.stderr.decode('utf-8')
                        except UnicodeDecodeError:
                            stderr_str = proc.stderr.decode('gbk', errors='replace')
                        print(f"  stderr:\n{stderr_str}")
                    return 0 if proc.returncode == 0 else 1
                except subprocess.TimeoutExpired:
                    print("\n[执行结果]")
                    print("  动作: timeout")
                    print("  返回码: 124")
                    print("  stderr: 执行超时 (120s)")
                    return 124
                except OSError as exc:
                    print("\n[执行结果]")
                    print("  动作: error")
                    print(f"  返回码: 2")
                    print(f"  stderr: 无法执行: {exc}")
                    return 2
            elif script_path.suffix == ".sh" and sys.platform.startswith("win"):
                # Windows 平台使用 PowerShell 模拟执行 shell 脚本
                print(f"[Smart Shell] Windows 平台，使用 PowerShell 模拟执行: {script_path.name}")
                result = _run_with_powershell_emulation(script_path, args_list)
                _print_result(result)
                return 0 if result.returncode == 0 else 1
            else:
                # 其他平台或脚本类型使用原生执行方式
                result = mgr.execute_skill(skill_name, args=args_list)
                _print_result(result)
                return 0 if result.returncode == 0 else 1
        else:
            print(f"[错误] 无法找到可执行脚本")
            return 1
    else:
        print(f"[错误] 找不到技能对象")
        return 1


def run_workflow(name: str, inputs_json: Optional[str] = None,
                 query: Optional[str] = None) -> int:
    """执行工作流。"""
    from src.workflow.workflow import (
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
        print(f"[工作流模式] 使用 query: {query}")

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
    from src.workflow.workflow import discover_workflows
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


# ---------------------------------------------------------------------------
# Agent 相关（子智能体调度）
# ---------------------------------------------------------------------------

def list_agents(config_path: Optional[str] = None) -> int:
    """列出所有可用 Agent（含简要说明）。"""
    from src.agent.agent import Agent
    from src.agent.registry import registry

    cfg = str(config_path or (PROJECT_ROOT / "config.yaml"))
    base_agent = Agent(cfg)

    print("\n=== 可用 Agent ===")
    print(registry.describe_all(base_agent))
    return 0


def _print_agent_result(result) -> None:
    """agent 任务结果的统一打印。"""
    if not isinstance(result, dict):
        print(f"\n[结果] {result}")
        return
    requested = result.get("requested")
    if requested is not None:
        skipped = result.get("skipped", 0) or 0
        print(f"\n=== Agent 任务完成 ===")
        line = f"请求: {requested} 篇，成功: {result.get('success')}，失败: {result.get('failure')}"
        if skipped > 0:
            line += f"，跳过: {skipped}"
        print(line)
        for i, art in enumerate(result.get("articles", []), 1):
            title = art.get("title") or art.get("query") or "(无标题)"
            path_md = art.get("path_md", "")
            path_json = art.get("path_json", "")
            print(f"\n  [{i}] {title}")
            if path_md:
                print(f"       Markdown: {path_md}")
            if path_json:
                print(f"       JSON:     {path_json}")
    elif result.get("task") == "suggest_topics":
        print(f"\n[话题建议] 共 {result.get('n')} 个：")
        for i, t in enumerate(result.get("topics", []), 1):
            print(f"  {i:2d}. {t}")
    else:
        print(f"\n[结果] {json.dumps(result, ensure_ascii=False, indent=2)}")


def run_agent_cmd(agent_name: str, *,
                  n: int = 10,
                  suggest: int = 0,
                  topics: Optional[str] = None,
                  query: Optional[str] = None,
                  task: Optional[str] = None,
                  config_path: Optional[str] = None) -> int:
    """直接跑指定 Agent。"""
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO,
                         format="[%(asctime)s] %(levelname)s %(name)s: %(message)s")

    from src.agent.agent import Agent
    from src.agent.registry import registry

    cfg = str(config_path or (PROJECT_ROOT / "config.yaml"))
    base_agent = Agent(cfg)
    name = agent_name.lower().strip()

    sub = registry.get(name, base_agent)
    print(f"调用 Agent: {name}")

    # 话题池（逗号分隔字符串 -> list）
    topic_pool = None
    if topics:
        topic_pool = [t.strip() for t in topics.split(",") if t.strip()]

    # 先优先处理 workflow/skill 直达（用户明确说跑一个 workflow）
    if task and task.lower() in ("workflow", "wf") and query:
        wf_result = sub.workflow(query, {"query": query, "count": 10})
        try:
            text = json.dumps(wf_result, ensure_ascii=False, indent=2)
        except Exception:
            text = str(wf_result)
        print(f"\n[工作流结果] {text[:2000]}")
        return 0

    # 否则走 Agent 自己的 run()
    if suggest and suggest > 0:
        result = sub.run(task="suggest_topics", n=suggest)
    elif task:
        result = sub.run(task=task, n=n, topic_pool=topic_pool, query=query)
    elif name == "toutiao":
        result = sub.run(task="daily_batch", n=n, topic_pool=topic_pool)
    else:
        result = sub.run(n=n, topic_pool=topic_pool, query=query)

    _print_agent_result(result)
    return 0


def run_instruction(instruction: str,
                    config_path: Optional[str] = None) -> int:
    """给主调度器发一条自然语言指令，让它自动选 Agent。"""
    from src.agent.agent import Agent
    from src.agent.registry import registry

    cfg = str(config_path or (PROJECT_ROOT / "config.yaml"))
    base_agent = Agent(cfg)

    orch = registry.get("main", base_agent)
    print(f"总调度器收到指令: {instruction}")

    result = orch.run(instruction=instruction)
    if isinstance(result, dict) and result.get("task") == "route" and result.get("ok"):
        inner = result.get("result") or {}
        if result.get("dispatched_to") == "toutiao":
            _print_agent_result(inner)
            return 0
    _print_agent_result(result)
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
    print("  src/skill/   # 技能加载与匹配")
    print("  src/workflow/ # 工作流引擎")
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
    quick.add_argument("-l", "--list", nargs="?", const="skills", metavar="TYPE",
                       choices=["skills", "workflows"],
                       help="列出资源类型: skills - 技能列表, workflows - 工作流列表")

    skill_group = parser.add_argument_group("技能执行")
    skill_group.add_argument("-e", "--execute", metavar="SKILL",
                             help="直接执行指定技能")
    skill_group.add_argument("-s", "--script", metavar="SCRIPT",
                             help="指定脚本名（默认自动挑选）")
    skill_group.add_argument("-a", "--arg", action="append", metavar="VAL",
                             dest="pos_args",
                             help="位置参数（可多次使用）")
    skill_group.add_argument("-k", "--kwarg", action="append", metavar="KEY=VAL",
                             dest="kwargs",
                             help="关键字参数（可多次使用，如 -k query=test）")

    wf_group = parser.add_argument_group("工作流")
    wf_group.add_argument("--workflows", action="store_true",
                          help="列出所有工作流（同 --list workflows）")
    wf_group.add_argument("-w", "--workflow", metavar="NAME",
                          help="执行指定工作流")
    wf_group.add_argument("--wf-query", metavar="TEXT",
                          help="配合 --workflow: 简化的 query 输入")
    wf_group.add_argument("--inputs", metavar="JSON",
                          help="配合 --workflow: JSON 输入参数")

    agent_group = parser.add_argument_group("智能体 (Agent)")
    agent_group.add_argument("--agents", action="store_true",
                             help="列出所有可用 Agent")
    agent_group.add_argument("--agent", metavar="NAME",
                             help="直接执行指定 Agent（如 toutiao）")
    agent_group.add_argument("--run", metavar="INSTRUCTION",
                             help="给主调度器发一条自然语言指令，自动选择合适的 Agent")
    agent_group.add_argument("--task", metavar="TASK",
                             help="配合 --agent: 指定任务名 (daily_batch/single_article/suggest_topics/workflow)")
    agent_group.add_argument("--n", type=int, default=10,
                             help="配合 --agent: 生成多少篇/条 (默认 10)")
    agent_group.add_argument("--suggest", type=int, default=0,
                             help="配合 --agent: 只建议 n 个话题，不实际跑")
    agent_group.add_argument("--topics", type=str,
                             help="配合 --agent: 用逗号分隔的自定义话题列表")

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
    config_path = str(PROJECT_ROOT / "config.yaml")

    # 按优先级分发（Agent 组优先）
    if args.info:
        return show_info()

    if args.agents:
        return list_agents(config_path)

    if args.agent:
        return run_agent_cmd(
            args.agent,
            n=args.n,
            suggest=args.suggest if args.suggest else 0,
            topics=args.topics,
            query=(getattr(args, 'query', None) or getattr(args, 'wf_query', None)),
            task=args.task,
            config_path=config_path,
        )

    if args.run:
        return run_instruction(args.run, config_path)

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
        if args.list == "workflows":
            return list_workflows()
        else:
            # 默认列出技能（支持按来源过滤）
            return run_list(args.list if args.list != "skills" else None)

    if args.execute:
        kwargs_dict = {}
        if args.kwargs:
            for kw in args.kwargs:
                if '=' in kw:
                    key, val = kw.split('=', 1)
                    kwargs_dict[key.strip()] = val.strip()
        
        return execute_skill(
            skill_name=args.execute,
            * (args.pos_args or []),
            **kwargs_dict
        )

    if args.interactive:
        return run_interactive()

    # 默认：交互式
    return run_interactive()


if __name__ == "__main__":
    raise SystemExit(main())
