"""
通用长期记忆管理 —— 每个 Agent 一个独立的 JSON 记忆文件。
提供：读写、关键词搜索、历史记录追加。
"""
import json
from pathlib import Path
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Optional, List, Dict


class Memory:
    """
    基于 JSON 文件的长期记忆。
    
    数据结构：
        {
            "version": 1,
            "created": "2026-06-06T10:30:00",
            "updated": "2026-06-06T11:00:00",
            "history": [ ... ],              // 任意记录列表（每条可含任意字段）
            "kv": { ... },                    // 键值存储（用户偏好、flag 等）
            "index": {                        // 简单倒排索引（可选，用于搜索）
                "titles": ["标题1", "标题2", ...]
            }
        }
    """
    
    def __init__(self, file_path: Path):
        self.file_path = Path(file_path)
        self.data = self._load()
    
    # ─── 基础 IO ─────────────────────────────────────
    def _load(self) -> dict:
        if not self.file_path.exists():
            now = datetime.now().isoformat(timespec="seconds")
            return {
                "version": 1,
                "created": now,
                "updated": now,
                "history": [],
                "kv": {},
                "index": {"titles": []}
            }
        with open(self.file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 保证字段存在
        data.setdefault("history", [])
        data.setdefault("kv", {})
        data.setdefault("index", {})
        data["index"].setdefault("titles", [])
        return data
    
    def save(self) -> None:
        self.data["updated"] = datetime.now().isoformat(timespec="seconds")
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        tmp.replace(self.file_path)
    
    # ─── History（有序列表） ─────────────────────────
    def append(self, record: Dict[str, Any]) -> int:
        """追加一条记录到 history，返回新记录的 index。"""
        record.setdefault("timestamp", datetime.now().isoformat(timespec="seconds"))
        self.data["history"].append(record)
        # 自动维护标题索引
        if "title" in record and record["title"]:
            self.data["index"]["titles"].append(str(record["title"]))
        self.save()
        return len(self.data["history"]) - 1
    
    def recent(self, n: int = 10) -> List[Dict[str, Any]]:
        """取最近 n 条记录。"""
        return list(self.data["history"][-n:])
    
    def all_history(self) -> List[Dict[str, Any]]:
        return list(self.data["history"])
    
    # ─── KV 存储 ─────────────────────────────────────
    def remember(self, key: str, value: Any) -> None:
        self.data["kv"][key] = value
        self.save()
    
    def recall(self, key: str, default: Any = None) -> Any:
        return self.data["kv"].get(key, default)
    
    def forget(self, key: str) -> None:
        if key in self.data["kv"]:
            del self.data["kv"][key]
            self.save()
    
    # ─── 标题相似度去重 ─────────────────────────────
    def title_exists_similar(self, new_title: str, threshold: float = 0.75, 
                            recent_n: int = 50) -> bool:
        """
        检查 new_title 是否与历史记录里最近 recent_n 条的 title 相似度 >= threshold。
        返回 True 表示"疑似重复"。
        """
        if not new_title:
            return False
        # 取最近的若干条记录的 title 比较，避免全量扫描
        recent_titles = []
        for rec in self.data["history"][-recent_n:]:
            t = rec.get("title")
            if t:
                recent_titles.append(t)
        # 也比较索引里的标题（去重）
        for t in self.data["index"]["titles"][-recent_n:]:
            if t not in recent_titles:
                recent_titles.append(t)
        
        for existing in recent_titles:
            sim = SequenceMatcher(None, new_title, existing).ratio()
            if sim >= threshold:
                return True
        return False
    
    # ─── 搜索（简单关键词匹配） ───────────────────────
    def search(self, keyword: str, field: Optional[str] = None, 
              limit: int = 20) -> List[Dict[str, Any]]:
        """按关键词搜索历史记录（包含字段名+内容）。"""
        kw = keyword.strip().lower()
        if not kw:
            return []
        results = []
        for rec in reversed(self.data["history"]):
            if field:
                haystack = str(rec.get(field, "")).lower()
            else:
                haystack = " ".join(str(v) for v in rec.values()).lower()
            if kw in haystack:
                results.append(rec)
                if len(results) >= limit:
                    break
        return results
    
    # ─── 统计 ──────────────────────────────────────
    def count(self) -> int:
        return len(self.data["history"])
    
    def summary(self) -> Dict[str, Any]:
        return {
            "total_records": len(self.data["history"]),
            "kv_keys": len(self.data["kv"]),
            "title_count": len(self.data["index"]["titles"]),
            "created": self.data.get("created"),
            "updated": self.data.get("updated"),
        }
