# Ask Jeremy v3

Initial scaffold for a data analytical agent project.

## Structure

- `backend/`: FastAPI chat backend with LangGraph-driven replies, skill loading, and session-specific workspaces
- `frontend/`: React + Vite chat client with a ChatGPT-style layout

The backend can use either OpenAI or Anthropic natively through a shared model interface selected with `DEFAULT_MODEL_PROVIDER`.

## Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -e .
uvicorn ask_jeremy_backend.main:app --reload
```

## Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend expects the backend at `http://localhost:8000/api` by default.
