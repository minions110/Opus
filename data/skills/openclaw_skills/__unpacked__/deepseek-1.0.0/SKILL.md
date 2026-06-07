---
name: deepseek
description: "使用 DeepSeek Chat Completions API 调用大模型进行文本生成、摘要、筛选、写作等任务。需要环境变量 DEEPSEEK_API_KEY。输入 JSON：system/messages/model/temperature/max_tokens。"
---

# DeepSeek Chat (opc 内置)

## 用法

```
python scripts/deepseek.py '{"messages":[{"role":"user","content":"你好"}]}'
```

## 输入字段（JSON）

- `messages`：必填。`[{role, content}, ...]`
- `system`：可选，插入到 messages 开头作为 system 消息
- `model`：可选，默认 `deepseek-chat`
- `temperature`：可选，默认 `0.7`
- `max_tokens`：可选，默认 `2048`

## 环境变量

- `DEEPSEEK_API_KEY`：必需。在 [https://platform.deepseek.com](https://platform.deepseek.com) 获取。
- `DEEPSEEK_BASE_URL`：可选。默认 `https://api.deepseek.com`。
