# Live OpenRouter Evaluation

**Run date:** 2026-11-03  
**Outcome:** A synthetic agreement extraction request reached OpenRouter and received HTTP 402 (insufficient credits); no model completion was returned.

The evaluation used the configured `openai/gpt-6.1-terra` model through the OpenRouter-compatible backend adapter. The API key was loaded from the local `.env`, was not printed or saved in evaluation artifacts, and is not present in frontend code. The request contained synthetic agreement content only.

The evaluator attempted TC01, received `provider_insufficient_credits` (HTTP 402), and stopped further live cases. It produced zero candidates for that case. TC02–TC19 were not attempted against the live provider. A subsequent combined-run retry did not complete and was interrupted; it is separately noted in the results artifact and is not counted as a successful response.

| Measure | Result |
|---|---|
| Completed live extraction cases | 0 of 1 attempted |
| Provider result | HTTP 402, insufficient credits |
| Candidate obligations | 0 |
| Extraction precision, recall, and F1 | Not measured |
| Threshold, field, evidence, definition, and cross-reference accuracy | Not measured |
| Usage/cost | Not returned |

The response verifies that the configured request reached a provider error path; it does **not** verify successful authentication, model availability, structured-output compatibility, or extraction quality. No accuracy values are inferred from the error. Check account credits/limits before a future live run.

The deterministic mock-provider run is documented separately in [TESTING_AND_EVALUATION.md](TESTING_AND_EVALUATION.md). Its payloads are synthetic ground-truth test doubles, not live LLM outputs, and are excluded from accuracy metrics.

Machine-readable record: `backend/test_results/evaluation_results.json` and `backend/test_results/evaluation_summary.csv`.
