"""Supabase client factory."""

from supabase import Client, create_client

from app.config import Settings


def resolve_supabase_credentials(settings: Settings) -> tuple[str | None, str | None]:
    """Resolve Supabase URL and API key from settings.

    Preference order for key: SERVICE_ROLE -> SUPABASE_KEY -> ANON.
    """
    url = settings.SUPABASE_URL
    key = settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_KEY or settings.SUPABASE_ANON_KEY
    return url, key


def create_supabase_client(settings: Settings) -> Client:
    """Create and return a Supabase client instance."""
    url, key = resolve_supabase_credentials(settings)
    if not url or not key:
        raise ValueError("Supabase credentials are not configured. Set SUPABASE_URL and a Supabase key.")
    return create_client(url, key)
