import os
import logging
from dotenv import load_dotenv
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.core.exceptions import AzureError
# REMOVED: azure.storage.blob (not needed for RAG MVP)


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Load .env
load_dotenv()


# Azure AI Search RAG (lecturer notes already indexed)
AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_API_KEY = os.getenv("AZURE_SEARCH_API_KEY")
AZURE_SEARCH_INDEX_NAME = os.getenv("AZURE_SEARCH_INDEX_NAME", "azureblob-index")


# RAG-only validation (no blob storage needed)
def _validate_env():
    """RAG-only env validation"""
    required = ["AZURE_SEARCH_ENDPOINT", "AZURE_SEARCH_API_KEY"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise ValueError(f"RAG missing env vars: {', '.join(missing)}")
    logger.info("✅ RAG credentials validated")


_validate_env()


# Lazy search client only
_search_client = None


def get_search_client():
    """Lazy AI Search client for lecturer notes"""
    global _search_client
    if _search_client is None:
        _search_client = SearchClient(
            endpoint=AZURE_SEARCH_ENDPOINT,
            index_name=AZURE_SEARCH_INDEX_NAME,
            credential=AzureKeyCredential(AZURE_SEARCH_API_KEY)
        )
    return _search_client


class AISearchClient:
    """Azure AI Search RAG - retrieves lecturer notes for Gap Coach."""
    
    def __init__(self):
        try:
            self.client = get_search_client()
            logger.info(f"✅ Connected to lecturer notes index: {AZURE_SEARCH_INDEX_NAME}")
        except AzureError as e:
            logger.error(f"❌ RAG init failed: {e}")
            raise
    
    def retrieve(self, query: str, top_k: int = 5):
        try:
            if not query or len(query.strip()) == 0:
                raise ValueError("Query cannot be empty")
            
            results = self.client.search(
                search_text=query,
                top=top_k,
                select=["metadata_storage_name", "content", "metadata_storage_path"]
            )
            
            documents = [
                {
                    "source": doc.get("metadata_storage_name", "unknown"),
                    "path": doc.get("metadata_storage_path", ""),
                    "content": doc.get("content", ""),
                    "score": doc.get("@search.score", 0)
                }
                for doc in results
            ]
            
            logger.info(f"✅ Retrieved {len(documents)} lecturer notes for: '{query}'")
            return {
                "query": query,
                "count": len(documents),
                "documents": documents
            }
        except AzureError as e:
            logger.error(f"❌ RAG failed for '{query}': {e}")
            return {"query": query, "count": 0, "documents": [], "error": str(e)}
    
    def health_check(self):
        """Demo health check."""
        try:
            self.client.search(search_text="test", top=1)
            return {"status": "healthy", "index": AZURE_SEARCH_INDEX_NAME}
        except AzureError as e:
            logger.error(f"❌ RAG unhealthy: {e}")
            return {"status": "unhealthy", "error": str(e)}


if __name__ == "__main__":
    # Hackathon demo test
    try:
        rag = AISearchClient()
        
        # Test student error queries
        queries = ["user", "center", "design"]
        for q in queries:
            results = rag.retrieve(q, top_k=2)
            print(f"\n🔍 '{q}' → {results['count']} notes:")
            for doc in results["documents"]:
                print(f"  📄 {doc['source']}: {doc['content'][:80]}...")
        
        print(f"\n🏥 Health: {rag.health_check()}")
    except Exception as e:
        logger.error(f"Demo failed: {e}")
