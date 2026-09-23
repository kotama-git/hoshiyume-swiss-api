"""Production entry point with a validated Cloud Run compatible port."""

import os

import uvicorn


def configured_port() -> int:
    try:
        port = int(os.getenv("PORT", "8080"))
    except ValueError as exc:
        raise SystemExit("PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise SystemExit("PORT must be between 1 and 65535")
    return port


if __name__ == "__main__":
    uvicorn.run(
        "swiss_api.main:app",
        host="0.0.0.0",
        port=configured_port(),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
