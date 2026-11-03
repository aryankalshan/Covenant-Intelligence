"""Run a tiny synthetic PDF through the public API and print actual responses."""
import json
import os
import sys
import tempfile
from pathlib import Path

import pymupdf
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
from app.modules.extraction.providers import MockLLMProvider
from app.main import create_app


def main():
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as working:
        root = Path(working)
        database_url = f"sqlite:///{root / 'demo.db'}"
        os.environ["DATABASE_URL"] = database_url
        command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), "head")
        app = create_app(database_url=database_url, storage_dir=root / "files")
        clause = "Synthetic sample facility agreement requires quarterly certificate within 40 days."
        app.state.provider_factory = lambda: MockLLMProvider([json.dumps({"schema_version":"1.0.0","obligations":[{
            "obligation_category":"reporting_obligation", "obligation_description":"Quarterly certificate delivery",
            "source_wording":clause, "threshold_value":None, "comparison_operator":None, "threshold_unit":None,
            "measurement_basis":None, "testing_frequency":"quarterly", "testing_period":None,
            "reporting_deadline":"Within 40 days", "deadline_calculation_rule":None, "conditions":None,
            "exceptions":None, "referenced_definitions":None, "cross_references":None,
            "supporting_evidence":[{"quote":clause,"source_page":1,"source_section":None}], "uncertainty_reasons":[]
        }]})])
        document = pymupdf.open()
        document.new_page().insert_text((72, 72), clause)
        pdf = document.tobytes()
        document.close()
        try:
            with TestClient(app) as client:
                headers = {"X-Dev-User": "contributor"}
                agreement = client.post("/api/v1/agreements", headers=headers, json={"name": "Synthetic Sample Facility", "counterparty": "Example Ltd"})
                print("POST /api/v1/agreements", json.dumps({"status": agreement.status_code, "body": agreement.json()}))
                version = client.post(
                    f"/api/v1/agreements/{agreement.json()['id']}/versions",
                    headers=headers,
                    data={"version_label": "Original", "source_kind": "synthetic"},
                    files={"file": ("sample.pdf", pdf, "application/pdf")},
                )
                print("POST /api/v1/agreements/{id}/versions", json.dumps({"status": version.status_code, "body": version.json()}))
                version_id = version.json()["id"]
                processed = client.post(f"/api/v1/versions/{version_id}/process", headers=headers)
                print("POST /api/v1/versions/{id}/process", json.dumps({"status": processed.status_code, "body": processed.json()}))
                page = client.get(f"/api/v1/versions/{version_id}/pages/1", headers=headers)
                print("GET /api/v1/versions/{id}/pages/1", json.dumps({"status": page.status_code, "body": page.json()}))
                run_created = client.post(f"/api/v1/versions/{version_id}/extraction-runs", headers=headers, json={})
                run_id = run_created.json()["id"]
                run = client.get(f"/api/v1/extraction-runs/{run_id}", headers=headers)
                print("POST /api/v1/versions/{id}/extraction-runs then GET run", json.dumps({"start_status":run_created.status_code,"body":run.json()}))
                candidates = client.get(f"/api/v1/extraction-runs/{run_id}/candidates", headers=headers)
                print("GET /api/v1/extraction-runs/{id}/candidates", json.dumps({"status":candidates.status_code,"body":candidates.json()}))
        finally:
            app.state.engine.dispose()


if __name__ == "__main__":
    main()
