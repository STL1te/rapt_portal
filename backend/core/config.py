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
    # JSON dict of provider-specific request params (e.g. {"enable_thinking": false}
    # for Qwen on DashScope); sent as extra_body, empty = nothing extra.
    extra_body: dict


_LLM_DEFAULTS = LLMConfig(
    base_url="http://host.docker.internal:11434/v1",
    api_key="not-needed",
    model="local-model",
    timeout=900.0,
    response_format="auto",
    sampling="default",
    extra_body={},
)


def _parse_extra_body(raw: str) -> dict:
    """JSON dict, or a quote-free `key=value,key=value` list — CasaOS strips quotes
    from env values, so the JSON form is untypeable there.
    ponytail: flat string values only; use the JSON form if a param needs a nested
    object or a non-string type."""
    if not raw:
        return {}
    if raw.lstrip().startswith("{"):
        return json.loads(raw)
    return dict(pair.split("=", 1) for pair in raw.split(",") if pair.strip())


def _llm(prefix: str, inherit: LLMConfig | None = None) -> LLMConfig:
    """Read {PREFIX}_LLM_* env vars, falling back to the shared legacy LLM_* ones.

    With `inherit`, the role extends another one instead: only {PREFIX}_LLM_* is read and
    anything unset comes from that config, so a role that overrides just the model keeps
    the endpoint, credentials and provider quirks of the role it extends. The legacy
    LLM_* names are skipped there — the inherited config already resolved them.
    """
    base = inherit or _LLM_DEFAULTS

    def get(name: str, default: str) -> str:
        value = os.getenv(f"{prefix}_LLM_{name}")
        if value is None and inherit is None:
            value = os.getenv(f"LLM_{name}")
        return (value or default).strip()

    response_format = get("RESPONSE_FORMAT", base.response_format).lower()
    if response_format not in {"auto", "json_schema", "json_object", "none"}:
        raise ValueError(
            f"{prefix}_LLM_RESPONSE_FORMAT must be one of: auto, json_schema, json_object, none"
        )
    sampling = get("SAMPLING", base.sampling).lower()
    if sampling not in {"default", "none"}:
        raise ValueError(f"{prefix}_LLM_SAMPLING must be one of: default, none")
    # Unset inherits; set-but-empty means "no extra params", which is the whole point of
    # a judge that must not be told reasoning_effort=none.
    raw_extra_body = os.getenv(f"{prefix}_LLM_EXTRA_BODY")
    if raw_extra_body is None and inherit is None:
        raw_extra_body = os.getenv("LLM_EXTRA_BODY")
    return LLMConfig(
        base_url=get("BASE_URL", base.base_url),
        api_key=get("API_KEY", base.api_key),
        model=get("MODEL", base.model),
        timeout=float(get("TIMEOUT_SECONDS", str(base.timeout))),
        response_format=response_format,
        sampling=sampling,
        extra_body=(
            base.extra_body if raw_extra_body is None else _parse_extra_body(raw_extra_body.strip())
        ),
    )


# Локальная дообученная модель — извлечение рецептов.
WIZARD_LLM = _llm("WIZARD")
# Облачная модель — AI-ассистент (чаты по варкам/ферментации/рецептам).
ASSISTANT_LLM = _llm("ASSISTANT")
# Судья семантической валидации рецептов. Наследует всё от WIZARD: по умолчанию это та же
# модель на том же эндпоинте, а VALIDATOR_LLM_* переопределяет ровно то, что нужно.
VALIDATOR_LLM = _llm("VALIDATOR", WIZARD_LLM)

# Зашиты в код: подбираются под модель, а не под окружение.
LLM_TEMPERATURE = 0.2
# Температура для реплик чата (после первой оценки) — выше, чтобы отвечать свободнее.
LLM_CHAT_TEMPERATURE = 0.5
LLM_TOP_P = 0.9

TOKEN_URL = "https://id.rapt.io/connect/token"
API_BASE = "https://api.rapt.io"
