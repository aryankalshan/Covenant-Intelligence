import asyncio
import json
from pathlib import Path

import httpx
import pymupdf as fitz
from sqlalchemy import select

from app.modules.agreements.models import AgreementVersion, DocumentPage
from app.modules.audit.models import AuditEvent
from app.modules.extraction.models import ExtractionCandidate, ExtractionRun
from app.modules.extraction.definitions import resolve_contract_references
from app.modules.extraction.definitions import verified_quote
from app.modules.extraction.chunking import build_chunks, relevant_chunks
from app.modules.extraction.providers import LLMResponse, MockLLMProvider, OpenRouterProvider, ProviderError
from app.modules.extraction.schemas import CanonicalObligation
from app.modules.extraction.validation import validate_domain, validate_evidence, validate_schema_response
from app.modules.obligations.models import Evidence


FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_credit_agreement.md"


def make_pdf(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_textbox(page.rect + (35, 35, -35, -35), text, fontsize=8, lineheight=1.35)
    content = document.tobytes()
    document.close()
    return content


def obligation(category, description, wording, *, threshold=None, operator=None, unit=None, frequency=None,
               period=None, deadline=None, rule=None, conditions=None, exceptions=None, definitions=None,
               refs=None, uncertainty=None, page=1):
    return {
        "obligation_category": category,
        "obligation_description": description,
        "source_wording": wording,
        "threshold_value": threshold,
        "comparison_operator": operator,
        "threshold_unit": unit,
        "measurement_basis": "As stated in the synthetic agreement" if category == "financial_covenant" else None,
        "testing_frequency": frequency,
        "testing_period": period,
        "reporting_deadline": deadline,
        "deadline_calculation_rule": rule,
        "conditions": conditions,
        "exceptions": exceptions,
        "referenced_definitions": definitions,
        "cross_references": refs,
        "supporting_evidence": [{"quote": wording, "source_page": page, "source_section": None}],
        "uncertainty_reasons": uncertainty or [],
    }


def model_batch(page_text: str) -> str:
    # All clauses are test-generated and quotes below are copied from this synthetic fixture.
    clauses = [
        obligation("financial_covenant", "Maximum Consolidated Leverage Ratio", "The Borrower shall not permit the Consolidated Leverage Ratio to exceed 3.50:1.00 as of each fiscal quarter end.", threshold="3.50", operator="<=", unit="ratio", frequency="quarterly", period="Each fiscal quarter end", definitions=[{"term":"Consolidated Leverage Ratio","definition_text":None,"source_page":None,"source_section":None}]),
        obligation("financial_covenant", "Minimum Interest Coverage Ratio", "The Borrower shall maintain an Interest Coverage Ratio of not less than 2.00:1.00 for each fiscal quarter.", threshold="2.00", operator=">=", unit="ratio", frequency="quarterly", period="Each fiscal quarter"),
        obligation("financial_covenant", "Minimum unrestricted cash", "The Borrower shall maintain unrestricted cash and cash equivalents of at least $25,000,000 at all times.", threshold="25000000", operator=">=", unit="USD", frequency="continuous", period="At all times"),
        obligation("reporting_obligation", "Quarterly financial statements and certificate", "Within 45 days after each fiscal quarter, the Borrower shall deliver quarterly financial statements and a compliance certificate.", frequency="quarterly", deadline=None, rule="Within 45 days after each fiscal quarter"),
        obligation("reporting_obligation", "Annual audited financial statements", "Within 90 days after each fiscal year, the Borrower shall deliver annual audited financial statements.", frequency="annually", rule="Within 90 days after each fiscal year"),
        obligation("negative_covenant", "Capital expenditure restriction", "The Borrower shall not make Capital Expenditures exceeding $10,000,000 in any fiscal year without the Agent's prior written consent.", threshold="10000000", operator="<=", unit="USD per fiscal year", period="Any fiscal year", conditions=["Without the Agent's prior written consent"]),
        obligation("negative_covenant", "Additional indebtedness restriction", "The Borrower shall not incur additional indebtedness, except Permitted Debt.", exceptions=["Permitted Debt"]),
        obligation("financial_covenant", "Consolidated Leverage Ratio calculation basis", "Consolidated Leverage Ratio means Consolidated Total Debt divided by Consolidated EBITDA, calculated under this Agreement.", definitions=[{"term":"Consolidated Leverage Ratio","definition_text":"Consolidated Leverage Ratio means Consolidated Total Debt divided by Consolidated EBITDA, calculated under this Agreement.","source_page":1,"source_section":None}]),
        obligation("negative_covenant", "Distribution restriction", "The Borrower shall not make distributions, except distributions funded from available cash and approved in writing by the Agent.", exceptions=["Distributions funded from available cash and approved in writing by the Agent"]),
        obligation("negative_covenant", "Asset sale restriction", "The Borrower shall not sell material assets except as permitted under Section 4.2.", refs=[{"reference_text":"Section 4.2","target_description":None,"source_page":None,"source_section":None}], exceptions=["As permitted under Section 4.2"]),
        obligation("financial_covenant", "Potentially conflicting leverage limit", "Conflicting language: the ratio limit is 3.50:1.00 in this clause, while the attached schedule says 3.25:1.00; the controlling limit is unclear.", uncertainty=["The operative leverage threshold conflicts with the attached schedule."]),
        obligation("financial_covenant", "Minimum Debt Service Coverage Ratio", "The Borrower shall maintain a Debt Service Coverage Ratio of at least 1.25:1.00 for each fiscal quarter.", threshold="1.25", operator=">=", unit="ratio", frequency="quarterly", period="Each fiscal quarter"),
    ]
    return json.dumps({"schema_version":"1.1.0", "obligations":clauses})


def upload_processed(client, headers):
    agreement = client.post("/api/v1/agreements", headers=headers, json={"name":"Synthetic Extraction Facility","counterparty":"Fictional Counterparty"})
    assert agreement.status_code == 201, agreement.text
    text = FIXTURE.read_text(encoding="utf-8")
    upload = client.post(f"/api/v1/agreements/{agreement.json()['id']}/versions", headers=headers, data={"version_label":"Test Fixture","source_kind":"synthetic"}, files={"file":("synthetic.pdf", make_pdf(text), "application/pdf")})
    assert upload.status_code == 201, upload.text
    version_id = upload.json()["id"]
    processed = client.post(f"/api/v1/versions/{version_id}/process", headers=headers)
    assert processed.status_code == 200, processed.text
    return agreement.json(), version_id


def test_pdf_to_mock_extraction_workflow_persists_candidates_and_evidence(client):
    headers = {"X-Dev-User":"contributor"}
    agreement, version_id = upload_processed(client, headers)
    db = client.app.state.session_factory()
    try:
        page = db.scalar(select(DocumentPage).where(DocumentPage.agreement_version_id == version_id))
        assert page and "3.50:1.00" in page.text
        provider = MockLLMProvider([model_batch(page.text)])
        client.app.state.provider_factory = lambda: provider
    finally:
        db.close()

    response = client.post(f"/api/v1/versions/{version_id}/extraction-runs", headers=headers, json={})
    assert response.status_code == 202, response.text
    run = client.get(f"/api/v1/extraction-runs/{response.json()['id']}", headers=headers).json()
    assert run["status"] == "succeeded", run
    assert run["candidate_count"] == 12
    candidates_response = client.get(f"/api/v1/extraction-runs/{run['id']}/candidates", headers=headers)
    assert candidates_response.status_code == 200
    candidates = candidates_response.json()
    assert len(candidates) == 12
    assert all(item["status"] in {"awaiting_review", "needs_review"} for item in candidates)
    assert any(item["status"] == "needs_review" for item in candidates)
    assert any(item["canonical_payload"]["uncertainty_reasons"] for item in candidates)
    assert any(any(ev["quote"] == "Consolidated Leverage Ratio means Consolidated Total Debt divided by Consolidated EBITDA, calculated under this Agreement." for ev in item["evidence"]) for item in candidates)
    assert any(ev["evidence_role"] == "definition" for item in candidates for ev in item["evidence"])
    assert any(ev["evidence_role"] == "cross_reference" for item in candidates for ev in item["evidence"])
    assert client.get(f"/api/v1/agreements/{agreement['id']}/obligations", headers=headers).json() == []
    db = client.app.state.session_factory()
    try:
        saved = list(db.scalars(select(ExtractionCandidate).where(ExtractionCandidate.extraction_run_id == run["id"])))
        assert len(saved) == 12
        for item in saved:
            relational = list(db.scalars(select(Evidence).where(Evidence.candidate_id == item.id)))
            expected = sorted(item.canonical_payload["supporting_evidence"], key=lambda x: (x["source_page"], x["quote"]))
            actual = sorted([{"quote": e.quote, "source_page": e.page_number, "source_section": e.source_section} for e in relational], key=lambda x: (x["source_page"], x["quote"]))
            assert actual == expected
    finally:
        db.close()


def test_schema_invalid_json_missing_fields_and_page_quote_validation():
    assert validate_schema_response("{")[1][0]["code"] == "invalid_json"
    assert validate_schema_response('{"schema_version":"1.1.0","obligations":[{}]}')[1]
    payload = obligation("reporting_obligation", "x", "not on page")
    assert validate_evidence(payload, {})[0]["code"] == "evidence_page_missing"
    class Page:
        text = "different source"
    assert validate_evidence(payload, {1: Page()})[0]["code"] == "evidence_quote_not_found"


def test_uncertainty_and_missing_financial_threshold_route_to_review():
    item = CanonicalObligation.model_validate(obligation("financial_covenant", "x", "source", uncertainty=["Ambiguous terms."]))
    codes = {finding["code"] for finding in validate_domain(item)}
    assert {"financial_threshold_missing", "uncertainty_present"} <= codes


def test_definition_and_section_reference_resolution_uses_only_present_contract_text():
    class Page:
        page_number = 3
        text = "The Consolidated Leverage Ratio applies under Section 4.2.\nConsolidated Leverage Ratio means Consolidated Total Debt divided by Consolidated EBITDA.\n4.2 Asset Dispositions"
    payload = obligation(
        "financial_covenant", "Leverage", "The Consolidated Leverage Ratio applies under Section 4.2.",
        definitions=[{"term":"Consolidated Leverage Ratio","definition_text":None,"source_page":None,"source_section":None}],
        refs=[{"reference_text":"Section 4.2","target_description":None,"source_page":None,"source_section":None}],
    )
    resolved, uncertainty = resolve_contract_references(payload, [Page()])
    assert resolved["referenced_definitions"][0]["source_page"] == 3
    assert resolved["cross_references"][0]["target_description"] == "4.2 Asset Dispositions"
    assert any(item["quote"].startswith("Consolidated Leverage Ratio means") for item in resolved["supporting_evidence"])
    assert uncertainty == []


def test_missing_definition_and_cross_reference_remain_explicitly_unresolved():
    class Page:
        page_number = 1
        text = "The Borrower shall maintain the Custom Coverage Metric under Section 9.9."
    payload = obligation("financial_covenant", "Metric", "The Custom Coverage Metric is required.", definitions=[{"term":"Custom Coverage Metric","definition_text":None,"source_page":None,"source_section":None}], refs=[{"reference_text":"Section 9.9","target_description":None,"source_page":None,"source_section":None}])
    resolved, uncertainty = resolve_contract_references(payload, [Page()])
    assert resolved["referenced_definitions"][0]["definition_text"] is None
    assert resolved["cross_references"][0]["target_description"] is None
    assert len(uncertainty) >= 2


def test_wrong_model_definition_is_replaced_by_verified_multiline_source_and_original_wording_preserved():
    class Page:
        def __init__(self, number, text): self.page_number, self.text = number, text
    pages = [
        Page(1, "A misleading model definition is not source text."),
        Page(4, "Consolidated Leverage Ratio\nmeans Consolidated Total Debt divided by\nConsolidated EBITDA for the relevant period."),
    ]
    wording = "The Consolidated Leverage Ratio must not exceed 3.50:1.00."
    payload = obligation("financial_covenant", "Leverage ratio", wording, threshold="3.50", operator="<=",
        definitions=[{"term":"Consolidated Leverage Ratio","definition_text":"Model invented definition text.","source_page":1,"source_section":None}])
    resolved, uncertainty = resolve_contract_references(payload, pages)
    definition = resolved["referenced_definitions"][0]
    assert definition["source_page"] == 4
    assert definition["definition_text"] == "Consolidated Leverage Ratio\nmeans Consolidated Total Debt divided by\nConsolidated EBITDA for the relevant period."
    assert resolved["source_wording"] == wording
    assert not any("Definition for Consolidated Leverage Ratio" in item for item in uncertainty)
    assert resolved["supporting_evidence"][-1]["source_page"] == 4


def test_cross_reference_source_page_and_target_evidence_stay_separate_and_model_target_is_verified():
    class Page:
        def __init__(self, number, text): self.page_number, self.text = number, text
    pages = [Page(1, "The Borrower shall not sell material assets except as permitted under Section 3.1."),
             Page(6, "3.1 Asset Dispositions")]
    wording = pages[0].text
    payload = obligation("negative_covenant", "Asset sale restriction", wording,
        refs=[{"reference_text":"Section 3.1","target_description":"Fake Section 8.8", "source_page":6,"source_section":None}])
    resolved, uncertainty = resolve_contract_references(payload, pages)
    reference = resolved["cross_references"][0]
    assert reference["source_page"] == 1
    assert reference["target_description"] == "3.1 Asset Dispositions"
    target_evidence = [item for item in resolved["supporting_evidence"] if item["quote"] == "3.1 Asset Dispositions"]
    assert target_evidence[0]["source_page"] == 6
    assert uncertainty == []


def test_missing_cross_reference_target_preserves_reference_and_routes_uncertainty():
    class Page:
        page_number = 2
        text = "The Borrower must comply with Section 9.9."
    payload = obligation("negative_covenant", "Restriction", Page.text,
        refs=[{"reference_text":"Section 9.9","target_description":"Model target not in agreement","source_page":2,"source_section":None}])
    resolved, uncertainty = resolve_contract_references(payload, [Page()])
    assert resolved["cross_references"][0]["reference_text"] == "Section 9.9"
    assert resolved["cross_references"][0]["source_page"] == 2
    assert resolved["cross_references"][0]["target_description"] is None
    assert any("target" in reason for reason in uncertainty)


def test_evidence_normalization_is_whitespace_only_and_chunk_selection_keeps_the_full_document():
    assert verified_quote("A\n  ratio", "A ratio")
    class Page:
        def __init__(self, number, text): self.page_number, self.text = number, text
    chunks = build_chunks([Page(1, "Opening text"), Page(2, "The Borrower shall not incur additional indebtedness."), Page(3, "Permitted Debt definition and exceptions.")], max_chars=500, overlap_chars=50)
    selected = relevant_chunks(chunks, ["negative_covenant"])
    assert selected and selected[0].page_numbers == [1, 2, 3]
    assert [chunk.index for chunk in selected] == [chunk.index for chunk in chunks]


def test_chunk_selection_does_not_drop_text_without_known_covenant_keywords():
    class Page:
        page_number = 1
        text = "The parties acknowledge their respective obligations under this instrument."
    chunks = build_chunks([Page()], max_chars=500, overlap_chars=50)
    assert len(chunks) == 1
    assert relevant_chunks(chunks, ["financial_covenant"]) == chunks


def test_blank_page_text_does_not_create_an_empty_model_chunk():
    class Page:
        page_number = 1
        text = "  \n  "
    assert build_chunks([Page()], max_chars=500, overlap_chars=50) == []


def test_provider_failure_is_recorded_and_candidates_remain_empty(client):
    headers = {"X-Dev-User":"contributor"}
    _, version_id = upload_processed(client, headers)
    client.app.state.provider_factory = lambda: MockLLMProvider([], provider_error=ProviderError(
        "provider_insufficient_credits",
        "OpenRouter reports insufficient credits (HTTP 402). Add credits or review account limits.",
        status_code=402,
    ))
    response = client.post(f"/api/v1/versions/{version_id}/extraction-runs", headers=headers, json={})
    assert response.status_code == 202
    result = client.get(f"/api/v1/extraction-runs/{response.json()['id']}", headers=headers).json()
    assert result["status"] == "partial"
    assert result["candidate_count"] == 0
    assert result["error_code"] == "provider_insufficient_credits"
    assert result["error_summary"] == "OpenRouter reports insufficient credits (HTTP 402). Add credits or review account limits."
    assert result["validation_findings"][0]["code"] == "provider_insufficient_credits"
    assert result["validation_findings"][0]["http_status"] == 402
    with client.app.state.session_factory() as db:
        event = db.scalar(select(AuditEvent).where(AuditEvent.entity_id == result["id"], AuditEvent.action == "extraction_partial"))
        assert event.summary["error_code"] == "provider_insufficient_credits"
        assert event.summary["http_status"] == 402
        assert "HTTP 402" in event.summary["error_summary"]


def test_invalid_evidence_page_is_not_persisted_and_marks_run_partial(client):
    headers = {"X-Dev-User":"contributor"}
    agreement = client.post("/api/v1/agreements", headers=headers, json={"name":"Synthetic Invalid Quote"}).json()
    text = "Within 45 days after each fiscal quarter, the Borrower shall deliver quarterly financial statements."
    upload = client.post(f"/api/v1/agreements/{agreement['id']}/versions", headers=headers, data={"version_label":"Original","source_kind":"synthetic"}, files={"file":("test.pdf",make_pdf(text),"application/pdf")})
    version_id = upload.json()["id"]
    client.post(f"/api/v1/versions/{version_id}/process", headers=headers)
    candidate = obligation("reporting_obligation", "Quarterly statements", text, rule="Within 45 days", page=9)
    client.app.state.provider_factory = lambda: MockLLMProvider([json.dumps({"schema_version":"1.1.0","obligations":[candidate]})])
    created = client.post(f"/api/v1/versions/{version_id}/extraction-runs", headers=headers, json={}).json()
    result = client.get(f"/api/v1/extraction-runs/{created['id']}", headers=headers).json()
    assert result["status"] == "partial"
    assert result["candidate_count"] == 0
    assert any(finding["code"] == "evidence_page_missing" for finding in result["validation_findings"])


def test_valid_empty_structured_result_is_not_misclassified_as_malformed(client):
    headers = {"X-Dev-User":"contributor"}
    _, version_id = upload_processed(client, headers)
    client.app.state.provider_factory = lambda: MockLLMProvider(['{"schema_version":"1.1.0","obligations":[]}'])
    created = client.post(f"/api/v1/versions/{version_id}/extraction-runs", headers=headers, json={}).json()
    result = client.get(f"/api/v1/extraction-runs/{created['id']}", headers=headers).json()
    assert result["status"] == "succeeded"
    assert result["candidate_count"] == 0
    assert any(finding["code"] == "no_obligations_returned" for finding in result["validation_findings"])


def test_affirmative_covenant_category_is_in_schema_and_retrieval():
    text = "Section 5.4 Insurance. The Borrower shall maintain insurance with reputable insurers."
    payload = obligation("affirmative_covenant", "Maintain insurance", text)
    parsed, findings = validate_schema_response(json.dumps({"schema_version": "1.1.0", "obligations": [payload]}))
    assert findings == []
    assert parsed[0]["obligation_category"] == "affirmative_covenant"
    class Page:
        page_number = 1
        text = "Section 5.4 Insurance. The Borrower shall maintain insurance with reputable insurers."
    assert relevant_chunks(build_chunks([Page()], max_chars=500, overlap_chars=50), ["affirmative_covenant"])


def test_openrouter_retries_transient_http_status_and_sends_json_schema():
    calls = []
    async def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after":"0"}, json={"secret":"not surfaced"})
        return httpx.Response(200, json={"model":"mock/model","choices":[{"message":{"content":"{}"},"finish_reason":"stop"}],"usage":{"prompt_tokens":3,"completion_tokens":2}})
    provider = OpenRouterProvider("test-key-not-real", "mock/model", "https://openrouter.ai/api/v1", max_retries=1, transport=httpx.MockTransport(handler))
    async def no_sleep(_): pass
    import app.modules.extraction.providers as provider_module
    original_sleep = provider_module.asyncio.sleep
    provider_module.asyncio.sleep = no_sleep
    try:
        result = asyncio.run(provider.extract([], {"type":"object"}))
    finally:
        provider_module.asyncio.sleep = original_sleep
    assert len(calls) == 2
    sent = json.loads(calls[0].content)
    assert sent["response_format"]["type"] == "json_schema"
    assert result.metadata["input_tokens"] == 3


def test_openrouter_402_exposes_clear_safe_insufficient_credit_error():
    async def handler(request):
        return httpx.Response(402, json={"error": {"message": "private provider details"}})
    provider = OpenRouterProvider("test-key-not-real", "mock/model", "https://openrouter.ai/api/v1", max_retries=0, transport=httpx.MockTransport(handler))
    try:
        asyncio.run(provider.extract([], {"type": "object"}))
        assert False, "expected ProviderError"
    except ProviderError as exc:
        assert exc.code == "provider_insufficient_credits"
        assert exc.status_code == 402
        assert "insufficient credits" in str(exc)
        assert "private provider details" not in str(exc)

