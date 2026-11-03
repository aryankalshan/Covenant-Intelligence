from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SupportingEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quote: str = Field(min_length=1)
    source_page: int = Field(ge=1)
    source_section: str | None = Field(...)


class ReferencedDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    term: str = Field(min_length=1)
    definition_text: str | None = Field(...)
    source_page: int | None = Field(..., ge=1)
    source_section: str | None = Field(...)


class CrossReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference_text: str = Field(min_length=1)
    target_description: str | None = Field(...)
    source_page: int | None = Field(..., ge=1)
    source_section: str | None = Field(...)


class CanonicalObligation(BaseModel):
    """Canonical one-obligation payload matching EXTRACTION_SCHEMA.md $defs.obligation."""

    model_config = ConfigDict(extra="forbid")
    obligation_category: Literal["financial_covenant", "reporting_obligation", "affirmative_covenant", "negative_covenant"]
    obligation_description: str = Field(min_length=1)
    source_wording: str = Field(min_length=1)
    threshold_value: str | float | None = Field(...)
    comparison_operator: Literal[">", ">=", "<", "<=", "=", "!="] | None = Field(...)
    threshold_unit: str | None = Field(...)
    measurement_basis: str | None = Field(...)
    testing_frequency: str | None = Field(...)
    testing_period: str | None = Field(...)
    reporting_deadline: str | None = Field(...)
    deadline_calculation_rule: str | None = Field(...)
    conditions: list[str] | None = Field(...)
    exceptions: list[str] | None = Field(...)
    referenced_definitions: list[ReferencedDefinition] | None = Field(...)
    cross_references: list[CrossReference] | None = Field(...)
    supporting_evidence: list[SupportingEvidence] = Field(min_length=1)
    uncertainty_reasons: list[str]


class CanonicalExtractionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.1.0"]
    obligations: list[CanonicalObligation]


class ExtractionRunRequest(BaseModel):
    categories: list[Literal["financial_covenant", "reporting_obligation", "affirmative_covenant", "negative_covenant"]] = Field(
        default_factory=lambda: ["financial_covenant", "reporting_obligation", "affirmative_covenant", "negative_covenant"],
        min_length=1,
    )


class EvidenceOut(BaseModel):
    id: str
    agreement_version_id: str
    page_number: int
    quote: str
    source_section: str | None
    evidence_role: str


class ExtractionCandidateOut(BaseModel):
    id: str
    extraction_run_id: str
    status: str
    validation_status: str
    validation_findings: list[dict]
    canonical_payload: dict
    extraction_origin: Literal["openrouter", "provider", "mock_test", "synthetic_demo"] = "provider"
    evidence: list[EvidenceOut]


class ExtractionRunOut(BaseModel):
    id: str
    agreement_version_id: str
    status: str
    provider: str | None
    model: str | None
    prompt_version: str
    schema_version: str
    chunk_count: int
    unprocessed_chunk_count: int
    screened_out_chunk_count: int
    processed_chunk_count: int
    candidate_count: int
    validation_findings: list[dict]
    error_code: str | None
    error_summary: str | None
    created_at: str
    started_at: str | None
    completed_at: str | None
