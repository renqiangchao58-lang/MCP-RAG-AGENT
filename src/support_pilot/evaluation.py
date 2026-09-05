from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from support_pilot.config import Settings, get_settings
from support_pilot.knowledge import KnowledgeService
from support_pilot.model_gateway import ModelGateway
from support_pilot.schemas import EvaluationSummary


async def evaluate(settings: Settings | None = None) -> EvaluationSummary:
    runtime_settings = settings or get_settings()
    cases_path = Path("evaluations/cases.json")
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    knowledge = KnowledgeService(runtime_settings)
    model = ModelGateway(runtime_settings)
    details: list[dict[str, Any]] = []
    retrieval_total = retrieval_hits = 0
    retrieval_top1_hits = 0
    reciprocal_rank_total = 0.0
    citation_total = 0
    route_total = route_hits = 0
    try:
        knowledge.ensure_index()
        for case in cases:
            if case["kind"] == "retrieval":
                retrieval_total += 1
                citations = knowledge.retrieve(case["query"], runtime_settings.top_k)
                sources = [item.source for item in citations]
                expected_source = case["expected_source"]
                passed = expected_source in sources
                rank = sources.index(expected_source) + 1 if passed else None
                retrieval_hits += int(passed)
                retrieval_top1_hits += int(rank == 1)
                reciprocal_rank_total += 1 / rank if rank else 0
                citation_total += len(citations)
                details.append(
                    {
                        "id": case["id"],
                        "kind": "retrieval",
                        "passed": passed,
                        "expected": expected_source,
                        "rank": rank,
                        "sources": sources,
                        "scores": [item.score for item in citations],
                    }
                )
            else:
                route_total += 1
                decision = await model.route(case["query"], case.get("last_order_id"))
                passed = decision.route == case["expected_route"]
                route_hits += int(passed)
                details.append(
                    {
                        "id": case["id"],
                        "kind": "route",
                        "passed": passed,
                        "expected": case["expected_route"],
                        "actual": decision.route,
                    }
                )
    finally:
        knowledge.close()
    return EvaluationSummary(
        retrieval_hit_rate_at_k=retrieval_hits / retrieval_total if retrieval_total else 0,
        retrieval_top1_accuracy=(
            retrieval_top1_hits / retrieval_total if retrieval_total else 0
        ),
        mean_reciprocal_rank=(
            reciprocal_rank_total / retrieval_total if retrieval_total else 0
        ),
        average_citations=citation_total / retrieval_total if retrieval_total else 0,
        route_accuracy=route_hits / route_total if route_total else 0,
        total_cases=len(cases),
        details=details,
    )


def render_markdown(summary: EvaluationSummary) -> str:
    failed = [item for item in summary.details if not item["passed"]]
    lines = [
        "# SupportPilot 离线评估结果",
        "",
        "> 使用内置 Hash Embeddings 与确定性路由，可离线复现，不消耗模型 API。",
        "",
        "| 指标 | 结果 |",
        "|---|---:|",
        f"| Retrieval Hit@K | {summary.retrieval_hit_rate_at_k:.1%} |",
        f"| Retrieval Top-1 Accuracy | {summary.retrieval_top1_accuracy:.1%} |",
        f"| Mean Reciprocal Rank | {summary.mean_reciprocal_rank:.3f} |",
        f"| Average Citations | {summary.average_citations:.2f} |",
        f"| Route Accuracy | {summary.route_accuracy:.1%} |",
        f"| Total Cases | {summary.total_cases} |",
        "",
        "## 失败案例",
        "",
    ]
    if failed:
        lines.extend(
            f"- `{item['id']}`：期望 `{item['expected']}`，实际 "
            f"`{item.get('actual') or item.get('sources')}`"
            for item in failed
        )
    else:
        lines.append("无。")
    lines.extend(
        [
            "",
            "## 复现命令",
            "",
            "```powershell",
            ".\\.venv\\Scripts\\python.exe -m support_pilot.evaluation",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate SupportPilot retrieval and routing")
    parser.add_argument("--output", default=".data/evaluation.json")
    parser.add_argument("--markdown", default="evaluations/RESULTS.md")
    args = parser.parse_args()
    summary = asyncio.run(evaluate())
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(summary.model_dump_json(indent=2), encoding="utf-8")
    markdown = Path(args.markdown)
    markdown.parent.mkdir(parents=True, exist_ok=True)
    markdown.write_text(render_markdown(summary), encoding="utf-8")
    print(summary.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
