"""Supabase client factory."""

from supabase import Client, create_client

from app.config import Settings


def create_supabase_client(settings: Settings) -> Client:
    """Create and return a Supabase client instance."""
    url = settings.SUPABASE_URL or ""
    key = settings.SUPABASE_KEY or ""
    return create_client(url, key)
