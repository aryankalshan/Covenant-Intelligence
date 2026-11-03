import json

from pydantic import ValidationError

from app.modules.agreements.models import DocumentPage
from app.modules.extraction.definitions import verified_quote
from app.modules.extraction.schemas import CanonicalExtractionBatch, CanonicalObligation


def validate_schema_response(content: str) -> tuple[list[dict] | None, list[dict]]:
    try:
        decoded = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None, [{"code": "invalid_json", "message": "Provider response was not valid JSON."}]
    try:
        batch = CanonicalExtractionBatch.model_validate(decoded)
    except ValidationError as exc:
        findings = [{
            "code": "schema_invalid",
            "field": ".".join(str(part) for part in error.get("loc", ())),
            "message": "Provider output did not satisfy the canonical extraction schema.",
        } for error in exc.errors()]
        return None, findings
    return [item.model_dump(mode="json") for item in batch.obligations], []


def validate_evidence(payload: dict, page_by_number: dict[int, DocumentPage]) -> list[dict]:
    findings: list[dict] = []
    for index, citation in enumerate(payload.get("supporting_evidence") or []):
        page_number = citation.get("source_page")
        page = page_by_number.get(page_number)
        if page is None:
            findings.append({"code": "evidence_page_missing", "field": f"supporting_evidence.{index}.source_page", "source_page": page_number})
            continue
        quote = citation.get("quote", "")
        if not verified_quote(quote, page.text):
            findings.append({"code": "evidence_quote_not_found", "field": f"supporting_evidence.{index}.quote", "source_page": page_number})
    return findings


def validate_domain(payload: CanonicalObligation) -> list[dict]:
    findings: list[dict] = []
    if payload.threshold_value is not None and payload.comparison_operator is None:
        findings.append({"code": "threshold_operator_missing", "field": "comparison_operator"})
    if payload.comparison_operator is not None and payload.threshold_value is None:
        findings.append({"code": "threshold_value_missing", "field": "threshold_value"})
    if payload.obligation_category == "financial_covenant" and payload.threshold_value is None:
        findings.append({"code": "financial_threshold_missing", "field": "threshold_value"})
    if payload.obligation_category == "reporting_obligation" and payload.reporting_deadline is None and payload.deadline_calculation_rule is None:
        findings.append({"code": "reporting_deadline_missing", "field": "reporting_deadline"})
    for index, definition in enumerate(payload.referenced_definitions or []):
        if definition.definition_text is None or definition.source_page is None:
            findings.append({"code": "definition_unresolved", "field": f"referenced_definitions.{index}"})
    for index, reference in enumerate(payload.cross_references or []):
        if reference.target_description is None:
            findings.append({"code": "cross_reference_unresolved", "field": f"cross_references.{index}"})
        if reference.source_page is None:
            findings.append({"code": "cross_reference_source_unresolved", "field": f"cross_references.{index}.source_page"})
    if payload.uncertainty_reasons:
        findings.append({"code": "uncertainty_present", "field": "uncertainty_reasons"})
    return findings
