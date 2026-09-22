"""Private service boundary; HOSHIYUME authenticates users before calling it."""

import os
from functools import lru_cache
from hmac import compare_digest
from importlib.metadata import version
from pathlib import Path

import swisseph as swe
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from swiss_api.calculation import EphemerisUnavailable, SwissEngine
from swiss_api.models import NatalRequest, NatalResponse

app = FastAPI(title="HOSHIYUME Calculation API", version="0.1.0")
bearer = HTTPBearer(auto_error=False)


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


@app.get("/health")
def health(engine: SwissEngine = Depends(get_engine)) -> dict:
    return {
        "status": "ok" if engine.ready else "not_ready",
        "ephemeris_files_configured": engine.ready,
        "engine_version": swe.version if engine.ready else None,
        "wrapper_version": version("pyswisseph") if engine.ready else None,
        "ephemeris_dataset_sha256": engine.dataset_hash,
        "rules_version": "natal_v1",
    }


@app.post("/natal", response_model=NatalResponse, dependencies=[Depends(require_service_token)])
def natal(request: NatalRequest, engine: SwissEngine = Depends(get_engine)) -> dict:
    try:
        return engine.natal(request)
    except EphemerisUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
