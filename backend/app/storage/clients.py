"""Storage client wrappers for external systems."""

from dataclasses import dataclass


@dataclass(slots=True)
class SupabaseClient:
    """Placeholder Supabase client wrapper."""

    url: str
    key: str

# Not in use -- keep after MVP? 
#   -- currently majority of logic in blob_client.py
# @dataclass(slots=True)
# class BlobStorageClient:
#     """Placeholder Azure Blob client wrapper."""

#     account_url: str
    # container_name: str
