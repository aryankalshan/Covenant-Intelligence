# Synthetic evaluation dataset

19 manually authored synthetic cases. Borrowers, terms, thresholds, and clauses are fictional. Ground truth is stored in each `expected.json`, separate from the extraction implementation and source pages. No LLM generated the ground truth. Recreate only when the dataset directory is empty with `python -m app.scripts.create_eval_dataset`. The invalid PDF case intentionally contains corrupt bytes.
