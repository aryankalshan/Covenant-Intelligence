import re
import unicodedata

from app.modules.agreements.models import DocumentPage


SECTION_NUMBER = re.compile(r"\b(?:section\s+)?(\d{1,2}\.\d{1,2}(?:\([A-Za-z0-9]+\))*)\b", re.I)
QUOTED_TERM = re.compile(r"[\"“]([A-Z][A-Za-z0-9&/ -]{1,80})[\"”]")
DEFINED_FINANCIAL_TERM = re.compile(
    r"\b((?:[A-Z][A-Za-z0-9&/-]*\s+){0,4}(?:Leverage Ratio|Coverage Ratio|EBITDA|Liquidity|Indebtedness))\b"
)
DEFINITION_VERB = re.compile(r"\b(means|shall mean|has the meaning(?: given)?|is defined as)\b", re.I)
SECTION_HEADING = re.compile(r"^\s*(?:section\s+)?\d{1,2}\.\d{1,2}(?:\([A-Za-z0-9]+\))*\b", re.I)


def normalize_contract_text(text: str) -> str:
    """Whitespace-only normalization for page text with PDF line wrapping."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


def verified_quote(quote: str | None, page_text: str) -> bool:
    return bool(quote) and normalize_contract_text(quote) in normalize_contract_text(page_text)


def identify_terms(source_wording: str, referenced_definitions: list[dict] | None) -> list[str]:
    terms = [item.get("term", "").strip() for item in referenced_definitions or [] if item.get("term")]
    terms.extend(QUOTED_TERM.findall(source_wording))
    terms.extend(DEFINED_FINANCIAL_TERM.findall(source_wording))
    result: list[str] = []
    seen: set[str] = set()
    for term in terms:
        normalized = re.sub(r"\s+", " ", term).strip(" .,:;")
        normalized = re.sub(r"^(?:the|a|an)\s+", "", normalized, flags=re.I)
        if normalized and normalized.casefold() not in seen:
            result.append(normalized)
            seen.add(normalized.casefold())
    return result


def find_definition(term: str, pages: list[DocumentPage]) -> dict | None:
    term_pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", re.I)
    for page in pages:
        lines = page.text.splitlines()
        for index, line in enumerate(lines):
            exact_term_line = normalize_contract_text(line).strip('"“”\' .,;:').casefold() == normalize_contract_text(term).casefold()
            definition_starts_next_line = exact_term_line and index + 1 < len(lines) and bool(DEFINITION_VERB.search(lines[index + 1]))
            if not term_pattern.search(line) or not (DEFINITION_VERB.search(line) or definition_starts_next_line):
                continue
            definition_lines = [line.strip()]
            for continuation in lines[index + 1:index + 9]:
                if not continuation.strip() or SECTION_HEADING.search(continuation) or DEFINITION_VERB.search(continuation):
                    if DEFINITION_VERB.search(continuation) and len(definition_lines) < 3:
                        definition_lines.append(continuation.strip())
                        continue
                    break
                definition_lines.append(continuation.strip())
                if continuation.rstrip().endswith((".", ";")):
                    break
            quote = "\n".join(part for part in definition_lines if part)
            if quote:
                return {"term": term, "definition_text": quote, "source_page": page.page_number, "source_section": None}
    return None


def find_section_target(reference_text: str, pages: list[DocumentPage]) -> dict | None:
    match = SECTION_NUMBER.search(reference_text)
    if not match:
        return None
    section = match.group(1)
    heading_pattern = re.compile(rf"(?im)^\s*(?:section\s+)?{re.escape(section)}\b[^\r\n]*")
    for page in pages:
        found = heading_pattern.search(page.text)
        if found:
            return {"target_description": found.group(0).strip(), "target_page": page.page_number}
    return None


def find_reference_source(reference_text: str, supplied_page: int | None, pages: list[DocumentPage], evidence: list[dict]) -> tuple[int | None, str | None]:
    page_map = {page.page_number: page for page in pages}
    if supplied_page in page_map and verified_quote(reference_text, page_map[supplied_page].text):
        return supplied_page, None
    for citation in evidence:
        page = page_map.get(citation.get("source_page"))
        if page and verified_quote(reference_text, page.text):
            return page.page_number, citation.get("source_section")
    for page in pages:
        if verified_quote(reference_text, page.text):
            return page.page_number, None
    return None, None


def resolve_contract_references(payload: dict, pages: list[DocumentPage]) -> tuple[dict, list[str]]:
    """Resolve only text actually found in the document; preserve unresolved items as uncertainty."""
    output = dict(payload)
    uncertainties = list(output.get("uncertainty_reasons") or [])
    evidence = list(output.get("supporting_evidence") or [])
    definitions = list(output.get("referenced_definitions") or [])
    for term in identify_terms(output.get("source_wording", ""), definitions):
        existing = next((item for item in definitions if str(item.get("term", "")).casefold() == term.casefold()), None)
        # Never trust a model's claimed text/page. Resolve from the stored source text.
        match = find_definition(term, pages)
        if match:
            if existing:
                existing.update(match)
            else:
                definitions.append(match)
            if not any(
                item.get("quote") == match["definition_text"] and item.get("source_page") == match["source_page"]
                for item in evidence
            ):
                evidence.append({"quote": match["definition_text"], "source_page": match["source_page"], "source_section": None})
        elif existing:
            existing.update({"definition_text": None, "source_page": None, "source_section": None})
        else:
            definitions.append({"term": term, "definition_text": None, "source_page": None, "source_section": None})

    for definition in definitions:
        if definition.get("definition_text") is None or definition.get("source_page") is None:
            uncertainties.append(f"Definition for {definition.get('term', 'referenced term')} is unresolved.")

    resolved_refs: list[dict] = []
    for reference in output.get("cross_references") or []:
        item = dict(reference)
        source_page, source_section = find_reference_source(item.get("reference_text", ""), item.get("source_page"), pages, evidence)
        item["source_page"] = source_page
        item["source_section"] = source_section
        target = find_section_target(item.get("reference_text", ""), pages)
        item["target_description"] = target["target_description"] if target else None
        if source_page is None:
            uncertainties.append(f"Cross-reference source for {item.get('reference_text', 'unknown reference')} was not located.")
        if target:
            if not any(verified_quote(target["target_description"], ev.get("quote", "")) and ev.get("source_page") == target["target_page"] for ev in evidence):
                evidence.append({"quote": target["target_description"], "source_page": target["target_page"], "source_section": target["target_description"].split(" ", 1)[0]})
        else:
            uncertainties.append(f"Cross-reference target for {item.get('reference_text', 'unknown reference')} was not verified.")
        resolved_refs.append(item)

    output["referenced_definitions"] = definitions or None
    output["cross_references"] = resolved_refs or None
    output["supporting_evidence"] = evidence
    output["uncertainty_reasons"] = list(dict.fromkeys(uncertainties))
    return output, list(dict.fromkeys(uncertainties))
