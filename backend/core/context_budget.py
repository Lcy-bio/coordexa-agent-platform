"""可解释的上下文预算，避免把固定截断值误当成动态上下文策略。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class ContextBudget:
    """字符级预算；真正 Token 消耗由 LLM provider usage 记录。"""

    model_context_chars: int = 24000
    reserved_output_chars: int = 6000
    prompt_chars: int = 5000
    memory_chars: int = 6000
    retrieval_chars: int = 7000

    @classmethod
    def from_env(cls) -> "ContextBudget":
        return cls(
            model_context_chars=_int_env("COORDEXA_CONTEXT_LIMIT_CHARS", 24000, 2000),
            reserved_output_chars=_int_env("COORDEXA_CONTEXT_RESERVED_OUTPUT_CHARS", 6000, 500),
            prompt_chars=_int_env("COORDEXA_CONTEXT_PROMPT_CHARS", 5000, 500),
            memory_chars=_int_env("COORDEXA_CONTEXT_MEMORY_CHARS", 6000, 500),
            retrieval_chars=_int_env("COORDEXA_CONTEXT_RETRIEVAL_CHARS", 7000, 500),
        )

    @property
    def available_chars(self) -> int:
        return max(1000, self.model_context_chars - self.reserved_output_chars)

    def fit(self, value: str, limit: Optional[int] = None) -> str:
        text = (value or "").strip()
        target = max(0, min(limit or self.available_chars, self.available_chars))
        if len(text) <= target:
            return text
        if target <= 16:
            return text[:target]
        # 同时保留开头和结尾：前者通常包含任务/标题，后者通常包含最新约束。
        head = int(target * 0.65)
        tail = target - head - 20
        return f"{text[:head]}\n...[上下文按预算截断]...\n{text[-max(0, tail):]}"

    def fit_context(self, context: str, query: str = "") -> str:
        """按区块优先级动态分配预算，而不是无条件截断整个字符串。"""
        text = context or ""
        if not text:
            return ""
        sections = text.split("\n\n")
        memory, retrieval, other = [], [], []
        for section in sections:
            lowered = section.lower()
            if any(key in lowered for key in ("[知识库", "知识库检索", "retrieval", "检索结果")):
                retrieval.append(section)
            elif any(key in lowered for key in ("[会话", "[相关历史", "[用户画像", "[最近对话")):
                memory.append(section)
            else:
                other.append(section)
        parts = [
            self.fit("\n\n".join(other), self.prompt_chars),
            self.fit("\n\n".join(memory), self.memory_chars),
            self.fit("\n\n".join(retrieval), self.retrieval_chars),
        ]
        result = "\n\n".join(item for item in parts if item)
        return self.fit(result, self.available_chars)

