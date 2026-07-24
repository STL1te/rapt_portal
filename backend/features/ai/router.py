"""Server-owned AI conversations backed by an OpenAI-compatible API."""

import asyncio
import json
import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from openai import APIConnectionError, OpenAIError
from pydantic import BaseModel, Field

from .brewzilla_overrides import BrewZillaOverrides
from .recipe_wizard import generate_profile
from .services import (
    open_conversation,
    reset_conversation,
    send_conversation_message,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class OpenConversationRequest(BaseModel):
    subject_type: Literal["brew_session", "fermentation_session", "recipe"]
    subject_id: str = Field(min_length=1, max_length=128)
    locale: str = Field(
        default="ru",
        min_length=2,
        max_length=35,
        pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$",
    )


class ConversationMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class ResetConversationRequest(BaseModel):
    locale: str = Field(
        default="ru",
        min_length=2,
        max_length=35,
        pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$",
    )


class RecipeWizardRequest(BaseModel):
    description: str = Field(min_length=8, max_length=12_000)
    overrides: BrewZillaOverrides | None = None


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
        return await open_conversation(request.subject_type, request.subject_id, request.locale)
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
async def reset_conversation_endpoint(
    conversation_id: str,
    request: ResetConversationRequest | None = None,
) -> dict:
    try:
        return await reset_conversation(conversation_id, request.locale if request else "ru")
    except LookupError as error:
        raise HTTPException(404, "AI conversation not found") from error
    except (APIConnectionError, OpenAIError) as error:
        _raise_ai_error(error)


@router.post("/api/ai/recipe-wizard")
async def recipe_wizard_endpoint(request: RecipeWizardRequest) -> dict:
    try:
        profile, _recipe = await generate_profile(
            request.description, user_overrides=request.overrides
        )
        return profile
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except (APIConnectionError, OpenAIError) as error:
        _raise_ai_error(error)


@router.post("/api/ai/recipe-wizard/stream")
async def recipe_wizard_stream_endpoint(request: RecipeWizardRequest) -> StreamingResponse:
    async def events():
        queue: asyncio.Queue[dict] = asyncio.Queue()

        async def run() -> None:
            try:
                profile, recipe = await generate_profile(
                    request.description,
                    lambda stage: queue.put_nowait({"type": "progress", "stage": stage}),
                    user_overrides=request.overrides,
                )
                await queue.put({"type": "result", "profile": profile, "recipe": recipe})
            except ValueError as error:
                await queue.put({"type": "error", "message": str(error)})
            except APIConnectionError:
                await queue.put({"type": "error", "message": "LLM is unavailable"})
            except OpenAIError:
                logger.exception("LLM request failed")
                await queue.put({"type": "error", "message": "LLM request failed"})
            except Exception:
                logger.exception("Recipe wizard stream failed")
                await queue.put({"type": "error", "message": "Recipe generation failed"})

        task = asyncio.create_task(run())
        try:
            while True:
                event = await queue.get()
                yield json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
                if event["type"] in ("result", "error"):
                    break
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
