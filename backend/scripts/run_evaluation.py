"""Run the synthetic evaluation corpus through isolated application instances.

`all` attempts real OpenRouter extraction first and stops real calls at the first
provider/configuration failure. It then runs clearly labelled mock pipeline checks.
Mock outputs are copied from manually curated ground truth and are never scored as
model accuracy. All temporary database/storage files are owned by TemporaryDirectory.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import tempfile
from difflib import SequenceMatcher
from decimal import Decimal, InvalidOperation
from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import pymupdf
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import OPENROUTER_API_KEY, OPENROUTER_MODEL
from app.db.session import build_session_factory
from app.main import create_app
from app.modules.agreements.models import AgreementVersion, DocumentPage
from app.modules.audit.models import AuditEvent
from app.modules.extraction.definitions import verified_quote
from app.modules.extraction.providers import MockLLMProvider
from app.modules.extraction.schemas import CanonicalObligation
from app.modules.extraction.validation import validate_evidence


DATASET = BACKEND / "evaluation_dataset"
RESULTS = BACKEND / "test_results"
HEADERS = {"X-Dev-User": "contributor"}
REVIEWER_HEADERS = {"X-Dev-User": "reviewer"}
CATEGORIES = ["financial_covenant", "reporting_obligation", "affirmative_covenant", "negative_covenant"]


def compact(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").casefold()).strip()


def semantic_equal(actual, expected) -> bool:
    if actual is None or expected is None:
        return actual is expected
    if isinstance(actual, (int, float)) or isinstance(expected, (int, float)):
        try:
            return Decimal(str(actual)) == Decimal(str(expected))
        except InvalidOperation:
            return str(actual) == str(expected)
    if isinstance(actual, list) and isinstance(expected, list):
        return sorted(compact(str(x)) for x in actual) == sorted(compact(str(x)) for x in expected)
    if isinstance(actual, dict) and isinstance(expected, dict):
        return actual == expected
    left, right = compact(str(actual)), compact(str(expected))
    if left == right:
        return True
    # Description/deadline wording can vary while conveying the same phrase.
    return SequenceMatcher(None, left, right).ratio() >= 0.90


def match_pairs(expected: list[dict], actual: list[dict]) -> tuple[list[tuple[int, int]], set[int], set[int]]:
    scored = []
    for ei, gold in enumerate(expected):
        for ai, prediction in enumerate(actual):
            reference = compact(gold.get("source_wording"))
            candidates = [compact(prediction.get("source_wording"))]
            candidates.extend(compact(ev.get("quote")) for ev in prediction.get("supporting_evidence") or [])
            score = max((SequenceMatcher(None, reference, candidate).ratio() for candidate in candidates if candidate), default=0)
            if reference and (reference in candidates or score >= 0.50):
                scored.append((score, ei, ai))
    pairs: list[tuple[int, int]] = []
    used_e: set[int] = set(); used_a: set[int] = set()
    for _, ei, ai in sorted(scored, reverse=True):
        if ei not in used_e and ai not in used_a:
            pairs.append((ei, ai)); used_e.add(ei); used_a.add(ai)
    return pairs, set(range(len(expected))) - used_e, set(range(len(actual))) - used_a


def score_predictions(expected: list[dict], actual: list[dict], pdf_pages: dict[int, str]) -> dict:
    pairs, missing, extra = match_pairs(expected, actual)
    tp, fp, fn = len(pairs), len(extra), len(missing)
    precision = tp / (tp + fp) if tp + fp else (1.0 if fn == 0 else 0.0)
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    checks = {key: [] for key in (
        "covenant_type", "obligation_description", "source_wording", "threshold_value", "comparison_operator", "threshold_unit",
        "testing_frequency", "testing_period", "reporting_deadline", "deadline_calculation_rule",
        "conditions", "exceptions", "referenced_definitions", "cross_references",
    )}
    evidence_count = evidence_valid = page_valid = 0
    unsupported_claims = claims = 0
    ambiguity_cases = ambiguity_correct = 0
    detail_pairs = []
    claim_fields = list(checks)
    for ei, ai in pairs:
        gold, pred = expected[ei], actual[ai]
        field_results = {}
        for key in checks:
            ok = semantic_equal(pred.get(key), gold.get(key))
            checks[key].append(ok); field_results[key] = ok
        evidence = pred.get("supporting_evidence") or []
        expected_evidence = gold.get("supporting_evidence") or []
        expected_pages = {item.get("source_page") for item in expected_evidence}
        for item in evidence:
            evidence_count += 1
            page_text = pdf_pages.get(item.get("source_page"), "")
            valid_quote = verified_quote(item.get("quote", ""), page_text)
            quote_relevant = any(
                SequenceMatcher(None, compact(reference.get("quote")), compact(item.get("quote"))).ratio() >= 0.50
                for reference in expected_evidence
            )
            if valid_quote and quote_relevant:
                evidence_valid += 1
            if valid_quote and item.get("source_page") in expected_pages and quote_relevant:
                page_valid += 1
        for key in claim_fields:
            value = pred.get(key)
            values = value if isinstance(value, list) else ([value] if value is not None else [])
            for _ in values:
                claims += 1
                if gold.get(key) is None or not semantic_equal(pred.get(key), gold.get(key)):
                    unsupported_claims += 1
        if gold.get("uncertainty_reasons"):
            ambiguity_cases += 1
            if pred.get("uncertainty_reasons") or pred.get("validation_findings"):
                ambiguity_correct += 1
        detail_pairs.append({"expected_index": ei, "actual_index": ai, "field_checks": field_results})
    # Unmatched model outputs are extra obligations; count each as unsupported.
    unsupported_claims += fp
    claims += fp
    metric = lambda values: sum(values) / len(values) if values else None
    return {
        "obligation_precision": precision,
        "obligation_recall": recall,
        "obligation_f1": f1,
        "exact_threshold_accuracy": metric(checks["threshold_value"]),
        "comparison_operator_accuracy": metric(checks["comparison_operator"]),
        "threshold_unit_accuracy": metric(checks["threshold_unit"]),
        "covenant_type_accuracy": metric(checks["covenant_type"]),
        "obligation_description_accuracy": metric(checks["obligation_description"]),
        "source_wording_accuracy": metric(checks["source_wording"]),
        "reporting_frequency_accuracy": metric(checks["testing_frequency"]),
        "testing_period_accuracy": metric(checks["testing_period"]),
        "deadline_accuracy": metric(checks["reporting_deadline"]),
        "deadline_rule_accuracy": metric(checks["deadline_calculation_rule"]),
        "conditions_accuracy": metric(checks["conditions"]),
        "exceptions_accuracy": metric(checks["exceptions"]),
        "definitions_accuracy": metric(checks["referenced_definitions"]),
        "cross_references_accuracy": metric(checks["cross_references"]),
        "evidence_quotation_accuracy": evidence_valid / evidence_count if evidence_count else None,
        "page_citation_accuracy": page_valid / evidence_count if evidence_count else None,
        "unsupported_or_fabricated_information_rate": unsupported_claims / claims if claims else 0.0,
        "correct_ambiguity_escalation_rate": ambiguity_correct / ambiguity_cases if ambiguity_cases else None,
        "evidence_quote_count": evidence_count,
        "verified_evidence_quote_count": evidence_valid,
        "verified_page_citation_count": page_valid,
        "populated_claim_count": claims,
        "unsupported_claim_count": unsupported_claims,
        "ambiguity_case_count": ambiguity_cases,
        "correctly_escalated_ambiguity_count": ambiguity_correct,
        "matched_obligations": tp,
        "missed_obligations": fn,
        "extra_or_duplicate_obligations": fp,
        "field_pair_details": detail_pairs,
    }


def dataset_cases():
    return [
        (directory, json.loads((directory / "source.json").read_text(encoding="utf-8")),
         json.loads((directory / "expected.json").read_text(encoding="utf-8")))
        for directory in sorted(DATASET.iterdir()) if directory.is_dir()
    ]


def isolated_client(temp_path: Path, *, mock=False):
    database = temp_path / "evaluation.sqlite"
    url = f"sqlite:///{database.as_posix()}"
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        alembic_cfg = Config(str(BACKEND / "alembic.ini"))
        command.upgrade(alembic_cfg, "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
    app = create_app(database_url=url, storage_dir=temp_path / "storage")
    if mock:
        app.state.provider_factory = lambda: MockLLMProvider([])
    return app


def create_agreement(client: TestClient, case_id: str, title: str):
    response = client.post("/api/v1/agreements", headers=HEADERS, json={
        "name": f"[EVAL SYNTHETIC] {case_id} {title}", "counterparty": "Fictional Evaluation Borrower",
    })
    response.raise_for_status()
    return response.json()["id"]


def upload_process(client: TestClient, agreement_id: str, case_dir: Path, filename: str, label: str):
    pdf = (case_dir / filename).read_bytes()
    upload = client.post(f"/api/v1/agreements/{agreement_id}/versions", headers=HEADERS,
        data={"version_label": label, "source_kind": "synthetic"},
        files={"file": (filename, pdf, "application/pdf")})
    if upload.status_code != 201:
        return None, upload
    version = upload.json()
    processed = client.post(f"/api/v1/versions/{version['id']}/process", headers=HEADERS)
    processed.raise_for_status()
    return version, upload


def extract(client: TestClient, app, version_id: str, *, mock_payloads: list[dict] | None):
    if mock_payloads is not None:
        batch = json.dumps({"schema_version": "1.1.0", "obligations": mock_payloads}, ensure_ascii=False)
        app.state.provider_factory = lambda: MockLLMProvider([batch] * 200)
    started = client.post(f"/api/v1/versions/{version_id}/extraction-runs", headers=HEADERS, json={"categories": CATEGORIES})
    started.raise_for_status()
    run_id = started.json()["id"]
    run = client.get(f"/api/v1/extraction-runs/{run_id}", headers=HEADERS).json()
    candidates = client.get(f"/api/v1/extraction-runs/{run_id}/candidates", headers=HEADERS).json()
    return run, candidates


def candidate_integrity(app, version_id: str, candidates: list[dict]) -> dict:
    with app.state.session_factory() as db:
            pages = list(db.scalars(select(DocumentPage).where(DocumentPage.agreement_version_id == version_id).order_by(DocumentPage.page_number)))
            page_map = {page.page_number: page for page in pages}
            details = []
            for candidate in candidates:
                schema_valid = True
                try:
                    CanonicalObligation.model_validate(candidate["canonical_payload"])
                except Exception:
                    schema_valid = False
                findings = validate_evidence(candidate["canonical_payload"], page_map)
                nested = {(ev["quote"], ev["source_page"]) for ev in candidate["canonical_payload"].get("supporting_evidence") or []}
                relational = {(ev["quote"], ev["page_number"]) for ev in candidate.get("evidence", [])}
                details.append({
                    "candidate_id": candidate["id"], "schema_valid": schema_valid,
                    "evidence_valid": not findings, "evidence_findings": findings,
                    "relational_evidence_consistent": nested == relational,
                    "origin": candidate.get("extraction_origin"),
                    "status": candidate.get("status"),
                })
            return {"page_count": len(pages), "candidates": details,
                    "all_schemas_valid": all(x["schema_valid"] for x in details),
                    "all_evidence_valid": all(x["evidence_valid"] for x in details),
                    "all_relational_evidence_consistent": all(x["relational_evidence_consistent"] for x in details)}


def source_page_map(case_dir: Path, source_doc: dict, filename: str) -> dict[int, str]:
    if source_doc["documents"][filename]["pages"] is None:
        return {}
    doc = pymupdf.open(case_dir / filename)
    result = {i + 1: page.get_text("text") for i, page in enumerate(doc)}
    doc.close()
    return result


def run_mock_cases(cases) -> tuple[list[dict], dict]:
    results = []
    workflow = {"attempted": False, "checks": {}}
    with tempfile.TemporaryDirectory(prefix=".test-eval-mock-", dir=BACKEND) as temporary:
        app = isolated_client(Path(temporary), mock=True)
        app.state.database_url = f"sqlite:///{(Path(temporary) / 'evaluation.sqlite').as_posix()}"
        try:
            with TestClient(app) as client:
                for case_dir, source, expected in cases:
                    agreement_id = create_agreement(client, expected["case_id"], expected["title"])
                    document_results = {}
                    workflow_context = {}
                    workflow_candidates = {}
                    for filename, source_spec in source["documents"].items():
                        gold = expected["expected_by_document"].get(filename, [])
                        version, uploaded = upload_process(client, agreement_id, case_dir, filename, filename.removesuffix(".pdf"))
                        if version is None:
                            expected_error = expected.get("expected_error") or {}
                            document_results[filename] = {"upload_status": uploaded.status_code,
                                "upload_detail": uploaded.json().get("detail"),
                                "matches_expected_error": uploaded.status_code == expected_error.get("http_status")}
                            continue
                        run, candidates = extract(client, app, version["id"], mock_payloads=gold)
                        workflow_candidates[filename] = candidates
                        integrity = candidate_integrity(app, version["id"], candidates)
                        document_results[filename] = {
                            "upload_status": uploaded.status_code, "process_status": version["status"],
                            "run_status": run["status"], "provider": run.get("provider"), "model": run.get("model"),
                            "expected_candidate_count": len(gold), "actual_candidate_count": len(candidates),
                            "pipeline_integrity": integrity,
                        }
                        if filename == "original.pdf":
                            workflow_context["base_version"] = version
                            if expected["case_id"] == "TC14":
                                workflow_context["base_candidate"] = candidates[0] if candidates else None
                                workflow_context["base_run"] = run
                        elif filename == "amendment.pdf":
                            workflow_context["amendment_version"] = version
                            workflow_context["amendment_run"] = run
                        elif expected["case_id"] == "TC14":
                            workflow_context["base_version"] = version
                            workflow_context["base_candidate"] = candidates[0] if candidates else None
                            workflow_context["base_run"] = run
                    pipeline_pass = all(
                        detail.get("matches_expected_error", False) if "matches_expected_error" in detail else
                        detail["actual_candidate_count"] == detail["expected_candidate_count"] and
                        detail["provider"] == "mock" and detail["pipeline_integrity"]["all_schemas_valid"] and
                        detail["pipeline_integrity"]["all_evidence_valid"] and
                        detail["pipeline_integrity"]["all_relational_evidence_consistent"]
                        for detail in document_results.values()
                    )
                    if pipeline_pass and expected["case_id"] == "TC05":
                        workflow["attempted"] = True
                        candidate = workflow_candidates.get("agreement.pdf", [{}])[0]
                        rejection = client.post(f"/api/v1/candidates/{candidate['id']}/review-decisions",
                            headers=REVIEWER_HEADERS, json={"action":"rejected", "comment":"Synthetic evaluation confirms the negative debt restriction requires review."})
                        workflow["checks"]["candidate_rejection"] = rejection.status_code == 201 and rejection.json().get("decision") == "rejected"
                        register = client.get(f"/api/v1/agreements/{agreement_id}/obligations", headers=HEADERS)
                        workflow["checks"]["rejected_candidate_not_in_register"] = register.status_code == 200 and len(register.json()) == 0
                    if pipeline_pass and expected["case_id"] == "TC07":
                        workflow["attempted"] = True
                        candidate = workflow_candidates.get("agreement.pdf", [{}])[0]
                        corrected = dict(candidate["canonical_payload"])
                        corrected["obligation_description"] = "Distribution Restriction During an Event of Default"
                        decision = client.post(f"/api/v1/candidates/{candidate['id']}/review-decisions", headers=REVIEWER_HEADERS,
                            json={"action":"corrected", "comment":"Reviewer clarification of the clause heading.", "corrected_obligation":corrected})
                        workflow["checks"]["complete_object_correction"] = decision.status_code == 201 and bool(decision.json().get("revision_id"))
                        register = client.get(f"/api/v1/agreements/{agreement_id}/obligations", headers=HEADERS)
                        workflow["checks"]["corrected_revision_in_register"] = register.status_code == 200 and any(
                            row["canonical_payload"]["obligation_description"] == corrected["obligation_description"] for row in register.json())
                    if expected["case_id"] == "TC14" and pipeline_pass:
                        amendment_workflow = run_amendment_workflow(client, app, agreement_id, workflow_context)
                        workflow["attempted"] = True
                        workflow["checks"].update(amendment_workflow["checks"])
                    results.append({"case_id": expected["case_id"], "title": expected["title"],
                                    "expected_obligations_by_document": expected["expected_by_document"],
                                    "actual_llm_obligations_by_document": None,
                                    "mock_pipeline": {"status": "passed" if pipeline_pass else "failed",
                                        "candidate_outputs_are_ground_truth_test_doubles": True,
                                        "accuracy_metrics_computed": False, "documents": document_results}})
        finally:
            app.state.engine.dispose()
    if workflow["attempted"]:
        workflow["all_passed"] = all(workflow["checks"].values())
    return results, workflow


def run_amendment_workflow(client: TestClient, app, agreement_id: str, ctx: dict) -> dict:
    checks = {}
    base = ctx.get("base_version")
    base_candidate = ctx.get("base_candidate")
    amended = ctx.get("amendment_version")
    amendment_run = ctx.get("amendment_run")
    if not all([base, base_candidate, amended, amendment_run]):
        return {"attempted": True, "checks": {"setup": False}}
    approved = client.post(f"/api/v1/candidates/{base_candidate['id']}/review-decisions", headers=REVIEWER_HEADERS, json={"action":"approved"})
    checks["human_approval"] = approved.status_code == 201
    if not checks["human_approval"]:
        return {"attempted": True, "checks": checks, "failure": approved.json()}
    approved_data = approved.json()
    register = client.get(f"/api/v1/agreements/{agreement_id}/obligations", headers=HEADERS)
    checks["approved_register"] = register.status_code == 200 and len(register.json()) == 1
    period = client.post(f"/api/v1/obligations/{approved_data['obligation_id']}/monitoring-periods", headers=HEADERS, json={
        "period_label":"Synthetic 2026 Q1", "period_start":"2026-01-01", "period_end":"2026-03-31", "due_date":"2026-05-15"})
    checks["monitoring_period_created"] = period.status_code == 201
    if period.status_code == 201:
        update = client.post(f"/api/v1/monitoring-periods/{period.json()['id']}/updates", headers=HEADERS, json={"status":"submitted", "note":"Synthetic evaluation submission"})
        checks["monitoring_update"] = update.status_code == 201 and update.json()["status"] == "submitted"
    comparison = client.post(f"/api/v1/agreements/{agreement_id}/amendment-comparisons", headers=HEADERS, json={
        "base_version_id":base["id"], "amendment_version_id":amended["id"], "extraction_run_id":amendment_run["id"]})
    checks["comparison_created"] = comparison.status_code == 201
    if comparison.status_code == 201:
        item = next((item for item in comparison.json()["items"] if item["change_type"] == "changed"), None)
        changes = item["proposed_changes"] if item else {}
        checks["threshold_change_detected"] = changes.get("threshold_value") == {"previous":"3.50", "proposed":"4.00"}
        if item:
            decision = client.post(f"/api/v1/comparison-items/{item['id']}/decisions", headers=REVIEWER_HEADERS, json={"decision":"accepted", "comment":"Synthetic ground-truth comparison verification."})
            checks["amendment_review_accepted"] = decision.status_code == 201 and decision.json()["status"] == "accepted"
    events = client.get("/api/v1/audit-events", headers=HEADERS)
    actions = {event["action"] for event in events.json()} if events.status_code == 200 else set()
    checks["audit_events"] = all(action in actions for action in (
        "candidate_approved", "candidate_corrected", "candidate_rejected", "monitoring_period_created",
        "monitoring_updated", "amendment_comparison_created", "amendment_accepted"))
    return {"attempted": True, "checks": checks, "all_passed": all(checks.values())}


def run_real_cases(cases) -> tuple[list[dict], dict]:
    results = []
    summary = {"provider_configured": bool(OPENROUTER_API_KEY.strip() and OPENROUTER_MODEL.strip()),
               "model": OPENROUTER_MODEL or None, "cases_attempted": 0, "provider_blocked": None, "metrics": None}
    if not summary["provider_configured"]:
        summary["provider_blocked"] = "OpenRouter key or model is not configured; no external request was made."
        return results, summary
    with tempfile.TemporaryDirectory(prefix=".test-eval-real-", dir=BACKEND) as temporary:
        app = isolated_client(Path(temporary), mock=False)
        try:
            with TestClient(app) as client:
                for case_dir, source, expected in cases:
                    agreement_id = create_agreement(client, expected["case_id"], expected["title"])
                    document_results = {}
                    blocked = False
                    for filename in source["documents"]:
                        gold = expected["expected_by_document"].get(filename, [])
                        version, uploaded = upload_process(client, agreement_id, case_dir, filename, filename.removesuffix(".pdf"))
                        if version is None:
                            expected_error = expected.get("expected_error") or {}
                            document_results[filename] = {"upload_status": uploaded.status_code,
                                "upload_detail": uploaded.json().get("detail"),
                                "matches_expected_error": uploaded.status_code == expected_error.get("http_status")}
                            continue
                        run, candidates = extract(client, app, version["id"], mock_payloads=None)
                        summary["cases_attempted"] += 1
                        integrity = candidate_integrity(app, version["id"], candidates)
                        pages = source_page_map(case_dir, source, filename)
                        scored = None
                        if run.get("provider") == "openrouter":
                            scored = score_predictions(gold, [item["canonical_payload"] for item in candidates], pages)
                        document_results[filename] = {
                            "source_version_id": version["id"], "upload_status": uploaded.status_code,
                            "run_id": run["id"], "run_status": run["status"], "provider": run.get("provider"),
                            "model": run.get("model"), "error_code": run.get("error_code"),
                            "error_summary": run.get("error_summary"), "expected_obligations": gold,
                            "candidate_count": run.get("candidate_count"),
                            "validation_findings": run.get("validation_findings", []),
                            "actual_candidates": candidates if run.get("provider") == "openrouter" else None,
                            "candidate_integrity": integrity, "metrics": scored,
                        }
                        if run.get("error_code"):
                            summary["provider_blocked"] = {"case_id": expected["case_id"], "error_code": run["error_code"],
                                "error_summary": run.get("error_summary"), "http_status": next((finding.get("http_status") for finding in run.get("validation_findings", []) if finding.get("http_status")), None)}
                            blocked = True
                            break
                    results.append({"case_id": expected["case_id"], "title": expected["title"],
                        "expected_obligations_by_document": expected["expected_by_document"],
                        "documents": document_results})
                    if blocked:
                        for remaining_dir, _, remaining_expected in cases:
                            if remaining_expected["case_id"] == expected["case_id"]:
                                continue
                            if any(row["case_id"] == remaining_expected["case_id"] for row in results):
                                continue
                            results.append({"case_id": remaining_expected["case_id"], "title": remaining_expected["title"],
                                "expected_obligations_by_document": remaining_expected["expected_by_document"],
                                "documents": None, "status": "not_run_after_provider_error"})
                        break
            scored_rows = [doc["metrics"] for row in results for doc in (row.get("documents") or {}).values()
                           if isinstance(doc, dict) and doc.get("metrics") is not None]
            if scored_rows:
                tp = sum(item["matched_obligations"] for item in scored_rows)
                fp = sum(item["extra_or_duplicate_obligations"] for item in scored_rows)
                fn = sum(item["missed_obligations"] for item in scored_rows)
                precision = tp / (tp + fp) if tp + fp else (1.0 if fn == 0 else 0.0)
                recall = tp / (tp + fn) if tp + fn else 1.0
                aggregate = {"obligation_precision":precision,"obligation_recall":recall,
                    "obligation_f1":2*precision*recall/(precision+recall) if precision+recall else 0.0,
                    "matched_obligations":tp,"extra_or_duplicate_obligations":fp,"missed_obligations":fn}
                weighted_fields = ["exact_threshold_accuracy","comparison_operator_accuracy","threshold_unit_accuracy",
                    "covenant_type_accuracy","obligation_description_accuracy","source_wording_accuracy",
                    "reporting_frequency_accuracy","testing_period_accuracy","deadline_accuracy","deadline_rule_accuracy",
                    "conditions_accuracy","exceptions_accuracy","definitions_accuracy","cross_references_accuracy"]
                for name in weighted_fields:
                    values=[(item[name],item["matched_obligations"]) for item in scored_rows if item.get(name) is not None]
                    aggregate[name]=sum(value*weight for value,weight in values)/sum(weight for _,weight in values) if values and sum(weight for _,weight in values) else None
                for name,numerator,denominator in [
                    ("evidence_quotation_accuracy","verified_evidence_quote_count","evidence_quote_count"),
                    ("page_citation_accuracy","verified_page_citation_count","evidence_quote_count"),
                    ("unsupported_or_fabricated_information_rate","unsupported_claim_count","populated_claim_count"),
                    ("correct_ambiguity_escalation_rate","correctly_escalated_ambiguity_count","ambiguity_case_count")]:
                    top=sum(item[numerator] for item in scored_rows); bottom=sum(item[denominator] for item in scored_rows)
                    aggregate[name]=top/bottom if bottom else None
                summary["metrics"] = aggregate
        finally:
            app.state.engine.dispose()
    return results, summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["all", "mock", "real"], default="all")
    parser.add_argument("--overwrite", action="store_true", help="Replace only the previous generated JSON/CSV evaluation outputs.")
    args = parser.parse_args()
    cases = dataset_cases()
    if not cases:
        raise SystemExit(f"No evaluation dataset found under {DATASET}; run scripts/create_eval_dataset.py first.")
    RESULTS.mkdir(parents=True, exist_ok=True)
    json_path = RESULTS / "evaluation_results.json"
    csv_path = RESULTS / "evaluation_summary.csv"
    if not args.overwrite and (json_path.exists() or csv_path.exists()):
        raise SystemExit(f"Evaluation outputs already exist; pass --overwrite to replace {RESULTS} JSON/CSV outputs.")
    output = {
        "created_at_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "dataset_case_count": len(cases),
        "dataset_document_count": sum(len(source["documents"]) for _, source, _ in cases),
        "dataset_ground_truth_obligation_count": sum(len(items) for _, _, expected in cases for items in expected["expected_by_document"].values()),
        "matching_method": "One-to-one greedy maximum normalized source-wording similarity assignment; minimum similarity 0.50; duplicates can match at most one expected item.",
        "real_llm": {"attempted": False, "model": OPENROUTER_MODEL or None, "cases_attempted": 0, "metrics": None, "results": [],
                     "metric_note": "Metrics require successful real provider outputs. Mock and seeded results are not included."},
        "mock_pipeline": {"executed": False, "results": [], "accuracy_metrics": None,
                          "note": "Mock candidates are hand-authored expected payloads fed through the application pipeline to test schema, page evidence, persistence, review/monitoring/amendment/audit workflow only; this does not measure extraction correctness."},
        "mock_full_workflow": {"attempted": False, "checks": {}},
        "metrics_explanation": {
            "precision_recall_f1": "One-to-one matched obligations over predicted and expected obligations; unmatched duplicates count as false positives.",
            "threshold_accuracy": "Exact Decimal numeric threshold equality for matched obligations.",
            "type_operator_unit_frequency_deadline": "Field equality with numeric string/number normalization and normalized phrase comparison where applicable.",
            "evidence_quote_accuracy": "Predicted evidence quote must exist on its cited source PDF page and overlap the expected clause wording.",
            "page_citation_accuracy": "Evidence quote must be valid on a ground-truth cited page and match expected clause wording.",
            "unsupported_information_rate": "Populated structured claims that disagree with a non-null ground truth, appear where ground truth is null, or belong to unmatched extra obligations divided by populated claims.",
            "ambiguity_escalation": "Ambiguous expected obligations whose prediction retains uncertainty reasons or validation findings divided by ambiguous matched obligations."
        }
    }
    real_rows=[]
    if args.mode in {"all", "real"}:
        real_rows, real_summary = run_real_cases(cases)
        output["real_llm"].update({"attempted": real_summary["cases_attempted"] > 0,
            "cases_attempted": real_summary["cases_attempted"], "provider_blocked": real_summary["provider_blocked"],
            "metrics": real_summary["metrics"], "results": real_rows})
    mock_rows=[]
    if args.mode in {"all", "mock"}:
        mock_rows, workflow = run_mock_cases(cases)
        output["mock_pipeline"].update({"executed": True, "results": mock_rows})
        output["mock_full_workflow"] = workflow
    output["overall_real_metrics"] = output["real_llm"]["metrics"]
    json_path.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    real_by_id = {row["case_id"]: row for row in real_rows}
    mock_by_id = {row["case_id"]: row for row in mock_rows}
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["case_id", "title", "expected_obligations", "real_status", "real_error_code", "real_http_status", "real_candidates", "real_precision", "real_recall", "real_f1", "mock_pipeline_status", "mock_candidates", "mock_evidence_valid"])
        writer.writeheader()
        for _, _, expected in cases:
            case_id=expected["case_id"]; real=real_by_id.get(case_id, {}); mock=mock_by_id.get(case_id, {})
            docs=real.get("documents") if isinstance(real.get("documents"),dict) else {}
            first=next((x for x in docs.values() if isinstance(x,dict) and "run_status" in x),{})
            score=first.get("metrics") or {}
            mock_docs=mock.get("mock_pipeline",{}).get("documents",{})
            writer.writerow({"case_id":case_id,"title":expected["title"],
                "expected_obligations":sum(len(v) for v in expected["expected_by_document"].values()),
                "real_status":first.get("run_status") or real.get("status", "not_run"),
                "real_error_code":first.get("error_code") or "",
                "real_http_status":next((finding.get("http_status") for finding in first.get("validation_findings",[]) if finding.get("http_status")), "") if first else "",
                "real_candidates":first.get("candidate_count", "") if first else "",
                "real_precision":score.get("obligation_precision"),"real_recall":score.get("obligation_recall"),"real_f1":score.get("obligation_f1"),
                "mock_pipeline_status":mock.get("mock_pipeline",{}).get("status", "not_run"),
                "mock_candidates":sum(x.get("actual_candidate_count",0) for x in mock_docs.values()),
                "mock_evidence_valid":all(x.get("pipeline_integrity",{}).get("all_evidence_valid",True) for x in mock_docs.values())})
    print(json.dumps({"dataset_cases":output["dataset_case_count"],"documents":output["dataset_document_count"],
        "real_cases_attempted":output["real_llm"]["cases_attempted"],"real_provider_blocked":output["real_llm"].get("provider_blocked"),
        "real_metrics":output["real_llm"]["metrics"],
        "mock_pipeline_passed":sum(r["mock_pipeline"]["status"]=="passed" for r in mock_rows),
        "mock_pipeline_failed":sum(r["mock_pipeline"]["status"]=="failed" for r in mock_rows),
        "mock_workflow":workflow if args.mode in {"all","mock"} else None,
        "json_output":str(json_path),"csv_output":str(csv_path)},indent=2,ensure_ascii=False))


if __name__ == "__main__":
    main()
