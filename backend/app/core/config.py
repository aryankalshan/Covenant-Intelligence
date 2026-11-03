from pathlib import Path
import os
from dotenv import load_dotenv
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env", override=False)
DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{PROJECT_ROOT / 'covenant.db'}"
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", PROJECT_ROOT / "storage"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
MAX_PDF_PAGES = int(os.getenv("MAX_PDF_PAGES", "500"))
FRONTEND_PORT = int(os.getenv("FRONTEND_PORT", "5173"))


def parse_cors_allowed_origins(value: str | None, frontend_port: int) -> list[str]:
    if not 1 <= frontend_port <= 65535:
        raise ValueError("FRONTEND_PORT must be between 1 and 65535.")
    if value and value.strip():
        origins = [origin.strip().rstrip("/") for origin in value.split(",") if origin.strip()]
        if not origins:
            raise ValueError("CORS_ALLOWED_ORIGINS must contain at least one origin.")
    else:
        origins = [
            f"http://localhost:{frontend_port}",
            f"http://127.0.0.1:{frontend_port}",
        ]
    for origin in origins:
        parsed = urlsplit(origin)
        if origin == "*" or parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError("CORS origins must be explicit http(s) origins; wildcard and origin paths are not allowed.")
    return list(dict.fromkeys(origins))


def validate_cors_allowed_origins(origins: list[str], frontend_port: int) -> list[str]:
    if not origins:
        raise ValueError("At least one explicit CORS origin is required.")
    return parse_cors_allowed_origins(",".join(origins), frontend_port)


CORS_ALLOWED_ORIGINS = parse_cors_allowed_origins(os.getenv("CORS_ALLOWED_ORIGINS"), FRONTEND_PORT)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_TIMEOUT_SECONDS = float(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "45"))
OPENROUTER_MAX_RETRIES = int(os.getenv("OPENROUTER_MAX_RETRIES", "2"))
EXTRACTION_CHUNK_CHARS = int(os.getenv("EXTRACTION_CHUNK_CHARS", "12000"))
EXTRACTION_CHUNK_OVERLAP = int(os.getenv("EXTRACTION_CHUNK_OVERLAP", "1000"))
EXTRACTION_MAX_CHUNKS = int(os.getenv("EXTRACTION_MAX_CHUNKS", "120"))
DEV_WORKSPACE_ID = "00000000-0000-4000-8000-000000000001"
DEV_IDENTITIES = {
    "admin": {"id": "00000000-0000-4000-8000-000000000004", "name": "Demo Admin", "role": "admin"},
    "reviewer": {"id": "00000000-0000-4000-8000-000000000002", "name": "Demo Reviewer", "role": "reviewer"},
    "contributor": {"id": "00000000-0000-4000-8000-000000000003", "name": "Demo Contributor", "role": "contributor"},
    "treasurer": {"id": "00000000-0000-4000-8000-000000000003", "name": "Demo Contributor", "role": "contributor"},
    "read_only": {"id": "00000000-0000-4000-8000-000000000005", "name": "Demo Read Only", "role": "read_only"},
}
DEV_SEEDED_USERS = {
    "reviewer": "00000000-0000-4000-8000-000000000002",
    "contributor": "00000000-0000-4000-8000-000000000003",
    "admin": "00000000-0000-4000-8000-000000000004",
    "read_only": "00000000-0000-4000-8000-000000000005",
}
