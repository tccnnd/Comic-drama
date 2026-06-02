"""Base agent framework for multi-turn LLM-driven production tasks."""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class AgentMessage:
    role: str  # "system", "user", "assistant"
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentState:
    """Persistent state for an agent session."""
    agent_id: str
    project_id: str
    messages: list[AgentMessage] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    status: str = "idle"  # idle, thinking, waiting_input, done, error
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class BaseAgent:
    """Base class for production agents.

    Subclasses implement:
    - system_prompt: The agent's role and instructions
    - process_response: Handle LLM response and decide next action
    - available_tools: What actions the agent can take
    """

    agent_type: str = "base"

    def __init__(self, project_id: str, llm_fn: Callable | None = None):
        self.project_id = project_id
        self.state = AgentState(
            agent_id=f"{self.agent_type}_{project_id}",
            project_id=project_id,
        )
        self._llm_fn = llm_fn or self._default_llm_fn

    @property
    def system_prompt(self) -> str:
        raise NotImplementedError

    def run(self, user_input: str) -> str:
        """Process user input and return agent response."""
        self.state.status = "thinking"
        self.state.messages.append(AgentMessage(role="user", content=user_input))

        # Build messages for LLM
        messages = [{"role": "system", "content": self.system_prompt}]
        for msg in self.state.messages[-20:]:  # Keep last 20 messages for context
            messages.append({"role": msg.role, "content": msg.content})

        # Call LLM
        try:
            response = self._llm_fn(messages)
        except Exception as exc:
            self.state.status = "error"
            error_msg = f"LLM call failed: {exc}"
            logger.error("[agent:%s] %s", self.agent_type, error_msg)
            return error_msg

        # Process response
        self.state.messages.append(AgentMessage(role="assistant", content=response))
        self.state.status = "idle"
        self.state.updated_at = time.time()

        return self.process_response(response)

    def process_response(self, response: str) -> str:
        """Override to post-process LLM response. Default: return as-is."""
        return response

    def reset(self) -> None:
        """Reset agent state."""
        self.state.messages.clear()
        self.state.context.clear()
        self.state.status = "idle"

    def _default_llm_fn(self, messages: list[dict[str, str]]) -> str:
        """Default LLM call using project's configured LLM."""
        from scripts.run_workflow import load_env_file, post_llm_chat_completion
        load_env_file()
        return post_llm_chat_completion(messages)
