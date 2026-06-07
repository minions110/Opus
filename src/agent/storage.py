"""
通用文件存储 —— 为每个 Agent 的产出（如文章、报告）提供统一的保存入口。
默认按日期分子目录：outputs/<agent_name>/YYYY-MM-DD/run-NN.json
"""
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional


class Storage:
    """
    把结构化数据保存到本地，支持 JSON + Markdown 双格式。
    """
    
    def __init__(self, output_root: Path, agent_name: str = "agent"):
        self.root = Path(output_root) / agent_name
        self.root.mkdir(parents=True, exist_ok=True)
        self.agent_name = agent_name
    
    # ─── 路径管理 ───────────────────────────────────
    def day_dir(self, date_str: Optional[str] = None) -> Path:
        date_str = date_str or datetime.now().strftime("%Y-%m-%d")
        d = self.root / date_str
        d.mkdir(parents=True, exist_ok=True)
        return d
    
    def _next_run_id(self, date_str: Optional[str] = None) -> int:
        """扫描当天目录找最大的 run-NN，+1 返回。"""
        d = self.day_dir(date_str)
        max_id = 0
        for f in d.iterdir():
            if f.is_file() and f.name.startswith("run-") and f.suffix in (".json", ".md"):
                try:
                    n = int(f.stem.split("-")[1])
                    if n > max_id:
                        max_id = n
                except (ValueError, IndexError):
                    pass
        return max_id + 1
    
    # ─── 保存 ───────────────────────────────────────
    def save_json(self, data: Dict[str, Any], name_prefix: str = "run",
                 date_str: Optional[str] = None, 
                 run_id: Optional[int] = None) -> Path:
        d = self.day_dir(date_str)
        run_id = run_id or self._next_run_id(date_str)
        path = d / f"{name_prefix}-{run_id:02d}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return path
    
    def save_markdown(self, md_text: str, name_prefix: str = "run",
                     date_str: Optional[str] = None,
                     run_id: Optional[int] = None) -> Path:
        d = self.day_dir(date_str)
        run_id = run_id or self._next_run_id(date_str)
        path = d / f"{name_prefix}-{run_id:02d}.md"
        with open(path, "w", encoding="utf-8") as f:
            f.write(md_text)
        return path
    
    def save_pair(self, data: Dict[str, Any], md_text: str,
                 name_prefix: str = "run",
                 date_str: Optional[str] = None) -> Dict[str, Path]:
        """同一份数据保存 JSON + MD 两个文件（共享同一个 run_id）。"""
        run_id = self._next_run_id(date_str)
        return {
            "json": self.save_json(data, name_prefix, date_str, run_id),
            "md": self.save_markdown(md_text, name_prefix, date_str, run_id),
        }
    
    # ─── 汇总报告 ───────────────────────────────────
    def save_daily_report(self, summaries: list, date_str: Optional[str] = None) -> Path:
        """把当天多篇产出汇总成一个 markdown 报告。"""
        date_str = date_str or datetime.now().strftime("%Y-%m-%d")
        lines = [f"# {self.agent_name} · 每日报告 ({date_str})", ""]
        lines.append(f"共产出 {len(summaries)} 篇内容。\n")
        for i, s in enumerate(summaries, 1):
            title = s.get("title") or s.get("query") or f"第 {i} 篇"
            lines.append(f"## {i}. {title}")
            if "query" in s:
                lines.append(f"- **Query**: {s['query']}")
            if "summary" in s:
                lines.append(f"- **摘要**: {s['summary']}")
            if "tags" in s and s["tags"]:
                lines.append(f"- **标签**: {', '.join(s['tags'])}")
            if "path_json" in s:
                lines.append(f"- **JSON**: `{s['path_json']}`")
            if "path_md" in s:
                lines.append(f"- **Markdown**: `{s['path_md']}`")
            lines.append("")
        md = "\n".join(lines)
        path = self.day_dir(date_str) / "daily-report.md"
        with open(path, "w", encoding="utf-8") as f:
            f.write(md)
        return path
    
    # ─── 查询 ───────────────────────────────────────
    def list_runs(self, date_str: Optional[str] = None) -> list:
        d = self.day_dir(date_str)
        jsons = sorted([f for f in d.iterdir()
                       if f.is_file() and f.suffix == ".json" and f.name.startswith("run-")])
        return jsons
    
    def load_json(self, date_str: str, run_id: int) -> Optional[dict]:
        path = self.day_dir(date_str) / f"run-{run_id:02d}.json"
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
