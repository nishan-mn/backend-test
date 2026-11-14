"""FastAPI entry point."""

import os
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.models import (
    AnalysisRequest,
    AnalysisResponse,
    ErrorResponse,
    MissionDetail,
    MissionSummary,
)
from app.services.horizons import HorizonsError, TIMEOUT
from app.services.historical_missions import get_mission_detail, list_mission_summaries
from app.services.visibility import analyze_visibility


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        app.state.http_client = client
        yield


def _safe_error_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="backslashreplace")
    if isinstance(value, str):
        return value.encode("utf-8", errors="backslashreplace").decode("utf-8")
    return "Invalid request"


def create_app() -> FastAPI:
    app = FastAPI(title="Lunar Compass Visibility Engine", version=__version__, lifespan=lifespan)
    origins = [origin.strip() for origin in os.getenv(
        "ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173"
    ).split(",") if origin.strip()]
    if any("*" in origin for origin in origins):
        raise ValueError("ALLOWED_ORIGINS must contain explicit origins, not wildcards")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(HorizonsError)
    async def horizons_error(request: Request, exc: HorizonsError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Allowlist error metadata: raw input and exception context are not response data.
        errors = [{
            "type": _safe_error_text(error["type"]),
            "loc": [part if type(part) is int else _safe_error_text(part) for part in error["loc"]],
            "msg": _safe_error_text(error["msg"]),
        } for error in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get(
        "/api/missions",
        response_model=list[MissionSummary],
        responses={422: {"model": ErrorResponse}},
        tags=["missions"],
    )
    async def read_missions(
        country: str | None = Query(default=None, min_length=1),
        landing_outcome: str | None = Query(default=None, min_length=1),
    ) -> list[MissionSummary]:
        """Return source-backed history only; modeled replay output is separate."""

        try:
            return list_mission_summaries(
                country=country,
                landing_outcome=landing_outcome,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get(
        "/api/missions/{mission_id}",
        response_model=MissionDetail,
        responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
        tags=["missions"],
    )
    async def read_mission(mission_id: str) -> MissionDetail:
        """Return a complete verified mission record with its source provenance."""

        try:
            mission = get_mission_detail(mission_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if mission is None:
            raise HTTPException(status_code=404, detail="Mission not found")
        return mission

    @app.post("/api/analyze", response_model=AnalysisResponse)
    async def analyze(
        body: AnalysisRequest, client: httpx.AsyncClient = Depends(get_http_client)
    ) -> AnalysisResponse:
        return await analyze_visibility(body, client)

    return app

def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


app = create_app()
