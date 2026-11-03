"""Score optional extraction predictions against the synthetic gold set.

Without --predictions this validates fixture integrity only. It does not call a
model and never presents fixture checks as model accuracy.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))

from app.modules.extraction.schemas import CanonicalObligation


DATASET = ROOT / "tests" / "fixtures" / "synthetic_evaluation_dataset.json"
FIELDS = tuple(CanonicalObligation.model_fields)


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def expected_escalation(payload: dict) -> bool:
    unresolved_definitions = any(not d.get("definition_text") or not d.get("source_page")
                                 for d in payload.get("referenced_definitions") or [])
    unresolved_refs = any(not r.get("target_description") for r in payload.get("cross_references") or [])
    return bool(payload.get("uncertainty_reasons") or unresolved_definitions or unresolved_refs)


def score(predictions: dict[str, list[dict]] | None = None) -> dict:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    examples = dataset["examples"]
    integrity_errors: list[str] = []
    gold_count = 0
    for example in examples:
        for index, payload in enumerate(example["expected_obligations"]):
            gold_count += 1
            try:
                CanonicalObligation.model_validate(payload)
            except Exception as exc:  # surfaced as a fixture integrity finding
                integrity_errors.append(f"{example['id']} obligation {index}: schema invalid ({type(exc).__name__})")
                continue
            if any(ev["source_page"] != example["source_page"] or ev["quote"] not in example["source_text"]
                   for ev in payload["supporting_evidence"]):
                integrity_errors.append(f"{example['id']} obligation {index}: evidence does not match source excerpt")

    report: dict[str, Any] = {
        "dataset_id": dataset["dataset_id"],
        "synthetic_example_count": len(examples),
        "gold_obligation_count": gold_count,
        "fixture_integrity": {"passed": not integrity_errors, "error_count": len(integrity_errors), "errors": integrity_errors},
        "llm_metrics": "not measured: no real provider predictions were supplied",
    }
    if predictions is None:
        return report

    example_ids = {example["id"] for example in examples}
    fp = sum(len(values) for key, values in predictions.items() if key not in example_ids)
    tp = fn = 0
    field_matches = field_total = threshold_matches = threshold_total = 0
    deadline_matches = deadline_total = evidence_matches = evidence_total = 0
    definition_matches = definition_total = escalation_matches = escalation_total = 0
    for example in examples:
        gold = example["expected_obligations"]
        predicted = []
        for raw in predictions.get(example["id"], []):
            try:
                predicted.append(CanonicalObligation.model_validate(raw).model_dump(mode="json"))
            except Exception:
                predicted.append({"_invalid_schema": True, **raw} if isinstance(raw, dict) else {"_invalid_schema": True})
        remaining = list(predicted)
        for expected in gold:
            match = next((p for p in remaining if not p.get("_invalid_schema") and norm(p.get("obligation_description")) == norm(expected["obligation_description"])), None)
            if match is None:
                fn += 1
                field_total += sum(field not in {"supporting_evidence", "uncertainty_reasons"} for field in FIELDS)
                threshold_total += 1
                deadline_total += 1
                evidence_total += len(expected["supporting_evidence"])
                definition_total += len(expected.get("referenced_definitions") or [])
                escalation_total += 1
                continue
            tp += 1
            remaining.remove(match)
            for field in FIELDS:
                if field not in {"supporting_evidence", "uncertainty_reasons"}:
                    field_total += 1
                    field_matches += match.get(field) == expected.get(field)
            threshold_total += 1
            threshold_matches += all(match.get(k) == expected.get(k) for k in ("threshold_value", "comparison_operator", "threshold_unit", "measurement_basis"))
            deadline_total += 1
            deadline_matches += all(match.get(k) == expected.get(k) for k in ("reporting_deadline", "deadline_calculation_rule"))
            expected_evidence = expected["supporting_evidence"]
            evidence_total += len(expected_evidence)
            predicted_evidence = match.get("supporting_evidence") or []
            evidence_matches += sum(any(e.get("source_page") == gold_ev["source_page"] and norm(e.get("quote")) == norm(gold_ev["quote"])
                                        for e in predicted_evidence) for gold_ev in expected_evidence)
            expected_defs = expected.get("referenced_definitions") or []
            definition_total += len(expected_defs)
            predicted_defs = match.get("referenced_definitions") or []
            definition_matches += sum(any(norm(d.get("term")) == norm(gd.get("term")) and d.get("definition_text") == gd.get("definition_text") and d.get("source_page") == gd.get("source_page") for d in predicted_defs) for gd in expected_defs)
            escalation_total += 1
            escalation_matches += bool(match.get("uncertainty_reasons")) == expected_escalation(expected)
        fp += len(remaining)
    report["llm_metrics"] = {
        "covenant_detection_precision": tp / (tp + fp) if tp + fp else None,
        "covenant_detection_recall": tp / (tp + fn) if tp + fn else None,
        "field_level_accuracy": field_matches / field_total if field_total else None,
        "threshold_extraction_accuracy": threshold_matches / threshold_total if threshold_total else None,
        "reporting_deadline_accuracy": deadline_matches / deadline_total if deadline_total else None,
        "evidence_citation_accuracy": evidence_matches / evidence_total if evidence_total else None,
        "definition_resolution_accuracy": definition_matches / definition_total if definition_total else None,
        "human_escalation_accuracy": escalation_matches / escalation_total if escalation_total else None,
        "counts": {"true_positive": tp, "false_positive": fp, "false_negative": fn},
        "note": "Scores only the supplied predictions; this script does not call a provider or establish legal correctness.",
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, help="JSON object mapping SYN ids to arrays of canonical obligation objects")
    args = parser.parse_args()
    predictions = json.loads(args.predictions.read_text(encoding="utf-8")) if args.predictions else None
    print(json.dumps(score(predictions), indent=2))


if __name__ == "__main__":
    main()
