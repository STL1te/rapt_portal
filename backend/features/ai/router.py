"""Local AI assessments backed by an OpenAI-compatible API."""

from typing import Literal

from fastapi import APIRouter, HTTPException
from openai import APIConnectionError, OpenAIError
from pydantic import BaseModel, Field

from core.config import LLM_MODEL
from core.db import SessionLocal

from .services import DEFAULT_QUESTIONS, assess, build_context

router = APIRouter()


class AssessmentRequest(BaseModel):
    kind: Literal["brew", "fermentation"]
    session_id: str = Field(min_length=1, max_length=128)
    question: str | None = Field(default=None, max_length=2000)
    history: list["ChatMessage"] = Field(default_factory=list, max_length=12)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


@router.post("/api/ai/assessments")
async def create_assessment(request: AssessmentRequest) -> dict:
    with SessionLocal() as db:
        try:
            context = build_context(db, request.kind, request.session_id, None)
        except LookupError as error:
            raise HTTPException(404, str(error)) from error

    try:
        answer = await assess(
            request.kind,
            request.session_id,
            context,
            request.question,
            [message.model_dump() for message in request.history],
        )
    except APIConnectionError as error:
        raise HTTPException(503, "LLM is unavailable") from error
    except OpenAIError as error:
        raise HTTPException(502, "LLM request failed") from error

    return {
        "answer": answer,
        "model": LLM_MODEL,
        "question": request.question or DEFAULT_QUESTIONS[request.kind],
    }
