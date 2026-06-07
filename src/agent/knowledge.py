"""
知识库加载 —— 每个 Agent 的 knowledge/ 目录下可放多个 txt/json 文件。
当前支持：
  - *.txt          → 按行读取（去空行、去 # 注释）
  - *.json         → 整个文件作为 dict/list 加载
常用：
  - topic_pool.txt       话题清单（每行一个，如 "AI 大模型最新进展"）
  - sensitive_words.txt  敏感词 / 不宜写的词（每行一个）
  - style_guide.txt      风格指南（自由文本，如"标题不超过 20 字"）
  - user_preferences.json 用户偏好（{"prefer_topics":["科技","财经"]}）
"""
import json
from pathlib import Path
from typing import Dict, List, Any, Optional


class KnowledgeBase:
    """简单文件型知识库 —— 懒加载 + 缓存。"""
    
    def __init__(self, dir_path: Path):
        self.dir = Path(dir_path)
        self._cache: Dict[str, Any] = {}
    
    # ─── 通用加载 ───────────────────────────────────
    def _load(self, name: str) -> Any:
        if name in self._cache:
            return self._cache[name]
        # 先试 .json 再试 .txt
        json_path = self.dir / f"{name}.json"
        txt_path = self.dir / f"{name}.txt"
        if json_path.exists():
            with open(json_path, "r", encoding="utf-8") as f:
                value = json.load(f)
        elif txt_path.exists():
            with open(txt_path, "r", encoding="utf-8") as f:
                lines = [ln.strip() for ln in f.readlines()
                        if ln.strip() and not ln.strip().startswith("#")]
                value = lines
        else:
            value = None
        self._cache[name] = value
        return value
    
    def reload(self) -> None:
        """清空缓存，下次访问重新从文件读。"""
        self._cache.clear()
    
    # ─── 常用便捷方法 ───────────────────────────────
    @property
    def topic_pool(self) -> List[str]:
        return self._load("topic_pool") or []
    
    @property
    def sensitive_words(self) -> List[str]:
        return self._load("sensitive_words") or []
    
    @property
    def style_guide(self) -> str:
        data = self._load("style_guide")
        if isinstance(data, list):
            return "\n".join(data)
        return data or ""
    
    @property
    def user_preferences(self) -> dict:
        return self._load("user_preferences") or {}
    
    # ─── 检查工具 ───────────────────────────────────
    def contains_sensitive(self, text: str) -> List[str]:
        """返回 text 中命中的敏感词列表。"""
        if not text:
            return []
        hits = []
        for w in self.sensitive_words:
            if w and w in text:
                hits.append(w)
        return hits
    
    def list_available(self) -> List[str]:
        """列出知识库目录下所有可用文件（不含扩展名）。"""
        if not self.dir.exists():
            return []
        names = []
        for f in sorted(self.dir.iterdir()):
            if f.is_file() and f.suffix in (".txt", ".json"):
                names.append(f.stem)
        return names
    
    def get(self, name: str, default: Any = None) -> Any:
        """通用获取：kb.get("topic_pool", [])。"""
        v = self._load(name)
        return default if v is None else v
    
    def describe(self) -> str:
        """给 LLM 看的简短描述。"""
        files = self.list_available()
        if not files:
            return "(知识库为空)"
        lines = []
        for name in files:
            data = self._load(name)
            if isinstance(data, list):
                lines.append(f"- {name}: {len(data)} 项，例: {data[0] if data else '空'}")
            elif isinstance(data, dict):
                lines.append(f"- {name}: {len(data)} 个字段 ({', '.join(list(data.keys())[:5])})")
            else:
                lines.append(f"- {name}: {str(data)[:80]}")
        return "\n".join(lines)
