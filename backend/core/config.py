import os

from dotenv import load_dotenv

load_dotenv()


def _normalize_database_url(value: str) -> str:
    if value.startswith("postgresql://") and "+psycopg" not in value:
        return value.replace("postgresql://", "postgresql+psycopg://", 1)
    return value


RAPT_USERNAME = os.getenv("RAPT_USERNAME", "")
RAPT_SECRET = os.getenv("RAPT_SECRET", "")
DATABASE_URL = _normalize_database_url(
    os.getenv("DATABASE_URL", "postgresql+psycopg://user:password@localhost/rapt_portal")
)
SYNC_INTERVAL_SECONDS = int(os.getenv("SYNC_INTERVAL_SECONDS", "60"))
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://host.docker.internal:11434/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "not-needed")
LLM_MODEL = os.getenv("LLM_MODEL", "local-model")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))
LLM_TOP_P = float(os.getenv("LLM_TOP_P", "0.9"))
LLM_EXTRA_BODY_JSON = os.getenv("LLM_EXTRA_BODY_JSON", "")
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "900"))
LLM_KEEP_ALIVE = os.getenv("LLM_KEEP_ALIVE", "")

TOKEN_URL = "https://id.rapt.io/connect/token"
API_BASE = "https://api.rapt.io"
