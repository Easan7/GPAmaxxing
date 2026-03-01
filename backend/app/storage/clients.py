"""Storage client wrappers for external systems."""

from dataclasses import dataclass


@dataclass(slots=True)
class SupabaseClient:
    """Placeholder Supabase client wrapper."""

    url: str
    key: str


@dataclass(slots=True)
class BlobStorageClient:
    """Placeholder Azure Blob client wrapper."""

    account_url: str
    container_name: str
