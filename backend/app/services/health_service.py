"""Service-layer health logic."""

from app.schemas.health import HealthResponse


def get_health_status() -> HealthResponse:
    """Return basic service health information."""
    return HealthResponse(status="ok", service="backend")
