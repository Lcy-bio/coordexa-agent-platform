"""Run the Coordexa labeled acceptance benchmark against a live API."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "evaluation" / "fixtures" / "benchmark_cases.json"


def request_json(url: str, method: str = "GET", payload: Any = None, timeout: float = 180.0) -> Any:
    body = None
    headers: dict[str, str] = {}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def accepted(expected: Any, actual: Any) -> bool:
    if isinstance(expected, list):
        return actual in expected
    return actual == expected


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def entities_match(expected: dict[str, list[str]], actual: dict[str, list[str]]) -> bool:
    for key, expected_values in expected.items():
        actual_values = {str(value).replace(" ", "") for value in actual.get(key, [])}
        normalized_expected = {str(value).replace(" ", "") for value in expected_values}
        if not normalized_expected.issubset(actual_values):
            return False
    return True


def run_chat_cases(base_url: str, cases: list[dict[str, Any]]) -> dict[str, Any]:
    details = []
    latencies = []
    successful = 0
    intent_hits = 0
    primary_hits = 0
    agent_set_hits = 0
    rag_gate_hits = 0
    entity_hits = 0
    entity_total = 0

    for case in cases:
        started = time.perf_counter()
        try:
            response = request_json(
                f"{base_url}/chat",
                method="POST",
                payload={
                    "message": case["message"],
                    "user_id": f"benchmark_{case['id']}",
                    "conv_id": f"benchmark_{case['id']}",
                },
            )
            wall_ms = (time.perf_counter() - started) * 1000
            successful += 1
            # 使用客户端墙钟时间，覆盖意图识别、RAG、路由和生成的完整链路。
            latencies.append(wall_ms)

            actual_agents = set(response.get("agent_types") or [])
            actual_agents.add(response.get("primary_agent") or response.get("agent_type"))
            actual_agents.update(response.get("supporting_agents") or [])

            checks = {
                "intent": accepted(case["expected_intent"], response.get("intent")),
                "primary": accepted(case["expected_primary"], response.get("primary_agent")),
                "agent_set": set(case.get("expected_agents") or []).issubset(actual_agents),
                "rag_gate": bool(response.get("knowledge_used")) == bool(case["expect_knowledge"]),
            }
            intent_hits += int(checks["intent"])
            primary_hits += int(checks["primary"])
            agent_set_hits += int(checks["agent_set"])
            rag_gate_hits += int(checks["rag_gate"])

            expected_entities = case.get("expected_entities")
            if expected_entities:
                entity_total += 1
                checks["entities"] = entities_match(expected_entities, response.get("entities") or {})
                entity_hits += int(checks["entities"])

            details.append({
                "id": case["id"],
                "status": "ok",
                "checks": checks,
                "actual": {
                    "intent": response.get("intent"),
                    "primary_agent": response.get("primary_agent"),
                    "supporting_agents": response.get("supporting_agents") or [],
                    "knowledge_used": bool(response.get("knowledge_used")),
                    "entities": response.get("entities") or {},
                    "end_to_end_latency_ms": round(wall_ms, 2),
                    "orchestrator_latency_ms": response.get("latency_ms"),
                },
            })
        except Exception as exc:
            details.append({"id": case["id"], "status": "error", "error": str(exc)})

    total = len(cases)
    denominator = successful or 1
    return {
        "cases": total,
        "successful_requests": successful,
        "request_success_rate": round(successful / total, 4) if total else 0.0,
        "intent_accuracy": round(intent_hits / denominator, 4),
        "primary_route_accuracy": round(primary_hits / denominator, 4),
        "agent_coverage_accuracy": round(agent_set_hits / denominator, 4),
        "rag_gate_accuracy": round(rag_gate_hits / denominator, 4),
        "entity_case_accuracy": round(entity_hits / entity_total, 4) if entity_total else None,
        "entity_cases": entity_total,
        "latency_ms": {
            "mean": round(statistics.mean(latencies), 2) if latencies else 0.0,
            "p50": round(percentile(latencies, 0.50), 2),
            "p95": round(percentile(latencies, 0.95), 2),
        },
        "details": details,
    }


def run_retrieval_cases(base_url: str, cases: list[dict[str, Any]], top_k: int) -> dict[str, Any]:
    details = []
    hits = 0
    reciprocal_ranks = []

    for case in cases:
        params = urllib.parse.urlencode({"query": case["query"], "top_k": top_k})
        try:
            response = request_json(f"{base_url}/search?{params}", method="POST")
            titles = [str(item.get("title", "")) for item in response.get("results") or []]
            rank = next((idx + 1 for idx, title in enumerate(titles) if title == case["expected_title"]), None)
            hit = rank is not None
            hits += int(hit)
            reciprocal_ranks.append(1.0 / rank if rank else 0.0)
            details.append({
                "id": case["id"],
                "status": "ok",
                "expected_title": case["expected_title"],
                "returned_titles": titles,
                "rank": rank,
                "hit": hit,
            })
        except Exception as exc:
            reciprocal_ranks.append(0.0)
            details.append({"id": case["id"], "status": "error", "error": str(exc)})

    total = len(cases)
    return {
        "cases": total,
        f"hit_at_{top_k}": round(hits / total, 4) if total else 0.0,
        "mrr": round(statistics.mean(reciprocal_ranks), 4) if reciprocal_ranks else 0.0,
        "details": details,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Coordexa labeled acceptance benchmark")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--include-quality-eval", action="store_true")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    dataset = json.loads(args.cases.read_text(encoding="utf-8"))

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_name": dataset.get("dataset_name"),
        "scope": dataset.get("scope"),
        "chat": run_chat_cases(base_url, dataset.get("chat_cases") or []),
        "retrieval": run_retrieval_cases(base_url, dataset.get("retrieval_cases") or [], args.top_k),
    }

    if args.include_quality_eval:
        try:
            quality = request_json(f"{base_url}/eval/run", method="POST", payload={})
            judge_success = float((quality.get("avg_scores") or {}).get("judge_success_rate", 0.0))
            report["quality"] = {
                "metrics_valid_for_external_use": judge_success >= 0.95,
                "report": quality,
            }
        except Exception as exc:
            report["quality"] = {"metrics_valid_for_external_use": False, "error": str(exc)}

    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    print(serialized)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")

    return 0 if report["chat"]["request_success_rate"] == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
