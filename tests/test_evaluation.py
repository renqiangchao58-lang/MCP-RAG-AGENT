import pytest

from support_pilot.evaluation import evaluate, render_markdown


@pytest.mark.asyncio
async def test_offline_evaluation_metrics_are_resume_ready(app_settings):
    summary = await evaluate(app_settings)

    assert summary.retrieval_hit_rate_at_k == 1.0
    assert summary.retrieval_top1_accuracy == 1.0
    assert summary.mean_reciprocal_rank == 1.0
    assert summary.average_citations <= app_settings.max_citations
    assert summary.route_accuracy == 1.0
    assert "Retrieval Top-1 Accuracy" in render_markdown(summary)
