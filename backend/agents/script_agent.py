"""ScriptAgent: Multi-turn iterative script analysis and storyboard construction.

Unlike the one-shot analyze_script_workflow, ScriptAgent:
1. Analyzes the script structure (acts, scenes, characters)
2. Proposes a storyboard breakdown
3. Allows user to refine (add/remove scenes, adjust pacing)
4. Outputs a finalized scene list ready for production

Usage:
    agent = ScriptAgent(project_id)
    response = agent.run("这是一个武侠故事...")  # Initial script
    response = agent.run("第三场太长了，拆成两场")  # Refinement
    scenes = agent.get_scenes()  # Get finalized scenes
"""
from __future__ import annotations

import json
import logging
from typing import Any

from backend.agents.base import BaseAgent

logger = logging.getLogger(__name__)

SCRIPT_AGENT_SYSTEM_PROMPT = """你是一个专业的漫剧分镜编剧助手。你的任务是将用户提供的故事/剧本拆解为适合竖屏短视频的分镜脚本。

## 工作流程

1. 用户提供故事文本后，你分析并输出分镜方案
2. 用户可以要求修改（增删场景、调整节奏、修改对白等）
3. 你根据反馈迭代优化，直到用户满意

## 输出格式

当你完成分镜拆解时，输出 JSON 格式（用 ```json 包裹）：

```json
{
  "title": "故事标题",
  "scenes": [
    {
      "order": 1,
      "title": "场景标题",
      "visual_prompt": "英文视觉描述，用于AI生图",
      "dialogue": "角色对白",
      "speaker": "说话人",
      "characters": ["角色1", "角色2"],
      "emotion": "情绪基调",
      "camera": "镜头运动",
      "duration": 5.0
    }
  ],
  "characters": [
    {
      "name": "角色名",
      "gender": "男/女",
      "age": "年龄段",
      "appearance": "外貌描述（中文）",
      "visual_prompt": "英文外貌关键词",
      "personality": "性格特征"
    }
  ]
}
```

## 规则

- 每个场景 3-8 秒，适合竖屏 9:16
- visual_prompt 必须是英文，描述画面构图和角色动作
- 角色数量控制在 2-6 人
- 场景数量控制在 3-12 个
- 注意叙事节奏：开场 → 铺垫 → 转折 → 高潮
- 对白简洁有力，每场 1-2 句
- camera 从以下选择：dramatic_push, melancholy_pan, establishing_tilt, static, slow_push, pull_back

## 当用户要求修改时

- 理解修改意图
- 只修改相关场景，保持其他场景不变
- 输出完整的更新后 JSON
"""


class ScriptAgent(BaseAgent):
    agent_type = "script"

    @property
    def system_prompt(self) -> str:
        return SCRIPT_AGENT_SYSTEM_PROMPT

    def process_response(self, response: str) -> str:
        """Extract scenes from response if JSON is present."""
        # Try to extract JSON from response
        try:
            json_start = response.find("```json")
            json_end = response.find("```", json_start + 7)
            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start + 7:json_end].strip()
                data = json.loads(json_str)
                if isinstance(data, dict) and "scenes" in data:
                    self.state.context["scenes"] = data["scenes"]
                    self.state.context["characters"] = data.get("characters", [])
                    self.state.context["title"] = data.get("title", "")
                    self.state.status = "done"
                    logger.info(
                        "[script-agent] Extracted %d scenes, %d characters",
                        len(data["scenes"]), len(data.get("characters", [])),
                    )
        except (json.JSONDecodeError, ValueError) as exc:
            logger.debug("[script-agent] No valid JSON in response: %s", exc)

        return response

    def get_scenes(self) -> list[dict[str, Any]]:
        """Get the current scene list from agent state."""
        return self.state.context.get("scenes", [])

    def get_characters(self) -> list[dict[str, Any]]:
        """Get the current character list from agent state."""
        return self.state.context.get("characters", [])

    def get_title(self) -> str:
        """Get the extracted title."""
        return self.state.context.get("title", "")

    def is_complete(self) -> bool:
        """Check if the agent has produced a valid storyboard."""
        return bool(self.state.context.get("scenes"))
