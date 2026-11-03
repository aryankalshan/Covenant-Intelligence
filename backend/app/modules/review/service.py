from sqlalchemy import select
import re
from sqlalchemy.orm import Session

from app.modules.agreements.models import AgreementVersion, DocumentPage
from app.modules.extraction.definitions import find_section_target, normalize_contract_text, verified_quote
from app.modules.extraction.schemas import CanonicalObligation
from app.modules.extraction.validation import validate_domain, validate_evidence


def validate_approved_obligation(db: Session, version: AgreementVersion, payload: dict) -> tuple[CanonicalObligation, list[dict]]:
    canonical = CanonicalObligation.model_validate(payload)
    pages = list(db.scalars(select(DocumentPage).where(DocumentPage.agreement_version_id == version.id)))
    page_by_number = {page.page_number: page for page in pages}
    findings = validate_evidence(canonical.model_dump(mode="json"), page_by_number)
    findings.extend(validate_domain(canonical))
    if canonical.uncertainty_reasons:
        findings.append({"code": "unresolved_uncertainty", "field": "uncertainty_reasons"})
    cited_text = " ".join([canonical.source_wording] + [page_by_number[ev.source_page].text for ev in canonical.supporting_evidence if ev.source_page in page_by_number])
    if canonical.threshold_value is not None:
        digits = re.sub(r"\D", "", str(canonical.threshold_value))
        source_digits = re.sub(r"\D", "", cited_text)
        if digits and digits not in source_digits:
            findings.append({"code": "threshold_not_supported_by_evidence", "field": "threshold_value"})
    operator_patterns = {
        "<=": r"\b(?:not exceed|not permit.{0,60}to exceed|no more than|at most|maximum|less than or equal to)\b",
        ">=": r"\b(?:at least|not less than|minimum|greater than or equal to)\b",
        "<": r"\b(?:less than|below)\b",
        ">": r"\b(?:greater than|above|exceed)\b",
        "=": r"\b(?:equal to|equals|equal)\b",
        "!=": r"\b(?:not equal to|different from)\b",
    }
    if canonical.comparison_operator and not re.search(operator_patterns[canonical.comparison_operator], cited_text, re.I):
        findings.append({"code": "comparison_operator_not_supported_by_evidence", "field": "comparison_operator"})
    if canonical.reporting_deadline and not verified_quote(canonical.reporting_deadline, cited_text):
        findings.append({"code": "reporting_deadline_not_supported_by_evidence", "field": "reporting_deadline"})
    if canonical.deadline_calculation_rule and not verified_quote(canonical.deadline_calculation_rule, cited_text):
        findings.append({"code": "deadline_rule_not_supported_by_evidence", "field": "deadline_calculation_rule"})
    for key in ("conditions", "exceptions"):
        for index, phrase in enumerate(getattr(canonical, key) or []):
            if not verified_quote(phrase, cited_text):
                findings.append({"code": f"{key[:-1]}_not_supported_by_evidence", "field": f"{key}.{index}"})
    for index, definition in enumerate(canonical.referenced_definitions or []):
        page = page_by_number.get(definition.source_page)
        if not page or not definition.definition_text or not verified_quote(definition.definition_text, page.text):
            findings.append({"code": "definition_not_verified", "field": f"referenced_definitions.{index}"})
        elif normalize_contract_text(definition.term).casefold() not in normalize_contract_text(definition.definition_text).casefold():
            findings.append({"code": "definition_term_not_found", "field": f"referenced_definitions.{index}.term"})
    for index, reference in enumerate(canonical.cross_references or []):
        source = page_by_number.get(reference.source_page)
        target = find_section_target(reference.reference_text, pages)
        if not source or not verified_quote(reference.reference_text, source.text):
            findings.append({"code": "cross_reference_source_not_verified", "field": f"cross_references.{index}.source_page"})
        if not target or normalize_contract_text(reference.target_description or "").casefold() != normalize_contract_text(target["target_description"]).casefold():
            findings.append({"code": "cross_reference_target_not_verified", "field": f"cross_references.{index}.target_description"})
        elif not any(ev.source_page == target["target_page"] and verified_quote(target["target_description"], ev.quote) for ev in canonical.supporting_evidence):
            findings.append({"code": "cross_reference_target_evidence_missing", "field": f"cross_references.{index}"})
    if not any(verified_quote(canonical.source_wording, page_by_number.get(ev.source_page).text) for ev in canonical.supporting_evidence if page_by_number.get(ev.source_page)):
        findings.append({"code": "source_wording_not_supported", "field": "source_wording"})
    unique = {(item.get("code"), item.get("field")): item for item in findings}
    return canonical, list(unique.values())
