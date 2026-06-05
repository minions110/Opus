"""配置管理模块 - 主要从 Opus.json 加载配置"""

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional

import yaml


def load_opus_json(json_path: str = "data/Opus.json") -> Dict[str, Any]:
    """加载 Opus.json 配置文件（主要配置文件）"""
    path = Path(json_path)
    if not path.exists():
        print(f"警告: Opus.json 配置文件不存在 - {json_path}")
        return {}
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Opus.json 解析失败: {exc}")
        return {}


def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    """加载配置文件，主要从 Opus.json 获取密钥"""
    # 加载 Opus.json（技能和 LLM 的 API Keys，这是主要的配置来源）
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
    
    # 合并 Opus.json 中的配置（优先级最高）
    if opus_config:
        config.setdefault("api_keys", {})
        config["api_keys"].update(opus_config.get("api_keys", {}))
        
        # 合并 settings
        settings = opus_config.get("settings", {})
        config.setdefault("settings", {})
        config["settings"].update(settings)
    
    return config


def get_api_key(name: str, category: str = None) -> Optional[str]:
    """获取指定的 API Key（从 Opus.json 获取）
    
    Args:
        name: API Key 名称（如 'tavily', 'openai'）
        category: 分类（'skills', 'llm', 'other'），如果为 None 则自动检测
    
    Returns:
        API Key 值，如果未找到返回 None
    """
    # 从 Opus.json 获取（唯一来源）
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


def get_llm_config(provider: str) -> Optional[Dict[str, Any]]:
    """获取指定 LLM 提供商的配置。
    
    Args:
        provider: LLM 提供商名称（如 'openai', 'anthropic', 'google', 'local', 'azure'）
    
    Returns:
        LLM 配置字典，如果未找到返回 None
    """
    opus_config = load_opus_json()
    llm_configs = opus_config.get("api_keys", {}).get("llm", {})
    return llm_configs.get(provider)


def get_all_llm_configs() -> Dict[str, Dict[str, Any]]:
    """获取所有 LLM 提供商的配置。
    
    Returns:
        所有 LLM 配置字典，格式: {provider: config}
    """
    opus_config = load_opus_json()
    return opus_config.get("api_keys", {}).get("llm", {})


def get_default_llm() -> str:
    """获取默认 LLM 提供商。
    
    Returns:
        默认提供商名称
    """
    opus_config = load_opus_json()
    settings = opus_config.get("settings", {})
    return settings.get("default_llm", "openai")


def get_fallback_llm() -> str:
    """获取故障转移 LLM 提供商。
    
    Returns:
        故障转移提供商名称
    """
    opus_config = load_opus_json()
    settings = opus_config.get("settings", {})
    return settings.get("fallback_llm", "local")


# 全局配置实例
_config = None


def get_config() -> Dict[str, Any]:
    """获取全局配置（单例）"""
    global _config
    if _config is None:
        _config = load_config()
    return _config
