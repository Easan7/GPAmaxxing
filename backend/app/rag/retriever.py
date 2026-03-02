"""
Gpamaxxing RAG Retriever
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
    """Azure AI Search retriever for Gpa Coach - lecturer notes."""
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
    
    # queries = [
    #     "User",
    #     "hex", 
    #     "life"
    # ]
    
    # Interaction Design core concepts
    queries = [{
        "user": "What are Fitts's Law and Hick's Law in interaction design?",
        "system": "Gap Coach for Interaction Design. Explain core principles from course notes. Cite specific lecturers/sources. Give practical examples.",
        "intent": "design_principles"
    },
    {
        "user": "How do I design better user protocols?",
        "system": "Protocol design best practices from course materials. Focus on usability testing, iterative design, user-centered methods. Cite protocols from notes.",
        "intent": "protocol_design"
    },
    {
        "user": "30min study plan for Interaction Design midterm",
        "system": "Create targeted review plan using lecturer notes. Prioritize high-yield topics (heuristics, prototyping, evaluation). Cite specific sections.",
        "intent": "study_plan"
    },
    {
        "user": "Common mistakes in interaction design projects?",
        "system": "Diagnose typical student pitfalls from course examples. Reference lecturer feedback and common errors. Suggest fixes with citations.",
        "intent": "error_summary"
    },
    {
        "user": "Explain Nielsen's 10 heuristics with examples",
        "system": "Break down Nielsen heuristics using course case studies. Practical examples from lecturer notes. Prioritize most violated ones.",
        "intent": "heuristics"
    },
    {
        "user": "My wireframes keep failing usability tests, help!",
        "system": "Wireframe + prototype evaluation from Interaction Design notes. Common issues and fixes. Cite specific protocol examples.",
        "intent": "usability_fix"
    }]

    
    for query in queries:
        result = rag_api.search(query["user"])
        print(f"\n🔍 '{query['user']}' → {result['count']} notes:")
        for doc in result["documents"]:
            print(f"  📄 {doc['source']} ({doc['score']}): {doc['preview']}")
