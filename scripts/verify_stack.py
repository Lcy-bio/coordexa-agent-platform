"""Verify a running Coordexa Docker stack without making an LLM request by default."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_SERVICES = {"backend", "chromadb", "frontend", "prometheus", "redis"}


def request_text(url: str, timeout: float = 15.0) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")
        return response.read().decode("utf-8")


def request_json(url: str) -> Any:
    return json.loads(request_text(url))


def compose_services() -> dict[str, dict[str, Any]]:
    completed = subprocess.run(
        ["docker", "compose", "ps", "--format", "json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    services: dict[str, dict[str, Any]] = {}
    for line in completed.stdout.splitlines():
        if line.strip():
            item = json.loads(line)
            services[item["Service"]] = item
    missing = REQUIRED_SERVICES - set(services)
    if missing:
        raise RuntimeError(f"缺少服务: {', '.join(sorted(missing))}")
    unhealthy = [
        name for name, item in services.items()
        if item.get("State") != "running" or item.get("Health") == "unhealthy"
    ]
    if unhealthy:
        raise RuntimeError(f"服务状态异常: {', '.join(sorted(unhealthy))}")
    return services


def prometheus_targets(url: str) -> list[str]:
    payload = request_json(f"{url}/api/v1/targets")
    targets = payload.get("data", {}).get("activeTargets", [])
    states = [f"{item.get('labels', {}).get('job', 'unknown')}:{item.get('health')}" for item in targets]
    if not states or any(not state.endswith(":up") for state in states):
        raise RuntimeError(f"抓取目标异常: {states}")
    return states


def run_check(name: str, operation: Callable[[], Any], results: list[dict[str, Any]]) -> None:
    try:
        detail = operation()
        results.append({"name": name, "passed": True, "detail": detail})
        print(f"[PASS] {name}: {detail}")
    except Exception as exc:
        results.append({"name": name, "passed": False, "detail": str(exc)})
        print(f"[FAIL] {name}: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a running Coordexa Docker stack")
    parser.add_argument("--frontend-url", default="http://localhost:8080")
    parser.add_argument("--backend-url", default="http://localhost:8200")
    parser.add_argument("--prometheus-url", default="http://localhost:9190")
    parser.add_argument("--run-tests", action="store_true", help="also run containerized pytest")
    parser.add_argument("--run-benchmark", action="store_true", help="also run the labeled live benchmark")
    args = parser.parse_args()

    frontend = args.frontend_url.rstrip("/")
    backend = args.backend_url.rstrip("/")
    prometheus = args.prometheus_url.rstrip("/")
    results: list[dict[str, Any]] = []

    run_check("Docker Compose 五服务", lambda: sorted(compose_services()), results)
    run_check("前端页面", lambda: "Coordexa" in request_text(frontend) or (_ for _ in ()).throw(RuntimeError("品牌标题缺失")), results)
    run_check("前端反向代理", lambda: request_json(f"{frontend}/api/health").get("status"), results)
    run_check("后端健康", lambda: request_json(f"{backend}/health").get("status"), results)
    run_check("OpenAPI 品牌", lambda: request_json(f"{backend}/openapi.json")["info"]["title"], results)
    run_check("Skills 加载", lambda: request_json(f"{backend}/skills").get("count"), results)
    run_check("知识库片段", lambda: request_json(f"{backend}/knowledge/stats").get("total_chunks"), results)
    run_check("Monitor 摘要", lambda: len(request_json(f"{backend}/monitor").get("agent_stats", {})), results)
    run_check("Prometheus 就绪", lambda: request_text(f"{prometheus}/-/ready").strip(), results)
    run_check("Prometheus 抓取目标", lambda: prometheus_targets(prometheus), results)

    if args.run_tests:
        run_check(
            "容器内单元测试",
            lambda: subprocess.run(
                ["docker", "compose", "--profile", "test", "run", "--rm", "--build", "tests"],
                cwd=ROOT,
                check=True,
            ).returncode,
            results,
        )

    if args.run_benchmark:
        output = ROOT / "evaluation" / "results" / "coordexa_latest_benchmark.json"
        run_check(
            "项目内在线验收集",
            lambda: subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "run_benchmark.py"),
                    "--base-url",
                    backend,
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                check=True,
            ).returncode,
            results,
        )

    failures = [result for result in results if not result["passed"]]
    print(f"\nSummary: {len(results) - len(failures)}/{len(results)} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
