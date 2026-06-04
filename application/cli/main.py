"""application/cli/main.py

命令行调用 —— 通过传参直接调用指定的 skill 或工作流。

用法:
    # 1. 查询（自然语言匹配技能）
    python application/cli/main.py -q "帮我写一个 web 应用"
    python application/cli/main.py --query "部署到 Vercel"

    # 2. 列出所有技能
    python application/cli/main.py --list
    python application/cli/main.py --list openclaw

    # 3. 查看某个技能详情
    python application/cli/main.py --show web-dev
    python application/cli/main.py --info web-dev

    # 4. 执行某个技能的脚本
    python application/cli/main.py --run skill-name
    python application/cli/main.py --run skill-name --args "参数1 参数2"

    # 5. 读取技能的参考文档
    python application/cli/main.py --ref skill-name --file reference.md

    # 6. 重新扫描 (解压 zip 并重载技能)
    python application/cli/main.py --reload
    python application/cli/main.py --install

    # 7. 交互式模式 (与原 main.py 相同)
    python application/cli/main.py --interactive
    python application/cli/main.py -i

    # 8. 工作流 (顺序执行多个步骤):
    #    work1: 先 /ask "构建 web app" -> 列出相关 skill
    #    work2: 先 /show skill_name -> 再 --run
    python application/cli/main.py --workflow search:web-dev
    # 自定义工作流在 WORKFLOWS 中定义
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# 让 src.agent 包可被导入
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agent.agent import Agent           # noqa: E402
from src.agent.executor import run_skill_script  # noqa: E402


# ---------------------------------------------------------------------------
# 内置工作流定义: name -> List[dict]
# ---------------------------------------------------------------------------
# 每个工作流是一个步骤列表:
#   {"action": "ask", "query": "..."}
#   {"action": "list", "source": "..."}
#   {"action": "show", "skill": "..."}
#   {"action": "run", "skill": "...", "args": "..."}
#   {"action": "ref", "skill": "...", "file": "..."}
#   {"action": "reload"}
#
# 用户可在命令行通过 --workflow <name> 调用，多个工作流用逗号分隔
#
# 还可以: --workflow "ask:你的问题" / --workflow "show:skill-name"
#         --workflow "run:skill-name"

WORKFLOWS: Dict[str, List[Dict[str, Any]]] = {
    "search": [
        {"action": "ask", "query": "搜索网络资源"},
        {"action": "show", "skill": "search"},
    ],
    "web-dev": [
        {"action": "ask", "query": "构建一个前端 web 应用"},
    ],
    "inspect-skill": [
        {"action": "reload"},
        {"action": "list"},
    ],
}


# ---------------------------------------------------------------------------
# 输出辅助
# ---------------------------------------------------------------------------

def _section(title: str) -> None:
    bar = "=" * 60
    print()
    print(bar)
    print(f" {title}")
    print(bar)


def _pretty_skills(skills) -> None:
    by_source: Dict[str, list] = {}
    for s in skills:
        by_source.setdefault(getattr(s, "source_root", s.source), []).append(s)
    for src, items in sorted(by_source.items()):
        print(f"\n[{src}] ({len(items)} 个)")
        for s in items:
            tags = []
            if s.scripts:
                tags.append("scripts")
            if s.references:
                tags.append("refs")
            tag_str = f" [{', '.join(tags)}]" if tags else ""
            desc = (s.description or "").strip().replace("\n", " ")
            if len(desc) > 80:
                desc = desc[:80] + "..."
            print(f"   - {s.name}{tag_str}")
            if desc:
                print(f"       {desc}")


# ---------------------------------------------------------------------------
# 步骤执行
# ---------------------------------------------------------------------------

def exec_step(agent: Agent, step: dict) -> None:
    action = (step.get("action") or "").lower()
    if action == "ask":
        query = step.get("query")
        if not query:
            print("  [!] ask 步骤需要 'query'")
            return
        _section(f"[工作流] 查询: {query}")
        resp = agent.ask(query)
        print(resp.reply)

    elif action == "list":
        source = step.get("source")
        _section(f"[工作流] 列出技能 {f'(source={source})' if source else ''}")
        skills = agent.list_skills(source) if source else agent.list_skills()
        _pretty_skills(skills)

    elif action == "show":
        skill = agent.find_skill(step.get("skill", ""))
        if skill is None:
            print(f"  [!] 找不到技能: {step.get('skill')}")
            return
        _section(f"[工作流] show {skill.name}")
        print(f"  来源: {skill.source} ({skill.source_root})")
        print(f"  路径: {skill.path}")
        if skill.scripts:
            print(f"  脚本: {', '.join(skill.scripts)}")
        if skill.references:
            print(f"  参考: {', '.join(skill.references)}")
        if skill.body:
            print("\n" + skill.body[:1200])
            if len(skill.body) > 1200:
                print("\n... (已截断)")

    elif action == "run":
        skill = agent.find_skill(step.get("skill", ""))
        if skill is None:
            print(f"  [!] 找不到技能: {step.get('skill')}")
            return
        args = step.get("args")
        _section(f"[工作流] run {skill.name}")
        result = run_skill_script(skill, args=args.split() if args else None)
        print(f"  返回码: {result.returncode}")
        if result.stdout:
            print("--- stdout ---")
            print(result.stdout[:2000])
        if result.stderr:
            print("--- stderr ---")
            print(result.stderr[:2000])

    elif action == "ref":
        skill = agent.find_skill(step.get("skill", ""))
        if skill is None:
            print(f"  [!] 找不到技能: {step.get('skill')}")
            return
        filename = step.get("file")
        if not filename:
            print("  [!] ref 需要 'file' 参数")
            return
        ref_path = Path(skill.path) / "references" / filename
        if not ref_path.is_file():
            print(f"  [!] 参考文件不存在: {filename}")
            print(f"      可用: {', '.join(skill.references)}")
            return
        _section(f"[工作流] ref {skill.name}/{filename}")
        print(ref_path.read_text(encoding="utf-8", errors="replace")[:3000])

    elif action == "reload":
        _section("[工作流] 重新加载技能")
        info = agent.reload_skills()
        print(f"  总计: {info.get('total')} 个技能")
        for src, n in sorted((info.get("by_source") or {}).items()):
            print(f"    {src}: {n}")

    else:
        print(f"  [!] 未知动作: {action}")


def _is_workflow_name(agent: Agent, name: str) -> bool:
    """检查 name 是否为已注册的工作流目录名。"""
    try:
        names = [w.get("name") for w in agent.list_workflows()]
    except Exception:
        return False
    return name in names


def run_workflow_by_expression(agent: Agent, expr: str) -> None:
    """运行工作流 —— 支持两种格式:

    1. 内置工作流名 (例如: web-dev, inspect-skill)
    2. 前缀表达式:
         ask:你的问题
         show:skill-name
         run:skill-name
         list:codex
         list:openclaw
         ref:skill-name/file.md
         reload
    """
    expr = expr.strip()
    if ":" in expr:
        prefix, _, rest = expr.partition(":")
        prefix = prefix.strip().lower()
        rest = rest.strip()
        if prefix == "ask":
            exec_step(agent, {"action": "ask", "query": rest})
        elif prefix == "show":
            exec_step(agent, {"action": "show", "skill": rest})
        elif prefix == "run":
            # run:skill-name/args...
            if "/" in rest:
                skill, _, args = rest.partition("/")
                exec_step(agent, {"action": "run", "skill": skill.strip(), "args": args.strip()})
            else:
                exec_step(agent, {"action": "run", "skill": rest})
        elif prefix == "list":
            exec_step(agent, {"action": "list", "source": rest or None})
        elif prefix == "reload" or prefix == "install":
            exec_step(agent, {"action": "reload"})
        elif prefix == "ref":
            # ref:skill/file.md
            if "/" in rest:
                skill, _, fname = rest.partition("/")
                exec_step(agent, {"action": "ref", "skill": skill.strip(), "file": fname.strip()})
            else:
                print(f"  [!] ref 格式: ref:skill-name/file.md")
        else:
            # 退而求其次 —— 把整个表达式当作自然语言查询
            exec_step(agent, {"action": "ask", "query": expr})
    elif expr in WORKFLOWS:
        _section(f"[工作流] 执行: {expr}")
        for i, step in enumerate(WORKFLOWS[expr], 1):
            print(f"\n  步骤 {i}/{len(WORKFLOWS[expr])}: {step.get('action')}")
            exec_step(agent, step)
    else:
        # 退而求其次 —— 把它作为自然语言查询
        exec_step(agent, {"action": "ask", "query": expr})


# ---------------------------------------------------------------------------
# 交互式模式
# ---------------------------------------------------------------------------

def interactive_mode(agent: Agent) -> None:
    print(f"已加载 {len(agent.list_skills())} 个技能。")
    print("输入 /help 查看命令，输入 /bye 退出。")
    while True:
        try:
            line = input("\n你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break
        if not line:
            continue
        resp = agent.ask(line)
        if resp.reply.strip() == "__EXIT__":
            print("再见！")
            break
        print("\nAgent>")
        print(resp.reply)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agent-cli",
        description="统一技能智能体 —— 命令行接口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n"
               "  python application/cli/main.py -q \"构建 web 应用\"\n"
               "  python application/cli/main.py --list\n"
               "  python application/cli/main.py --show web-dev\n"
               "  python application/cli/main.py --run search --args \"python async\"\n"
               "  python application/cli/main.py --workflows\n"
               "  python application/cli/main.py --workflow test1\n"
               "  python application/cli/main.py --workflow test1 --inputs '{\"k\":\"v\"}'\n",
    )
    mode = p.add_argument_group("模式 (任选其一)")
    mode.add_argument("-q", "--query", metavar="TEXT",
                       help="自然语言查询 —— 返回最相关的 Top-K 技能")
    mode.add_argument("-l", "--list", nargs="?", const="", metavar="SOURCE",
                       help="列出技能；可加来源过滤 (codex/openclaw/hermes)")
    mode.add_argument("--show", metavar="SKILL",
                       help="查看技能详情 (别名 --info)")
    mode.add_argument("--info", metavar="SKILL", help=argparse.SUPPRESS)
    mode.add_argument("--run", metavar="SKILL", help="运行指定技能的脚本")
    mode.add_argument("--ref", metavar="SKILL", help="读取技能 references/ 中的文档 (需 --file)")
    mode.add_argument("--reload", action="store_true", help="重新加载所有技能")
    mode.add_argument("--install", action="store_true",
                       help="解压 zip 并重新加载 (更详细报告)")
    mode.add_argument("--workflows", action="store_true",
                       help="列出所有可用工作流 (data/workflows/)")
    mode.add_argument("-w", "--workflow", metavar="NAME",
                       help="执行工作流: 目录名或内置表达式; 例如 test1 / ask:你的问题")
    mode.add_argument("-i", "--interactive", action="store_true",
                       help="进入交互式对话")

    extra = p.add_argument_group("附加参数")
    extra.add_argument("--file", metavar="FILENAME",
                       help="配合 --ref 使用: 指定参考文件名")
    extra.add_argument("--args", metavar="ARGS",
                       help="配合 --run 使用: 传递给脚本的参数字符串")
    extra.add_argument("--inputs", metavar="JSON",
                       help="配合 --workflow 使用: 传入工作流的输入 (JSON 字符串)")
    extra.add_argument("--top-k", type=int, default=5,
                       help="--query 返回技能数 (默认 5)")
    extra.add_argument("--json", action="store_true",
                       help="输出 JSON 格式 (便于管道)")
    extra.add_argument("-v", "--verbose", action="store_true", help="显示详细日志")
    extra.add_argument("-c", "--config", default=None,
                       help="配置文件路径 (默认项目根 config.yaml)")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="[%(asctime)s] %(levelname)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    cfg_path = args.config or str(PROJECT_ROOT / "config.yaml")

    # 初始化 Agent (按需)
    agent = Agent(cfg_path)
    total = len(agent.list_skills())

    # 确定执行哪个模式 —— 优先级: reload > install > query > list > show > run > ref > workflows > workflow > interactive
    mode = "interactive"
    if args.reload:
        mode = "reload"
    elif args.install:
        mode = "install"
    elif args.query:
        mode = "query"
    elif args.list is not None:
        mode = "list"
    elif args.show or args.info:
        mode = "show"
    elif args.run:
        mode = "run"
    elif args.ref:
        mode = "ref"
    elif args.workflows:
        mode = "workflows"
    elif args.workflow:
        mode = "workflow"
    elif args.interactive:
        mode = "interactive"

    # ---------- JSON 输出模式 ----------
    if args.json:
        out: Dict[str, Any] = {"total_skills": total}
        if mode == "query":
            resp = agent.ask(args.query, top_k=args.top_k)
            out["reply"] = resp.reply
            out["matched_skills"] = [
                {"name": s.name, "source": s.source, "score": float(sc),
                 "description": s.description,
                 "scripts": list(s.scripts), "references": list(s.references)}
                for s, sc in resp.matched_skills
            ]
        elif mode == "list":
            skills = agent.list_skills(source=(args.list or None))
            out["skills"] = [{"name": s.name, "source": s.source,
                               "source_root": s.source_root,
                               "description": s.description,
                               "scripts": list(s.scripts),
                               "references": list(s.references)}
                              for s in skills]
            out["count"] = len(skills)
        elif mode == "show":
            sname = args.show or args.info
            skill = agent.find_skill(sname)
            if skill is None:
                out["error"] = f"未找到技能: {sname}"
            else:
                out["skill"] = {
                    "name": skill.name, "source": skill.source,
                    "source_root": skill.source_root,
                    "description": skill.description,
                    "body": skill.body,
                    "scripts": list(skill.scripts),
                    "references": list(skill.references),
                    "assets": list(skill.assets),
                    "path": str(skill.path),
                }
        elif mode == "run":
            skill = agent.find_skill(args.run)
            if skill is None:
                out["error"] = f"未找到技能: {args.run}"
            else:
                res = run_skill_script(skill, args=args.args.split() if args.args else None)
                out["run"] = {"skill": skill.name, "returncode": res.returncode,
                              "stdout": res.stdout, "stderr": res.stderr,
                              "ok": res.returncode == 0}
        elif mode in ("reload", "install"):
            out["reload"] = agent.reload_skills()
        elif mode == "workflows":
            out["workflows"] = agent.list_workflows()
        elif mode == "workflow":
            # 先走工作流引擎（目录名匹配），失败再回落到表达式模式
            if _is_workflow_name(agent, args.workflow):
                inputs: dict = {}
                if args.inputs:
                    import json as _json
                    try:
                        inputs = _json.loads(args.inputs)
                    except Exception as exc:
                        out["error"] = f"--inputs 不是合法 JSON: {exc}"
                        print(json.dumps(out, ensure_ascii=False, indent=2))
                        return 1
                r = agent.run_workflow(args.workflow, inputs=inputs)
                out["workflow"] = {
                    "name": r.name,
                    "ok": r.ok,
                    "error": r.error,
                    "steps": [
                        {"id": s.step_id, "action": s.action, "ok": s.ok,
                         "error": s.error, "output": s.output}
                        for s in r.steps
                    ],
                }
            else:
                out["workflow_expr"] = args.workflow
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    # ---------- 常规文本输出 ----------
    if mode == "interactive":
        interactive_mode(agent)
        return 0

    if mode == "reload":
        _section("重新加载技能")
        info = agent.reload_skills()
        print(f"总计: {info.get('total')}")
        for src, n in sorted((info.get("by_source") or {}).items()):
            print(f"  {src}: {n}")
        return 0

    if mode == "install":
        _section("安装 / 重新加载技能")
        info = agent.reload_skills()
        skills = agent.list_skills()
        print(f"总计: {len(skills)}")
        _pretty_skills(skills)
        return 0

    if mode == "query":
        _section(f"查询: {args.query}")
        resp = agent.ask(args.query, top_k=args.top_k)
        print(resp.reply)
        return 0

    if mode == "list":
        _section(f"技能列表 ({args.list or '全部'})")
        skills = agent.list_skills(source=(args.list or None))
        print(f"共 {len(skills)} 个技能")
        _pretty_skills(skills)
        return 0

    if mode == "show":
        sname = args.show or args.info
        skill = agent.find_skill(sname)
        if skill is None:
            print(f"未找到技能: {sname}")
            return 1
        _section(f"技能: {skill.name}")
        print(f"来源:    {skill.source} ({skill.source_root})")
        print(f"路径:    {skill.path}")
        if skill.description:
            print(f"描述:    {skill.description[:200]}")
        if skill.scripts:
            print(f"脚本:    {', '.join(skill.scripts)}")
        if skill.references:
            print(f"参考:    {', '.join(skill.references)}")
        if skill.assets:
            print(f"资源:    {len(skill.assets)} 个文件")
        if skill.body:
            _section("正文")
            print(skill.body[:2000])
            if len(skill.body) > 2000:
                print("\n... (已截断)")
        return 0

    if mode == "run":
        skill = agent.find_skill(args.run)
        if skill is None:
            print(f"未找到技能: {args.run}")
            return 1
        if not skill.scripts:
            print(f"技能 {skill.name} 没有可执行脚本")
            return 1
        _section(f"run: {skill.name}" + (f" args={args.args}" if args.args else ""))
        res = run_skill_script(skill, args=args.args.split() if args.args else None)
        print(f"返回码: {res.returncode}")
        if res.stdout:
            print("--- stdout ---")
            print(res.stdout[:4000])
        if res.stderr:
            print("--- stderr ---")
            print(res.stderr[:4000])
        return 0 if res.returncode == 0 else res.returncode

    if mode == "ref":
        if not args.file:
            print("使用 --ref 时必须提供 --file <filename>")
            return 2
        skill = agent.find_skill(args.ref)
        if skill is None:
            print(f"未找到技能: {args.ref}")
            return 1
        ref_path = Path(skill.path) / "references" / args.file
        if not ref_path.is_file():
            print(f"参考文件不存在: {args.file}")
            print(f"  可用: {', '.join(skill.references)}")
            return 1
        _section(f"ref: {skill.name}/{args.file}")
        print(ref_path.read_text(encoding="utf-8", errors="replace"))
        return 0

    if mode == "workflows":
        wfs = agent.list_workflows()
        if not wfs:
            print("没有发现任何工作流。请在 data/workflows/<name>/workflow.yaml 下创建。")
            return 0
        print(f"共 {len(wfs)} 个工作流:\n")
        for w in wfs:
            step_note = f"  ({w.get('step_count', 0)} 步)" if w.get('step_count') else ""
            desc = (w.get('description') or "").strip().replace("\n", " ")
            print(f"  - {w.get('name')}{step_note}")
            if desc:
                print(f"      {desc[:200]}")
            inputs = w.get("inputs") or []
            if inputs:
                print(f"      inputs: {', '.join(str(i.get('name')) for i in inputs)}")
        return 0

    if mode == "workflow":
        # 支持多个工作流以逗号分隔（对目录名型工作流也生效）
        for expr in args.workflow.split(","):
            expr = expr.strip()
            if not expr:
                continue
            if _is_workflow_name(agent, expr):
                # 通过工作流引擎执行
                inputs: dict = {}
                if args.inputs:
                    import json as _json
                    try:
                        inputs = _json.loads(args.inputs)
                    except Exception as exc:
                        print(f"[错误] --inputs 不是合法 JSON: {exc}")
                        return 1
                r = agent.run_workflow(expr, inputs=inputs)
                _section(f"[工作流] {r.name}  ok={r.ok}")
                for s in r.steps:
                    status = "OK" if s.ok else "FAIL"
                    print(f"  - [{status}] {s.step_id} ({s.action})")
                    if s.error:
                        print(f"      error: {s.error}")
                    if s.output is not None:
                        out_text = str(s.output)
                        if len(out_text) > 400:
                            out_text = out_text[:400] + "..."
                        print(f"      output: {out_text}")
                if r.error:
                    print(f"\n最终错误: {r.error}")
                if not r.ok:
                    return 1
            else:
                # 回落到旧的表达式模式 (ask:xxx / run:xxx 等)
                run_workflow_by_expression(agent, expr)
        return 0

    # 默认: 交互式
    interactive_mode(agent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
