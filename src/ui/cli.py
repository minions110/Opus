"""命令行界面（CLI）。"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent",
        description="统一使用 openclaw 技能的智能体",
    )
    parser.add_argument(
        "-c", "--config",
        default=str(Path(__file__).resolve().parent.parent.parent / "config.yaml"),
        help="配置文件路径（默认 ./config.yaml）",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="显示详细日志",
    )
    parser.add_argument(
        "-q", "--query", default=None,
        help="一次性执行的查询（不进入交互模式）",
    )
    parser.add_argument(
        "--topk", type=int, default=5,
        help="匹配返回的 Top-K 技能数（默认 5）",
    )
    return parser


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s: %(message)s",
    )


def interactive_loop(agent, top_k: int) -> None:
    print(f"已加载 {len(agent.list_skills())} 个技能。输入 /help 查看帮助，输入 /bye 退出。")
    while True:
        try:
            user_input = input("\n你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break
        if not user_input:
            continue
        resp = agent.ask(user_input, top_k=top_k)
        if resp.reply.strip() == "__EXIT__":
            print("再见！")
            break
        print("\nAgent>")
        print(resp.reply)


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose)

    # 延迟导入，这样 -h 时无需加载 yaml
    from ..agent.agent import Agent

    try:
        agent = Agent(args.config)
    except Exception as exc:
        print(f"[错误] 无法初始化智能体: {exc}", file=sys.stderr)
        return 2

    if args.query:
        resp = agent.ask(args.query, top_k=args.topk)
        print(resp.reply)
        return 0

    interactive_loop(agent, args.topk)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
