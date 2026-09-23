"""Service boundary; HOSHIYUME authenticates users before calling it."""

import os
from functools import lru_cache
from hmac import compare_digest
from importlib.metadata import version
from pathlib import Path
from urllib.parse import urlsplit

import swisseph as swe
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from swiss_api.calculation import EphemerisUnavailable, SwissEngine
from swiss_api.models import NatalRequest, NatalResponse

app = FastAPI(title="HOSHIYUME Calculation API", version="0.1.0")
bearer = HTTPBearer(auto_error=False)
LICENSE_ID = "AGPL-3.0-or-later"


def source_code_url() -> str | None:
    value = os.getenv("SOURCE_CODE_URL", "").strip()
    if not value:
        return None
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        return None
    return value


@app.middleware("http")
async def offer_corresponding_source(request: Request, call_next):
    response = await call_next(request)
    source = source_code_url()
    if source:
        response.headers["Link"] = f'<{source}>; rel="source"'
    return response


@lru_cache(maxsize=4)
def _engine_for_path(path: str | None) -> SwissEngine:
    return SwissEngine(Path(path) if path else None)


def get_engine() -> SwissEngine:
    return _engine_for_path(os.getenv("SWISS_EPHE_PATH"))


def require_service_token(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> None:
    expected = os.getenv("SWISS_API_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="service authentication is not configured")
    if credentials is None or not compare_digest(credentials.credentials, expected):
        raise HTTPException(status_code=401, detail="invalid service token")


@app.get("/", include_in_schema=False)
def service_information() -> dict:
    return {
        "service": "HOSHIYUME Calculation API",
        "license": LICENSE_ID,
        "source_code_url": source_code_url(),
    }


@app.get("/source", include_in_schema=False)
def corresponding_source() -> RedirectResponse:
    source = source_code_url()
    if not source:
        raise HTTPException(status_code=503, detail="corresponding source is not configured")
    return RedirectResponse(source, status_code=307)


@app.get("/health")
def health(engine: SwissEngine = Depends(get_engine)) -> dict:
    source = source_code_url()
    ready = engine.ready and bool(os.getenv("SWISS_API_TOKEN")) and source is not None
    return {
        "status": "ok" if ready else "not_ready",
        "ephemeris_files_configured": engine.ready,
        "source_offer_configured": source is not None,
        "engine_version": swe.version if engine.ready else None,
        "wrapper_version": version("pyswisseph") if engine.ready else None,
        "ephemeris_dataset_sha256": engine.dataset_hash,
        "rules_version": "natal_v1",
        "license": LICENSE_ID,
        "source_code_url": source,
    }


@app.post("/natal", response_model=NatalResponse, dependencies=[Depends(require_service_token)])
def natal(request: NatalRequest, engine: SwissEngine = Depends(get_engine)) -> dict:
    try:
        return engine.natal(request)
    except EphemerisUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
