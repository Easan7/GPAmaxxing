"""Azure Blob container client factory."""

from azure.storage.blob import ContainerClient

from app.config import Settings


def create_blob_container_client(settings: Settings) -> ContainerClient:
    """Create and return a Blob ContainerClient instance."""
    connection_string = settings.AZURE_STORAGE_CONNECTION_STRING or ""
    container_name = settings.AZURE_BLOB_CONTAINER or ""
    return ContainerClient.from_connection_string(
        conn_str=connection_string,
        container_name=container_name,
    )
