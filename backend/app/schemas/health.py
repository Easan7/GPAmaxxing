"""Health endpoint schemas."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Standard health response payload."""

    status: str
    service: str
