# GPAmaxxing

## .env Setup

### Backend `.env`

Create this file:

```text
backend/.env
```

Use this format:

```env
# App
APP_ENV=dev
ALLOWED_ORIGINS=*

# OpenAI / Azure OpenAI
OPENAI_API_KEY=You can use your own API Key/Refer to Documentation (Section 9)
OPENAI_MODEL="gpt-4o-mini"

# Supabase (required for analytics/attempt data)
SUPABASE_URL=Refer to Documentation (Section 9)
SUPABASE_KEY=Refer to Documentation (Section 9)

# IMPORTANT: both index names are referenced; set both to same value
AZURE_SEARCH_ENDPOINT= "Refer to Documentation (Section 9)"
AZURE_SEARCH_API_KEY= "Refer to Documentation (Section 9)"
AZURE_SEARCH_INDEX_NAME = "Refer to Documentation (Section 9)"
```

### Frontend `.env`

Create this file:

```text
frontend/.env
```

Use this format:

```env
# Optional. If omitted, dev mode can use Vite proxy for /api.
# If set, use full backend URL, e.g. http://localhost:8000
VITE_API_BASE_URL=

# Supabase (used by frontend Supabase client)
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_ANON_KEY=your_anon_key
```

To use the exact keys/values, refer to project documentation.

## Run Backend

```bash
cd backend
python -m venv .venv
```

Windows (PowerShell):

```powershell
.\.venv\Scripts\Activate.ps1
```

Install and run:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## Run Frontend

```bash
cd frontend
npm install
npm run dev
```

Open:

```text
http://localhost:5173
```
