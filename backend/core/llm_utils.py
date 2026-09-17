"""LLM response helpers shared by Anthropic-compatible providers."""
import json
import re
from typing import Any, Dict, Iterable, List, Optional, Type


def extract_text_content(content: Iterable[Any]) -> str:
    """Return text blocks from Anthropic-style response content."""
    texts: List[str] = []
    for block in content or []:
        if isinstance(block, str):
            texts.append(block)
            continue

        block_type = getattr(block, "type", None)
        text = getattr(block, "text", None)
        if isinstance(block, dict):
            block_type = block.get("type", block_type)
            text = block.get("text", text)

        if isinstance(text, str) and (block_type in (None, "text")):
            texts.append(text)

    return "\n".join(t for t in texts if t)


def extract_json_value(text: str, expected_type: Optional[Type] = None) -> Any:
    """Extract the first valid JSON value from fenced or explanatory model text."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("LLM 未返回可解析文本")

    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if expected_type is None or isinstance(value, expected_type):
            return value

    expected = expected_type.__name__ if expected_type else "JSON"
    raise ValueError(f"LLM 文本中没有有效的 {expected}")


def extract_labeled_floats(text: str, labels: Iterable[str]) -> Dict[str, float]:
    """Parse ``label: 0.8`` pairs when a compatible model omits JSON braces."""
    values: Dict[str, float] = {}
    for label in labels:
        match = re.search(
            rf"(?i)(?:[\"']?{re.escape(label)}[\"']?)\s*[:=：]\s*"
            r"([-+]?(?:\d+(?:\.\d*)?|\.\d+))",
            text or "",
        )
        if match:
            values[label] = float(match.group(1))
    return values
