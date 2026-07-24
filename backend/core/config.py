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
# Optional stronger judge for recipe-wizard semantic validation; empty = LLM_MODEL.
LLM_VALIDATOR_MODEL = os.getenv("LLM_VALIDATOR_MODEL", "").strip() or None
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "900"))
LLM_RESPONSE_FORMAT = os.getenv("LLM_RESPONSE_FORMAT", "auto").strip().lower()
if LLM_RESPONSE_FORMAT not in {"auto", "json_schema", "json_object", "none"}:
    raise ValueError("LLM_RESPONSE_FORMAT must be one of: auto, json_schema, json_object, none")
# none = режим reasoning-моделей OpenAI (gpt-5.x): не отправлять temperature/top_p
# (принимают только дефолт, иначе 400) и слать max_completion_tokens вместо
# устаревшего max_tokens.
LLM_SAMPLING = os.getenv("LLM_SAMPLING", "default").strip().lower()
if LLM_SAMPLING not in {"default", "none"}:
    raise ValueError("LLM_SAMPLING must be one of: default, none")

# Зашиты в код: подбираются под модель, а не под окружение.
LLM_TEMPERATURE = 0.2
# Температура для реплик чата (после первой оценки) — выше, чтобы отвечать свободнее.
LLM_CHAT_TEMPERATURE = 0.5
LLM_TOP_P = 0.9

TOKEN_URL = "https://id.rapt.io/connect/token"
API_BASE = "https://api.rapt.io"
