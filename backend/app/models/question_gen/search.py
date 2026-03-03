from __future__ import annotations

from typing import Any

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient

from app.config import get_settings


def retrieve_topic_context(*, topic: str, tags: list[str] | None = None, top_k: int = 6) -> list[dict[str, Any]]:
    settings = get_settings()
    endpoint = settings.AZURE_SEARCH_ENDPOINT
    key = settings.AZURE_SEARCH_KEY
    index_name = settings.AZURE_SEARCH_INDEX

    if not endpoint or not key or not index_name:
        return []

    search_text_parts = [topic] + [str(tag).strip() for tag in (tags or []) if str(tag).strip()]
    search_text = " ".join(search_text_parts).strip()
    if not search_text:
        return []

    client = SearchClient(
        endpoint=endpoint,
        index_name=index_name,
        credential=AzureKeyCredential(key),
    )

    results = client.search(
        search_text=search_text,
        top=max(1, min(int(top_k), 12)),
        select=["content", "metadata_storage_name", "metadata_storage_path"],
    )

    docs: list[dict[str, Any]] = []
    for doc in results:
        docs.append(
            {
                "content": str(doc.get("content") or "")[:2200],
                "source": str(doc.get("metadata_storage_name") or "unknown"),
                "path": str(doc.get("metadata_storage_path") or ""),
                "score": float(doc.get("@search.score") or 0.0),
            }
        )
    return docs
