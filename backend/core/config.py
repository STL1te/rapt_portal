import json
import os
from dataclasses import dataclass

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


@dataclass
class LLMConfig:
    """One OpenAI-compatible endpoint. Configured per role, not globally."""

    base_url: str
    api_key: str
    model: str
    timeout: float
    response_format: str
    # none = режим reasoning-моделей OpenAI (gpt-5.x): не отправлять temperature/top_p
    # (принимают только дефолт, иначе 400) и слать max_completion_tokens вместо
    # устаревшего max_tokens.
    sampling: str
    # Optional stronger judge for recipe-wizard semantic validation; empty = model.
    validator_model: str | None
    # full = the whole instruction prompt, for a model that has never seen the task.
    # short = the one-line prompt the student was fine-tuned on (sft v5/v6): the rules
    # live in the weights, so resending them wastes ~8.6k chars and is off-distribution.
    # Must match the model actually configured - a v3 student needs `full`.
    prompt: str
    # JSON dict of provider-specific request params (e.g. {"enable_thinking": false}
    # for Qwen on DashScope); sent as extra_body, empty = nothing extra.
    extra_body: dict


def _llm(prefix: str) -> LLMConfig:
    """Read {PREFIX}_LLM_* env vars, falling back to the shared legacy LLM_* ones."""

    def get(name: str, default: str = "") -> str:
        return (os.getenv(f"{prefix}_LLM_{name}") or os.getenv(f"LLM_{name}") or default).strip()

    response_format = get("RESPONSE_FORMAT", "auto").lower()
    if response_format not in {"auto", "json_schema", "json_object", "none"}:
        raise ValueError(
            f"{prefix}_LLM_RESPONSE_FORMAT must be one of: auto, json_schema, json_object, none"
        )
    sampling = get("SAMPLING", "default").lower()
    if sampling not in {"default", "none"}:
        raise ValueError(f"{prefix}_LLM_SAMPLING must be one of: default, none")
    prompt = get("PROMPT", "full").lower()
    if prompt not in {"full", "short"}:
        raise ValueError(f"{prefix}_LLM_PROMPT must be one of: full, short")
    return LLMConfig(
        base_url=get("BASE_URL", "http://host.docker.internal:11434/v1"),
        api_key=get("API_KEY", "not-needed"),
        model=get("MODEL", "local-model"),
        timeout=float(get("TIMEOUT_SECONDS", "900")),
        response_format=response_format,
        sampling=sampling,
        validator_model=get("VALIDATOR_MODEL") or None,
        extra_body=json.loads(get("EXTRA_BODY") or "{}"),
        prompt=prompt,
    )


# Локальная дообученная модель — извлечение рецептов.
WIZARD_LLM = _llm("WIZARD")
# Облачная модель — AI-ассистент (чаты по варкам/ферментации/рецептам).
ASSISTANT_LLM = _llm("ASSISTANT")

# Зашиты в код: подбираются под модель, а не под окружение.
LLM_TEMPERATURE = 0.2
# Температура для реплик чата (после первой оценки) — выше, чтобы отвечать свободнее.
LLM_CHAT_TEMPERATURE = 0.5
LLM_TOP_P = 0.9

TOKEN_URL = "https://id.rapt.io/connect/token"
API_BASE = "https://api.rapt.io"
