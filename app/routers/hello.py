"""Sample router (P1 / P15).

Demonstrates Pydantic request/response models — input is validated automatically, so a
malformed body returns ``422`` with no custom code (validation is intrinsic to FastAPI,
PY-D21). Mirrors the shape of the .NET/Go/Node minimal scaffolds (``score: 110``).
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.config import get_settings

router = APIRouter(prefix="/v1", tags=["sample"])


class HelloResponse(BaseModel):
    message: str
    timestamp: str
    version: str
    environment: str
    score: int


class EchoRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class EchoResponse(BaseModel):
    message: str
    name: str


@router.get("/hello", response_model=HelloResponse)
async def hello() -> HelloResponse:
    settings = get_settings()
    return HelloResponse(
        message="Hello from RepoUniqueNormalisedIdentifier!",
        timestamp=datetime.now(timezone.utc).isoformat(),
        version="v1",
        environment=settings.environment,
        score=110,
    )


@router.post("/echo", response_model=EchoResponse)
async def echo(body: EchoRequest) -> EchoResponse:
    # `body` is validated by Pydantic before this runs — bad input → 422 automatically.
    return EchoResponse(message="echo", name=body.name)
