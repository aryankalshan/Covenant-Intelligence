import json
from pathlib import Path

import pymupdf

from app.modules.extraction.definitions import verified_quote
from app.modules.extraction.schemas import CanonicalObligation
from scripts.run_evaluation import score_predictions


DATASET = Path(__file__).resolve().parents[1] / "evaluation_dataset"


def test_synthetic_dataset_ground_truth_schema_and_pdf_evidence_are_valid():
    case_dirs = sorted(path for path in DATASET.iterdir() if path.is_dir())
    assert len(case_dirs) >= 15
    case_count = document_count = obligation_count = evidence_count = 0
    for directory in case_dirs:
        source = json.loads((directory / "source.json").read_text(encoding="utf-8"))
        expected = json.loads((directory / "expected.json").read_text(encoding="utf-8"))
        case_count += 1
        for filename, payloads in expected["expected_by_document"].items():
            document_count += 1
            source_pages = source["documents"][filename]["pages"]
            if source_pages is None:
                assert expected["expected_error"]["http_status"] == 422
                continue
            doc = pymupdf.open(directory / filename)
            for payload in payloads:
                CanonicalObligation.model_validate(payload)
                obligation_count += 1
                for evidence in payload["supporting_evidence"]:
                    evidence_count += 1
                    assert verified_quote(evidence["quote"], doc[evidence["source_page"] - 1].get_text("text"))
            doc.close()
    assert case_count == 19
    assert document_count == 20
    assert obligation_count >= 15
    assert evidence_count >= obligation_count


def test_evaluator_matches_duplicates_one_to_one_and_penalizes_extra_predictions():
    wording = "The Borrower shall maintain Liquidity of at least INR 8 crore at all times."
    gold = {"obligation_category":"financial_covenant", "obligation_description":"Minimum liquidity",
        "source_wording":wording, "threshold_value":"8", "comparison_operator":">=", "threshold_unit":"INR crore",
        "testing_frequency":"continuous", "reporting_deadline":None,
        "supporting_evidence":[{"quote":wording,"source_page":1,"source_section":"Section 4.1"}]}
    actual = [dict(gold), dict(gold)]
    result = score_predictions([gold], actual, {1:wording})
    assert result["matched_obligations"] == 1
    assert result["extra_or_duplicate_obligations"] == 1
    assert result["obligation_precision"] == 0.5
    assert result["obligation_recall"] == 1.0


def test_evaluator_counts_value_added_where_ground_truth_is_null_as_unsupported():
    wording = "The Borrower shall maintain the Required Liquidity Amount."
    gold = {"obligation_category":"financial_covenant", "obligation_description":"Minimum liquidity",
        "source_wording":wording, "threshold_value":None, "comparison_operator":None, "threshold_unit":None,
        "supporting_evidence":[{"quote":wording,"source_page":1,"source_section":"Section 4.1"}]}
    actual = dict(gold, threshold_value="5")
    result = score_predictions([gold], [actual], {1:wording})
    assert result["exact_threshold_accuracy"] == 0.0
    assert result["unsupported_or_fabricated_information_rate"] > 0

