"""Server-owned AI conversations backed by an OpenAI-compatible API."""

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from openai import APIConnectionError, OpenAIError
from pydantic import BaseModel, Field

from .services import open_conversation, reset_conversation, send_conversation_message

logger = logging.getLogger(__name__)
router = APIRouter()


class OpenConversationRequest(BaseModel):
    subject_type: Literal["brew_session", "fermentation_session", "recipe"]
    subject_id: str = Field(min_length=1, max_length=128)


class ConversationMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


def _raise_ai_error(error: Exception) -> None:
    if isinstance(error, APIConnectionError):
        logger.warning("LLM unavailable: %s", error)
        raise HTTPException(503, "LLM is unavailable") from error
    if isinstance(error, OpenAIError):
        logger.exception("LLM request failed")
        raise HTTPException(502, "LLM request failed") from error
    raise error


@router.post("/api/ai/conversations/open")
async def open_conversation_endpoint(request: OpenConversationRequest) -> dict:
    try:
        return await open_conversation(request.subject_type, request.subject_id)
    except LookupError as error:
        raise HTTPException(404, "AI subject not found") from error
    except (APIConnectionError, OpenAIError) as error:
        _raise_ai_error(error)


@router.post("/api/ai/conversations/{conversation_id}/messages")
async def create_conversation_message(
    conversation_id: str,
    request: ConversationMessageRequest,
) -> dict:
    try:
        return await send_conversation_message(conversation_id, request.content)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except LookupError as error:
        raise HTTPException(404, "AI conversation not found") from error
    except (APIConnectionError, OpenAIError) as error:
        _raise_ai_error(error)


@router.post("/api/ai/conversations/{conversation_id}/reset")
async def reset_conversation_endpoint(conversation_id: str) -> dict:
    try:
        return await reset_conversation(conversation_id)
    except LookupError as error:
        raise HTTPException(404, "AI conversation not found") from error
    except (APIConnectionError, OpenAIError) as error:
        _raise_ai_error(error)
