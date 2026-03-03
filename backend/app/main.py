"""FastAPI app entrypoint."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.analytics import router as analytics_router
from app.api.coach import router as coach_router
from app.api.health import router as health_router
from app.config import get_settings


def _parse_allowed_origins(origins_raw: str) -> list[str]:
    cleaned = origins_raw.strip()
    if cleaned == "*":
        return ["*"]
    return [origin.strip() for origin in cleaned.split(",") if origin.strip()]


def create_app() -> FastAPI:
    """Application factory used by ASGI servers and tests."""
    settings = get_settings()
    allowed_origins = _parse_allowed_origins(settings.ALLOWED_ORIGINS)

    app = FastAPI(title="Adaptive Learning Backend", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(analytics_router)
    app.include_router(coach_router)

    @app.get("/")
    def root() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
