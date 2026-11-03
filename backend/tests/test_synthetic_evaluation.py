import json
from pathlib import Path

from app.modules.extraction.schemas import CanonicalObligation
from scripts.evaluate_synthetic_dataset import DATASET, score


def test_synthetic_evaluation_fixture_is_schema_and_evidence_valid():
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    assert len(data["examples"]) >= 10
    report = score()
    assert report["fixture_integrity"]["passed"], report["fixture_integrity"]["errors"]
    assert report["gold_obligation_count"] >= 10
    assert report["llm_metrics"].startswith("not measured")
    for example in data["examples"]:
        for payload in example["expected_obligations"]:
            CanonicalObligation.model_validate(payload)
            assert payload["supporting_evidence"]
            assert all(ev["source_page"] == example["source_page"] and ev["quote"] in example["source_text"]
                       for ev in payload["supporting_evidence"])
