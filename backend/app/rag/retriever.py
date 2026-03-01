"""
Gapamaxxing RAG Retriever
LangChain interface → AISearchClient (lecturer notes)
"""

import sys
from pathlib import Path
from typing import List
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.callbacks import CallbackManagerForRetrieverRun

try:
    from app.storage.blob_client import AISearchClient
except ModuleNotFoundError:
    backend_root = Path(__file__).resolve().parents[2]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))
    from app.storage.blob_client import AISearchClient


class GapamaxxingRetriever(BaseRetriever):
    """Azure AI Search retriever for Gap Coach - lecturer notes."""
    client: AISearchClient
    top_k: int = 5
    
    class Config:
        arbitrary_types_allowed = True
    
    def __init__(self, top_k: int = 5):
        super().__init__(client=AISearchClient(), top_k=top_k)
    
    def _get_relevant_documents(
        self, 
        query: str, 
        *,
        run_manager: CallbackManagerForRetrieverRun = None
    ) -> List[Document]:
        """Retrieve lecturer notes explaining student gaps."""
        if not query.strip():
            return []
        
        # Call YOUR AISearchClient.retrieve() exactly!
        azure_result = self.client.retrieve(query, top_k=self.top_k)
        
        if azure_result.get("error"):
            print(f"⚠️ No lecturer notes for: {azure_result['error']}")
            return []
        
        # Convert YOUR format → LangChain Documents
        documents = [
            Document(
                page_content=doc["content"][:1500],  # LLM context limit
                metadata={
                    "source": doc["source"],           # "notes-fractions.pdf"
                    "path": doc["path"],               # Full Azure path
                    "score": round(doc["score"], 3),   # Relevance 0.92
                    "index": "azureblob-index"
                }
            )
            for doc in azure_result["documents"]
        ]
        
        print(f"✅ RAG: {len(documents)} notes for '{query[:50]}...'")
        return documents


# Direct API usage (FastAPI endpoint)
class GapamaxxingRAGAPI:
    """Standalone RAG for frontend /rag/ endpoint."""
    
    def __init__(self, top_k: int = 5):
        self.retriever = GapamaxxingRetriever(top_k)
    
    def search(self, query: str, top_k: int = 5) -> dict:
        """Frontend-friendly JSON response."""
        retriever = self.retriever if top_k == self.retriever.top_k else GapamaxxingRetriever(top_k=top_k)
        docs = retriever.invoke(query)
        return {
            "query": query,
            "count": len(docs),
            "documents": [
                {
                    "source": d.metadata["source"],
                    "content": d.page_content,
                    "score": d.metadata["score"],
                    "preview": d.page_content[:200] + "..."
                }
                for d in docs
            ]
        }


if __name__ == "__main__":
    # Hackathon demo test
    rag_api = GapamaxxingRAGAPI(top_k=3)
    
    queries = [
        "User",
        "Design", 
        "Principle"
    ]
    
    for query in queries:
        result = rag_api.search(query)
        print(f"\n🔍 '{query}' → {result['count']} notes:")
        for doc in result["documents"]:
            print(f"  📄 {doc['source']} ({doc['score']}): {doc['preview']}")
