# Canonical Extraction JSON Schema

Version `1.1.0`. This is the canonical model output contract referenced by the API and extraction pipeline. Persist the schema version with every run/candidate. Breaking changes require a new major version; additive changes require a minor version. The current schema uses required nullable fields so absence is explicit: unavailable or unresolved information is `null`, never guessed or silently omitted.

Every obligation must include at least one supporting evidence item with a verbatim quote and source page. A quote must be checked against extracted page text. `source_section` may be `null` if no section heading can be established. Evidence presence and quote matching establish provenance only; they do not prove the interpretation is correct. Model confidence is intentionally not a correctness signal and must never be used as proof or approval criterion. Any uncertainty must be recorded and routed to human review.

The schema object is retained immutably as `canonical_payload` on both extraction candidates and approved revisions. Relational evidence records mirror each `supporting_evidence` entry in the same database transaction; evidence rows do not replace the complete JSON payload. Synthetic annotation and model-quality evaluation boundaries are documented in `docs/EVALUATION.md`.

## Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://covenant-intelligence.local/schemas/extraction-obligation-1.1.0.json",
  "title": "Covenant Intelligence Extraction Obligation",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "obligations"],
  "properties": {
    "schema_version": { "const": "1.1.0" },
    "obligations": {
      "type": "array",
      "items": { "$ref": "#/$defs/obligation" }
    }
  },
  "$defs": {
    "evidence": {
      "type": "object",
      "additionalProperties": false,
      "required": ["quote", "source_page", "source_section"],
      "properties": {
        "quote": { "type": "string", "minLength": 1 },
        "source_page": { "type": "integer", "minimum": 1 },
        "source_section": { "type": ["string", "null"] }
      }
    },
    "obligation": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "obligation_category", "obligation_description", "source_wording",
        "threshold_value", "comparison_operator", "threshold_unit",
        "measurement_basis", "testing_frequency", "testing_period",
        "reporting_deadline", "deadline_calculation_rule", "conditions",
        "exceptions", "referenced_definitions", "cross_references",
        "supporting_evidence", "uncertainty_reasons"
      ],
      "properties": {
        "obligation_category": {
          "type": "string",
          "enum": ["financial_covenant", "reporting_obligation", "affirmative_covenant", "negative_covenant"]
        },
        "obligation_description": { "type": "string", "minLength": 1 },
        "source_wording": { "type": "string", "minLength": 1 },
        "threshold_value": { "type": ["string", "number", "null"] },
        "comparison_operator": {
          "type": ["string", "null"],
          "enum": [">", ">=", "<", "<=", "=", "!=", null]
        },
        "threshold_unit": { "type": ["string", "null"] },
        "measurement_basis": { "type": ["string", "null"] },
        "testing_frequency": { "type": ["string", "null"] },
        "testing_period": { "type": ["string", "null"] },
        "reporting_deadline": { "type": ["string", "null"] },
        "deadline_calculation_rule": { "type": ["string", "null"] },
        "conditions": {
          "description": "Conditions explicitly found in source; null when unavailable.",
          "type": ["array", "null"],
          "items": { "type": "string" }
        },
        "exceptions": {
          "description": "Exceptions explicitly found in source; null when unavailable.",
          "type": ["array", "null"],
          "items": { "type": "string" }
        },
        "referenced_definitions": {
          "description": "Referenced term and located definition citation when resolved; null when none or unavailable.",
          "type": ["array", "null"],
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["term", "definition_text", "source_page", "source_section"],
            "properties": {
              "term": { "type": "string", "minLength": 1 },
              "definition_text": { "type": ["string", "null"] },
              "source_page": { "type": ["integer", "null"], "minimum": 1 },
              "source_section": { "type": ["string", "null"] }
            }
          }
        },
        "cross_references": {
          "description": "Explicit contractual cross-references and resolved target when available; null when none or unavailable.",
          "type": ["array", "null"],
          "items": {
            "type": "object",
            "additionalProperties": false,
            "required": ["reference_text", "target_description", "source_page", "source_section"],
            "properties": {
              "reference_text": { "type": "string", "minLength": 1 },
              "target_description": { "type": ["string", "null"] },
              "source_page": { "type": ["integer", "null"], "minimum": 1 },
              "source_section": { "type": ["string", "null"] }
            }
          }
        },
        "supporting_evidence": {
          "type": "array",
          "minItems": 1,
          "items": { "$ref": "#/$defs/evidence" }
        },
        "uncertainty_reasons": {
          "type": "array",
          "items": { "type": "string" }
        }
      }
    }
  }
}
```

## Interpretation and validation rules

- `source_wording` is verbatim text supporting the described obligation; do not paraphrase this field.
- Threshold fields are nullable and must not be inferred. Use a decimal string when possible to avoid binary floating point representation changes. A threshold may legitimately be null for reporting or negative covenants.
- Operators are populated only when the source expressly establishes the comparison. Do not normalize prose into an operator if ambiguous.
- Frequency, period, reporting deadline, and calculation rule preserve source meaning. Relative deadlines (for example, a number of days after a stated event) belong in `deadline_calculation_rule`; populate `reporting_deadline` only when a concrete deadline is available.
- `conditions`, `exceptions`, `referenced_definitions`, and `cross_references` use `null` when unavailable or not identified. Use an empty array only when the source has been examined and none apply.
- At the top-level Pydantic/API candidate wrapper, attach agreement version ID, extraction run ID, and validation findings. Those are system provenance fields rather than model-generated obligation content.
- Validate every evidence page against the version's page table and verify quote containment with documented normalization. Keep original quote and page text hash. A successful validation does not validate legal meaning.
- Route empty required prose, missing evidence, non-matching quotes, ambiguous definitions, unresolved operative references, and any non-empty `uncertainty_reasons` to review. Never auto-approve.
