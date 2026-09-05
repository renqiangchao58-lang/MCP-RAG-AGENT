from support_pilot.embeddings import HashEmbeddings
from support_pilot.knowledge import KnowledgeService


def test_hash_embeddings_are_deterministic_and_normalized():
    embeddings = HashEmbeddings(64)
    first = embeddings.embed_query("配送延迟补偿")
    second = embeddings.embed_query("配送延迟补偿")

    assert first == second
    assert len(first) == 64
    assert abs(sum(value * value for value in first) - 1.0) < 1e-9


def test_rebuild_and_retrieve_with_source(app_settings):
    knowledge = KnowledgeService(app_settings)
    try:
        result = knowledge.rebuild()
        citations = knowledge.retrieve("金卡客户配送延迟五天补偿多少？")
    finally:
        knowledge.close()

    assert result == {"documents": 4, "chunks": 4}
    assert citations[0].source == "售后补偿政策.md"
    assert citations[0].page == 1
    assert citations[0].chunk_id
    assert len(citations) <= 2


def test_hybrid_reranker_promotes_the_expected_refund_source(app_settings):
    knowledge = KnowledgeService(app_settings)
    try:
        knowledge.rebuild()
        citations = knowledge.retrieve("退款审核后多久到账？")
    finally:
        knowledge.close()

    assert citations[0].source == "售后补偿政策.md"
    assert all(item.score <= citations[0].score for item in citations[1:])


def test_upload_rejects_unsupported_extension(app_settings):
    knowledge = KnowledgeService(app_settings)
    try:
        try:
            knowledge.save_upload("malware.exe", b"no")
        except ValueError as exc:
            assert "仅支持" in str(exc)
        else:
            raise AssertionError("unsupported upload must fail")
    finally:
        knowledge.close()
