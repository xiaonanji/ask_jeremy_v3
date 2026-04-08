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
$env:Path = "C:\Users\sean.ji\node-v24.14.0-win-x64;" + $env:Path
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
npm install
npm run dev
```

The frontend expects the backend at `http://localhost:8000/api` by default.

## Fresh Machine Setup

On Windows, you can bootstrap both apps from the repo root with:

```powershell
.\setup-dev.ps1
```

The script:

- creates `backend/.venv` if needed
- installs backend dependencies with `pip install -e .`
- creates `backend/.env` from `backend/.env.example` if it does not already exist
- installs frontend dependencies with `npm ci`

After the script finishes, set your API key in `backend/.env`, then start the backend and frontend in separate terminals.
