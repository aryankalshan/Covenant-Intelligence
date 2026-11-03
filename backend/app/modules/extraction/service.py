import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import (
    EXTRACTION_CHUNK_CHARS,
    EXTRACTION_CHUNK_OVERLAP,
    EXTRACTION_MAX_CHUNKS,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_MAX_RETRIES,
    OPENROUTER_MODEL,
    OPENROUTER_TIMEOUT_SECONDS,
)
from app.modules.audit.service import record_audit
from app.modules.agreements.models import Agreement
from app.modules.agreements.models import AgreementVersion, DocumentPage
from app.modules.extraction.chunking import build_chunks, relevant_chunks
from app.modules.extraction.definitions import resolve_contract_references
from app.modules.extraction.models import ExtractionCandidate, ExtractionRun
from app.modules.extraction.persistence import save_candidate_with_evidence
from app.modules.extraction.prompts import PROMPT_VERSION, build_messages, response_json_schema
from app.modules.extraction.providers import LLMProvider, OpenRouterProvider, ProviderError
from app.modules.extraction.validation import validate_domain, validate_evidence, validate_schema_response

logger = logging.getLogger(__name__)


def openrouter_provider_factory() -> LLMProvider:
    return OpenRouterProvider(
        OPENROUTER_API_KEY,
        OPENROUTER_MODEL,
        OPENROUTER_BASE_URL,
        timeout_seconds=OPENROUTER_TIMEOUT_SECONDS,
        max_retries=OPENROUTER_MAX_RETRIES,
    )


def _dedupe_payloads(payloads: list[tuple[dict, list[dict]]]) -> list[tuple[dict, list[dict]]]:
    merged: dict[tuple[str, str], tuple[dict, list[dict]]] = {}
    for payload, findings in payloads:
        key = (
            payload.get("obligation_category", ""),
            re.sub(r"\s+", " ", payload.get("source_wording", "")).strip().casefold(),
        )
        if key not in merged:
            merged[key] = (payload, list(findings))
            continue
        prior, prior_findings = merged[key]
        prior = dict(prior)
        evidence = list(prior.get("supporting_evidence") or [])
        for item in payload.get("supporting_evidence") or []:
            if item not in evidence:
                evidence.append(item)
        prior["supporting_evidence"] = evidence
        uncertainty = list(prior.get("uncertainty_reasons") or [])
        for item in payload.get("uncertainty_reasons") or []:
            if item not in uncertainty:
                uncertainty.append(item)
        prior["uncertainty_reasons"] = uncertainty
        merged[key] = (prior, prior_findings + [item for item in findings if item not in prior_findings])
    return list(merged.values())


async def _execute_extraction(run_id: str, session_factory: sessionmaker, provider_factory: Callable[[], LLMProvider], *, max_chars: int, overlap_chars: int, max_chunks: int) -> None:
    db: Session = session_factory()
    run: ExtractionRun | None = None
    try:
        run = db.get(ExtractionRun, run_id)
        if run is None or run.status != "queued":
            return
        version = db.get(AgreementVersion, run.agreement_version_id)
        if version is None or version.status != "processed":
            run.status = "failed"
            run.error_code = "document_not_processed"
            run.error_summary = "Process the document version before extraction."
            run.completed_at = datetime.now(timezone.utc)
            db.commit()
            return
        pages = list(db.scalars(select(DocumentPage).where(
            DocumentPage.agreement_version_id == version.id,
        ).order_by(DocumentPage.page_number)))
        run.status = "running"
        run.started_at = datetime.now(timezone.utc)
        run.prompt_version = PROMPT_VERSION
        db.commit()

        all_chunks = build_chunks(pages, max_chars=max_chars, overlap_chars=overlap_chars)
        run.validation_findings = []
        if not all_chunks:
            run.chunk_count = 0
            run.screened_out_chunk_count = 0
            run.unprocessed_chunk_count = 0
            run.status = "failed"
            run.error_code = "no_extractable_text"
            run.error_summary = "No extractable page text is available for this document version."
            run.validation_findings.append({"code": "no_extractable_text", "message": run.error_summary})
            run.completed_at = datetime.now(timezone.utc)
            agreement = db.get(Agreement, version.agreement_id)
            record_audit(db, workspace_id=agreement.workspace_id, actor_user_id=run.requested_by,
                         action="extraction_failed", entity_type="extraction_run", entity_id=run.id,
                         summary={"status": run.status, "error_code": run.error_code,
                                  "error_summary": run.error_summary})
            db.commit()
            return
        selected = relevant_chunks(all_chunks, run.requested_categories)
        run.chunk_count = len(selected)
        run.screened_out_chunk_count = max(0, len(all_chunks) - len(selected))
        truncated = len(selected) > max_chunks
        if truncated:
            run.unprocessed_chunk_count = len(selected) - max_chunks
            selected = selected[:max_chunks]
            run.validation_findings.append({"code": "chunk_limit_reached", "message": f"Chunk limit reached; {run.unprocessed_chunk_count} additional relevant chunks were not processed. Extraction coverage is incomplete."})
        db.commit()

        provider = provider_factory() if selected else None
        accepted: list[tuple[dict, list[dict]]] = []
        provider_failures = 0
        provider_http_status: int | None = None
        malformed_responses = 0
        usage_input = 0
        usage_output = 0
        for chunk in selected:
            try:
                response = await provider.extract(build_messages(chunk.text, run.requested_categories), response_json_schema())
                run.provider = response.provider
                run.model = response.model
                usage_input += int(response.metadata.get("input_tokens") or 0)
                usage_output += int(response.metadata.get("output_tokens") or 0)
                run.provider_metadata = {
                    "input_tokens": usage_input,
                    "output_tokens": usage_output,
                    "chunks_with_response": run.processed_chunk_count + 1,
                    "mock": bool(response.metadata.get("mock")),
                }
                results, schema_findings = validate_schema_response(response.content)
                if schema_findings:
                    malformed_responses += 1
                    run.validation_findings.extend({**item, "chunk_index": chunk.index} for item in schema_findings)
                elif not results:
                    run.validation_findings.append({"code": "no_obligations_returned", "message": "The provider returned a valid empty obligation list for this chunk. This does not establish that the full agreement has no obligations; review coverage and source text.", "chunk_index": chunk.index})
                else:
                    for result in results or []:
                        enriched, resolution_uncertainties = resolve_contract_references(result, pages)
                        try:
                            from app.modules.extraction.schemas import CanonicalObligation
                            canonical = CanonicalObligation.model_validate(enriched)
                        except Exception:
                            run.validation_findings.append({"code": "post_resolution_schema_invalid", "chunk_index": chunk.index})
                            malformed_responses += 1
                            continue
                        evidence_findings = validate_evidence(enriched, {page.page_number: page for page in pages})
                        domain_findings = validate_domain(canonical)
                        candidate_findings = evidence_findings + domain_findings
                        if evidence_findings:
                            malformed_responses += 1
                            run.validation_findings.extend({**item, "chunk_index": chunk.index} for item in evidence_findings)
                            # Non-matching citations are never persisted as evidence-backed candidates.
                            continue
                        status = "needs_review" if candidate_findings or resolution_uncertainties else "awaiting_review"
                        accepted.append((canonical.model_dump(mode="json"), candidate_findings))
                run.processed_chunk_count += 1
                db.commit()
            except ProviderError as exc:
                provider_failures += 1
                run.error_code = exc.code
                run.error_summary = str(exc)[:500]
                provider_http_status = exc.status_code
                finding = {"code": exc.code, "message": run.error_summary, "chunk_index": chunk.index}
                if exc.status_code is not None:
                    finding["http_status"] = exc.status_code
                run.validation_findings.append(finding)
                run.processed_chunk_count += 1
                db.commit()
            except Exception as exc:
                provider_failures += 1
                logger.error("Extraction chunk failed run_id=%s chunk_index=%s error_type=%s", run.id, chunk.index, type(exc).__name__)
                run.validation_findings.append({"code": "chunk_processing_error", "message": "A document chunk could not be processed.", "chunk_index": chunk.index})
                run.processed_chunk_count += 1
                db.commit()

        page_by_number = {page.page_number: page for page in pages}
        for payload, prior_findings in _dedupe_payloads(accepted):
            schema_checked, schema_findings = validate_schema_response(json.dumps({"schema_version": "1.1.0", "obligations": [payload]}))
            if schema_findings or not schema_checked:
                run.validation_findings.extend(schema_findings or [{"code": "candidate_invalid_after_deduplication"}])
                continue
            from app.modules.extraction.schemas import CanonicalObligation
            canonical = CanonicalObligation.model_validate(schema_checked[0])
            domain_findings = validate_domain(canonical)
            evidence_findings = validate_evidence(schema_checked[0], page_by_number)
            findings = prior_findings + domain_findings
            if evidence_findings:
                malformed_responses += 1
                run.validation_findings.extend(evidence_findings)
                continue
            save_candidate_with_evidence(
                db,
                run.id,
                version,
                schema_checked[0],
                status="needs_review" if findings else "awaiting_review",
                validation_status="needs_review" if findings else "valid",
                validation_findings=findings,
            )
        run.candidate_count = db.scalar(select(func.count()).select_from(ExtractionCandidate).where(ExtractionCandidate.extraction_run_id == run.id)) or 0
        if provider_failures and run.processed_chunk_count < len(selected):
            run.status = "partial"
        elif provider_failures or malformed_responses or truncated:
            run.status = "partial"
        else:
            run.status = "succeeded"
        run.completed_at = datetime.now(timezone.utc)
        agreement = db.get(Agreement, version.agreement_id)
        record_audit(db, workspace_id=agreement.workspace_id, actor_user_id=run.requested_by,
                     action=f"extraction_{run.status}", entity_type="extraction_run", entity_id=run.id,
                     summary={"status": run.status, "count": run.candidate_count,
                              "error_code": run.error_code, "http_status": provider_http_status,
                              "error_summary": run.error_summary})
        db.commit()
    except ProviderError as exc:
        db.rollback()
        run = db.get(ExtractionRun, run_id)
        if run:
            run.status = "failed"
            run.error_code = exc.code
            run.error_summary = str(exc)[:500]
            run.completed_at = datetime.now(timezone.utc)
            version = db.get(AgreementVersion, run.agreement_version_id)
            agreement = db.get(Agreement, version.agreement_id) if version else None
            if agreement:
                record_audit(db, workspace_id=agreement.workspace_id, actor_user_id=run.requested_by,
                             action="extraction_failed", entity_type="extraction_run", entity_id=run.id,
                             summary={"status": "failed", "error_code": run.error_code,
                                      "http_status": exc.status_code, "error_summary": run.error_summary})
            db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("Extraction run failed run_id=%s error_type=%s", run_id, type(exc).__name__)
        run = db.get(ExtractionRun, run_id)
        if run:
            run.status = "failed"
            run.error_code = "extraction_internal_error"
            run.error_summary = "Extraction failed; retry the run or contact an administrator."
            run.completed_at = datetime.now(timezone.utc)
            version = db.get(AgreementVersion, run.agreement_version_id)
            agreement = db.get(Agreement, version.agreement_id) if version else None
            if agreement:
                record_audit(db, workspace_id=agreement.workspace_id, actor_user_id=run.requested_by,
                             action="extraction_failed", entity_type="extraction_run", entity_id=run.id,
                             summary={"status": "failed"})
            db.commit()
    finally:
        db.close()


def run_extraction_background(run_id: str, session_factory: sessionmaker, provider_factory: Callable[[], LLMProvider], *, max_chars: int = EXTRACTION_CHUNK_CHARS, overlap_chars: int = EXTRACTION_CHUNK_OVERLAP, max_chunks: int = EXTRACTION_MAX_CHUNKS) -> None:
    asyncio.run(_execute_extraction(run_id, session_factory, provider_factory, max_chars=max_chars, overlap_chars=overlap_chars, max_chunks=max_chunks))
