from pathlib import Path
from unittest.mock import patch

from eval.run_eval import business_fact_accuracy, load_cases, refusal_passed, source_recall


DATASET = Path(__file__).resolve().parents[1] / "eval" / "trade_knowledge_eval.json"


def test_evaluation_dataset_has_40_unique_japanese_cases():
    cases = load_cases(DATASET)
    assert len(cases) == 40
    assert len({case["id"] for case in cases}) == 40
    assert {case["category"] for case in cases} == {"catalog", "business", "hybrid", "refusal"}


def test_source_recall_uses_file_names():
    assert source_recall(
        ["04_植物検疫_輸入検査手続き.pdf", "13_食品表示ラベル規定.docx"],
        ["/app/data_docs/04_植物検疫_輸入検査手続き.pdf"],
    ) == 0.5


def test_business_accuracy_requires_exact_structured_values():
    expected = [
        {"section": "stock", "match": {"product_code": "FRT-STR-001", "stock_qty": 16}},
        {"section": "shipments", "match": {"shipment_no": "RC-7004", "qty": 60}},
    ]
    matched, total, missing = business_fact_accuracy(
        expected,
        {
            "stock": [{"product_code": "FRT-STR-001", "stock_qty": 16}],
            "shipments": [{"shipment_no": "RC-7004", "qty": 50}],
        },
    )
    assert (matched, total) == (1, 2)
    assert missing == [expected[1]]


def test_refusal_requires_no_sources_or_business_rows():
    state = {
        "final_answer": "該当する業務データが見つかりませんでした。",
        "citations": [],
        "business_result": {"stock": [], "orders": [], "shipments": [], "alerts": []},
    }
    assert refusal_passed(state)
    state["citations"] = ["[Source: irrelevant.md]"]
    assert not refusal_passed(state)


def test_openai_compatible_client_uses_base_url_and_deepseek_key():
    from app.utils.llm import _build_client

    with patch.dict(
        "os.environ",
        {
            "LLM_PROVIDER": "openai",
            "OPENAI_BASE_URL": "https://api.deepseek.com/v1",
            "DEEPSEEK_API_KEY": "test-only-placeholder",
        },
        clear=True,
    ):
        client = _build_client()

    assert str(client.base_url) == "https://api.deepseek.com/v1/"
