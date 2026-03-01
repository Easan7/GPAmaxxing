# App Structure

This `app/` package follows a service-oriented layout designed for clean separation of concerns.

- `main.py`: FastAPI application entrypoint (app creation, middleware, router registration).
- `config.py`: Centralized environment/config loading.
- `api/`: Thin HTTP route handlers (validation + delegation only).
- `schemas/`: Pydantic request/response schemas shared by routes/services.
- `services/`: Core business logic.
- `models/`: Deterministic domain models and pure computation structures.
- `agents/`: LangGraph/LangChain orchestration layer.
- `storage/`: Data and file access abstractions (Supabase + Blob).
- `rag/`: Retrieval and RAG-specific logic (Azure AI Search integration point).

Keep routes thin and move behavior to service classes/functions.
