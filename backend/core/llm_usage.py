"""统一记录 LLM 调用用量、延迟和降级状态。

该模块只读取兼容 Anthropic ``messages.create`` 返回对象中的 usage 字段，
不会根据字符数或 max_tokens 猜测 token。供应商未返回 usage 时，记录
``usage_available=False``，让评测和面试展示保持可审计。
"""
from __future__ import annotations

import contextlib
import contextvars
import os
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, Optional

from prometheus_client import Counter, Gauge, Histogram


_request_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "coordexa_llm_request_id", default="unscoped"
)
_component: contextvars.ContextVar[str] = contextvars.ContextVar(
    "coordexa_llm_component", default="unknown"
)


LLM_CALLS = Counter(
    "coordexa_llm_calls_total",
    "Total LLM calls observed by Coordexa",
    ("component", "model", "status"),
)
LLM_INPUT_TOKENS = Counter(
    "coordexa_llm_input_tokens_total",
    "Input tokens returned by the provider",
    ("component", "model"),
)
LLM_OUTPUT_TOKENS = Counter(
    "coordexa_llm_output_tokens_total",
    "Output tokens returned by the provider",
    ("component", "model"),
)
LLM_USAGE_MISSING = Counter(
    "coordexa_llm_usage_missing_total",
    "LLM responses without provider usage metadata",
    ("component", "model"),
)
LLM_LATENCY = Histogram(
    "coordexa_llm_latency_seconds",
    "LLM call latency",
    ("component", "model"),
)
LLM_ESTIMATED_COST = Counter(
    "coordexa_llm_estimated_cost_usd_total",
    "Estimated cost from configured per-million-token rates",
    ("component", "model"),
)
LLM_ACTIVE = Gauge("coordexa_llm_active_calls", "Active LLM calls")


def current_request_id() -> str:
    return _request_id.get()


@contextlib.contextmanager
def request_context(request_id: Optional[str] = None) -> Iterator[str]:
    """把一次 API 请求的 ID 传播到同一 asyncio task 内的所有 LLM 调用。"""
    value = request_id or str(uuid.uuid4())[:8]
    token = _request_id.set(value)
    try:
        yield value
    finally:
        _request_id.reset(token)


@contextlib.contextmanager
def component_context(component: str) -> Iterator[None]:
    token = _component.set(component)
    try:
        yield
    finally:
        _component.reset(token)


def _usage_value(usage: Any, name: str) -> Optional[int]:
    if usage is None:
        return None
    if isinstance(usage, dict):
        value = usage.get(name)
    else:
        value = getattr(usage, name, None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _env_rate(name: str) -> Optional[float]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
        return value if value >= 0 else None
    except ValueError:
        return None


@dataclass
class LLMUsageRecord:
    request_id: str
    component: str
    model: str
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    total_tokens: Optional[int]
    usage_available: bool
    success: bool
    latency_ms: float
    estimated_cost_usd: Optional[float]
    error: Optional[str]
    timestamp: str


class LLMUsageTracker:
    def __init__(self, max_records: int = 5000):
        self._records: deque[LLMUsageRecord] = deque(maxlen=max_records)

    def record(
        self,
        *,
        model: str,
        response: Any = None,
        latency_ms: float = 0.0,
        success: bool = True,
        error: Optional[str] = None,
        component: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> LLMUsageRecord:
        usage = getattr(response, "usage", None) if response is not None else None
        input_tokens = _usage_value(usage, "input_tokens")
        output_tokens = _usage_value(usage, "output_tokens")
        total_tokens = _usage_value(usage, "total_tokens")
        if total_tokens is None and input_tokens is not None and output_tokens is not None:
            total_tokens = input_tokens + output_tokens
        available = input_tokens is not None or output_tokens is not None or total_tokens is not None

        estimated_cost = None
        if available:
            input_rate = _env_rate("COORDEXA_INPUT_COST_PER_1M")
            output_rate = _env_rate("COORDEXA_OUTPUT_COST_PER_1M")
            if input_rate is not None and output_rate is not None:
                estimated_cost = (
                    (input_tokens or 0) * input_rate
                    + (output_tokens or 0) * output_rate
                ) / 1_000_000

        model = str(model or "unknown")
        component = component or _component.get()
        record = LLMUsageRecord(
            request_id=request_id or current_request_id(),
            component=component,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            usage_available=available,
            success=bool(success),
            latency_ms=round(float(latency_ms), 3),
            estimated_cost_usd=estimated_cost,
            error=str(error) if error else None,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self._records.append(record)

        status = "success" if success else "error"
        LLM_CALLS.labels(component, model, status).inc()
        LLM_LATENCY.labels(component, model).observe(max(0.0, latency_ms) / 1000)
        if input_tokens is not None:
            LLM_INPUT_TOKENS.labels(component, model).inc(input_tokens)
        if output_tokens is not None:
            LLM_OUTPUT_TOKENS.labels(component, model).inc(output_tokens)
        if not available:
            LLM_USAGE_MISSING.labels(component, model).inc()
        if estimated_cost is not None:
            LLM_ESTIMATED_COST.labels(component, model).inc(estimated_cost)
        return record

    def records(self, request_id: Optional[str] = None, limit: int = 100) -> list[Dict[str, Any]]:
        values = list(self._records)
        if request_id:
            values = [item for item in values if item.request_id == request_id]
        return [asdict(item) for item in values[-max(1, min(limit, 500)):]]

    def summary(self, request_id: Optional[str] = None, limit: int = 500) -> Dict[str, Any]:
        values = self.records(request_id=request_id, limit=limit)
        input_tokens = sum(item["input_tokens"] or 0 for item in values)
        output_tokens = sum(item["output_tokens"] or 0 for item in values)
        total_tokens = sum(item["total_tokens"] or 0 for item in values)
        known_costs = [item["estimated_cost_usd"] for item in values if item["estimated_cost_usd"] is not None]
        return {
            "request_id": request_id or (values[-1]["request_id"] if values else None),
            "calls": len(values),
            "successful_calls": sum(1 for item in values if item["success"]),
            "failed_calls": sum(1 for item in values if not item["success"]),
            "usage_available_calls": sum(1 for item in values if item["usage_available"]),
            "usage_missing_calls": sum(1 for item in values if not item["usage_available"]),
            "input_tokens": input_tokens if any(item["input_tokens"] is not None for item in values) else None,
            "output_tokens": output_tokens if any(item["output_tokens"] is not None for item in values) else None,
            "total_tokens": total_tokens if any(item["total_tokens"] is not None for item in values) else None,
            "estimated_cost_usd": round(sum(known_costs), 8) if known_costs else None,
            "components": sorted({item["component"] for item in values}),
            "records": values,
        }

    def overview(self, limit: int = 500) -> Dict[str, Any]:
        """返回可直接用于 Swagger/前端仪表盘的聚合观测摘要。"""
        values = self.records(limit=limit)
        by_component: Dict[str, Dict[str, Any]] = {}
        by_request: Dict[str, Dict[str, Any]] = {}
        for item in values:
            component = item["component"]
            component_summary = by_component.setdefault(component, {
                "calls": 0,
                "successful_calls": 0,
                "failed_calls": 0,
                "usage_available_calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
            })
            component_summary["calls"] += 1
            component_summary["successful_calls"] += int(item["success"])
            component_summary["failed_calls"] += int(not item["success"])
            component_summary["usage_available_calls"] += int(item["usage_available"])
            component_summary["input_tokens"] += item["input_tokens"] or 0
            component_summary["output_tokens"] += item["output_tokens"] or 0
            component_summary["total_tokens"] += item["total_tokens"] or 0

            request_summary = by_request.setdefault(item["request_id"], {
                "request_id": item["request_id"],
                "calls": 0,
                "successful_calls": 0,
                "usage_available_calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "components": set(),
                "last_timestamp": item["timestamp"],
            })
            request_summary["calls"] += 1
            request_summary["successful_calls"] += int(item["success"])
            request_summary["usage_available_calls"] += int(item["usage_available"])
            request_summary["input_tokens"] += item["input_tokens"] or 0
            request_summary["output_tokens"] += item["output_tokens"] or 0
            request_summary["total_tokens"] += item["total_tokens"] or 0
            request_summary["components"].add(component)
            request_summary["last_timestamp"] = item["timestamp"]

        aggregate = self.summary(limit=limit)
        request_rows = sorted(
            (
                {**row, "components": sorted(row["components"])}
                for row in by_request.values()
            ),
            key=lambda row: row["last_timestamp"],
            reverse=True,
        )
        return {
            "limit": max(1, min(limit, 500)),
            "records_scanned": len(values),
            "request_count": len(by_request),
            "usage_available_rate": round(
                aggregate["usage_available_calls"] / aggregate["calls"], 4
            ) if aggregate["calls"] else 0.0,
            "totals": {
                "calls": aggregate["calls"],
                "successful_calls": aggregate["successful_calls"],
                "failed_calls": aggregate["failed_calls"],
                "usage_available_calls": aggregate["usage_available_calls"],
                "usage_missing_calls": aggregate["usage_missing_calls"],
                "input_tokens": aggregate["input_tokens"],
                "output_tokens": aggregate["output_tokens"],
                "total_tokens": aggregate["total_tokens"],
                "estimated_cost_usd": aggregate["estimated_cost_usd"],
            },
            "by_component": by_component,
            "by_request": request_rows,
        }


_TRACKER = LLMUsageTracker()


def get_usage_tracker() -> LLMUsageTracker:
    return _TRACKER


class _MessagesProxy:
    def __init__(self, owner: "TrackedClient", messages: Any):
        self._owner = owner
        self._messages = messages

    async def create(self, **kwargs: Any) -> Any:
        model = str(kwargs.get("model", getattr(self._owner, "_default_model", "unknown")))
        component = _component.get()
        started = time.monotonic()
        LLM_ACTIVE.inc()
        try:
            response = await self._messages.create(**kwargs)
            get_usage_tracker().record(
                model=model,
                response=response,
                latency_ms=(time.monotonic() - started) * 1000,
                success=True,
                component=component,
            )
            return response
        except Exception as ex:
            get_usage_tracker().record(
                model=model,
                latency_ms=(time.monotonic() - started) * 1000,
                success=False,
                error=str(ex),
                component=component,
            )
            raise
        finally:
            LLM_ACTIVE.dec()


class TrackedClient:
    """透明代理，兼容 AsyncAnthropic 和测试 FakeClient。"""
    def __init__(self, client: Any):
        self._client = client
        self._messages = _MessagesProxy(self, client.messages)
        self._default_model = "unknown"

    @property
    def messages(self) -> _MessagesProxy:
        return self._messages

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


def track_client(client: Any) -> Any:
    if isinstance(client, TrackedClient):
        return client
    if not hasattr(client, "messages") or not hasattr(client.messages, "create"):
        return client
    return TrackedClient(client)
