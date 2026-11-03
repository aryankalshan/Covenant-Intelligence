# Evaluation

The current synthetic evaluation protocol, dataset coverage, executed test results, live-provider outcome, and limitations are recorded in [TESTING_AND_EVALUATION.md](TESTING_AND_EVALUATION.md).

The gold set contains 19 synthetic cases and 20 synthetic PDFs. Expected canonical obligations and supporting citations are manually authored and kept separate from model output. Use `backend/scripts/create_eval_dataset.py` to recreate the fixtures and `backend/scripts/run_evaluation.py` to run the isolated evaluator.

Mock-provider results exercise application plumbing and workflow behavior only. They are never reported as model accuracy. Real LLM metrics require successful OpenRouter completions and remain null when no real predictions are returned.
