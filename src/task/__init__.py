"""task —— 所有 agent 的任务执行引擎。

架构：
  src/task/task.py            TaskExecutor（通用引擎，按任务名分派到 handler）
  data/agents/<agent>/tasks/  *.yaml  任务声明（name / handler / 元信息）

约定 —— 每个任务 YAML 长这样（以 batch_articles 为模板）：

  name: batch_articles
  handler: batch_articles          # 映射到 TaskExecutor._handler_<handler>()
  description: |
    一句话说明这个任务做什么
  inputs:
    - name: n
      type: number
      default: 10
      description: 生成多少篇
    - name: topics
      type: string
      default: ""
      description: 可选，逗号分隔的自定义话题列表
  workflow_name: search-toutiao    # 若该任务是跑工作流，指定工作流名
  output_dir: outputs/toutiao_agent

新增任务的最小步骤：
  1. 在 data/agents/<agent>/tasks/ 下新建一个 yaml（参考上面格式）
  2. 在 TaskExecutor 里新增一个 _handler_<name>(self, task_def, inputs) 方法
  3. 就可以用 python main.py --agent <name> --task <任务名> --n 10 调用
"""
from .task import TaskExecutor

__all__ = ["TaskExecutor"]
