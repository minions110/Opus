"""配置管理模块 - 支持环境变量、.env 文件和 Opus.json 加载"""

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional

import yaml


def load_env_file(env_path: str = ".env") -> Dict[str, str]:
    """加载 .env 文件中的环境变量"""
    env_vars = {}
    path = Path(env_path)
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key.strip()] = value.strip()
    return env_vars


def load_opus_json(json_path: str = "data/Opus.json") -> Dict[str, Any]:
    """加载 Opus.json 配置文件"""
    path = Path(json_path)
    if not path.exists():
        return {}
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Opus.json 解析失败: {exc}")
        return {}


def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    """加载配置文件，支持环境变量覆盖"""
    # 先加载 .env 文件
    env_vars = load_env_file()
    
    # 加载 Opus.json（技能和 LLM 的 API Keys）
    opus_config = load_opus_json()
    
    # 加载 YAML 配置
    path = Path(config_path)
    if not path.exists():
        config = {"skill_roots": [], "min_relevance": 0.15}
    else:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
        except (yaml.YAMLError, OSError) as exc:
            print(f"配置解析失败: {exc}")
            config = {"skill_roots": [], "min_relevance": 0.15}
    
    if not isinstance(config, dict):
        config = {"skill_roots": [], "min_relevance": 0.15}
    
    # 设置默认值
    config.setdefault("skill_roots", [])
    config.setdefault("min_relevance", 0.15)
    config.setdefault("history_limit", 20)
    
    # 合并 Opus.json 中的配置
    if opus_config:
        config.setdefault("api_keys", {})
        config["api_keys"].update(opus_config.get("api_keys", {}))
        
        # 合并 settings
        settings = opus_config.get("settings", {})
        config.setdefault("settings", {})
        config["settings"].update(settings)
    
    # 添加 API keys（优先环境变量，其次 .env 文件）
    env_api_keys = {}
    for key in ["TAVILY_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]:
        # 优先系统环境变量
        value = os.environ.get(key)
        if not value:
            # 其次 .env 文件
            value = env_vars.get(key)
        if value:
            env_api_keys[key] = value
    
    if env_api_keys:
        config.setdefault("env_api_keys", {})
        config["env_api_keys"].update(env_api_keys)
    
    return config


def get_api_key(name: str, category: str = None) -> Optional[str]:
    """获取指定的 API Key
    
    优先级：
    1. 系统环境变量（如 TAVILY_API_KEY）
    2. .env 文件
    3. Opus.json 中的配置（支持分类查找）
    4. config.yaml 中的 api_keys 配置
    
    Args:
        name: API Key 名称（如 'tavily', 'openai', 'TAVILY_API_KEY'）
        category: 分类（'skills', 'llm', 'other'），如果为 None 则自动检测
    
    Returns:
        API Key 值，如果未找到返回 None
    """
    # 1. 系统环境变量
    env_name = name.upper()
    if not env_name.endswith("_API_KEY"):
        env_name = f"{env_name}_API_KEY"
    value = os.environ.get(env_name)
    if value:
        return value
    
    # 2. .env 文件
    env_vars = load_env_file()
    value = env_vars.get(env_name)
    if value:
        return value
    
    # 3. Opus.json
    opus_config = load_opus_json()
    api_keys = opus_config.get("api_keys", {})
    
    # 尝试按分类查找
    if category:
        category_config = api_keys.get(category, {})
        if name in category_config:
            return category_config[name].get("api_key")
    else:
        # 自动检测分类
        for cat in ["skills", "llm", "other"]:
            category_config = api_keys.get(cat, {})
            if name in category_config:
                return category_config[name].get("api_key")
            # 尝试小写匹配
            lower_name = name.lower()
            if lower_name in category_config:
                return category_config[lower_name].get("api_key")
    
    # 4. config.yaml
    try:
        config = load_config()
        api_keys = config.get("api_keys", {})
        return api_keys.get(name)
    except Exception:
        pass
    
    return None


def set_api_key(name: str, api_key: str, category: str = "skills", enabled: bool = True):
    """设置 API Key 到 Opus.json
    
    Args:
        name: API Key 名称（如 'tavily', 'openai'）
        api_key: API Key 值
        category: 分类（'skills', 'llm', 'other'）
        enabled: 是否启用
    """
    opus_config = load_opus_json()
    
    # 确保结构存在
    opus_config.setdefault("api_keys", {})
    opus_config["api_keys"].setdefault(category, {})
    
    # 获取现有配置
    current = opus_config["api_keys"][category].get(name, {})
    
    # 更新配置
    opus_config["api_keys"][category][name] = {
        "name": current.get("name", name),
        "api_key": api_key,
        "enabled": enabled,
        "endpoint": current.get("endpoint", ""),
        "description": current.get("description", "")
    }
    
    # 保存到文件
    path = Path("data/Opus.json")
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(opus_config, f, indent=2, ensure_ascii=False)


# 全局配置实例
_config = None


def get_config() -> Dict[str, Any]:
    """获取全局配置（单例）"""
    global _config
    if _config is None:
        _config = load_config()
    return _config
