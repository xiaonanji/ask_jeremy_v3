# Ask Jeremy Backend

FastAPI backend for the first slice of the Ask Jeremy project.

## Features

- Session-scoped chat API
- Filesystem workspace for every conversation
- LangGraph v1 chat workflow with SQLite-backed checkpointing per session
- OpenAI and Anthropic models through LangChain chat model adapters
- Skill discovery from project and user skill roots
- Skill catalog endpoint plus per-session LLM-driven skill activation
- JSON-based session transcript persistence

## Run

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .
uvicorn ask_jeremy_backend.main:app --reload
```

## Environment

Copy `.env.example` to `.env`, set `DEFAULT_MODEL_PROVIDER` to `openai` or `anthropic`, and provide the matching API key.

LangGraph checkpoints are stored locally in `backend/data/langgraph_checkpoints.sqlite` by default. You can override that with `LANGGRAPH_CHECKPOINT_PATH`.

Skill loading defaults:

- Project skills: `<repo>/.agents/skills`
- User skills: `%USERPROFILE%\\.agents\\skills`

Relevant settings:

- `PROJECT_SKILL_ROOT`
- `USER_SKILL_ROOT`
- `ENABLE_PROJECT_SKILLS`
- `ENABLE_USER_SKILLS`
- `TRUST_PROJECT_SKILLS`
- `MAX_AUTO_ACTIVATED_SKILLS`

## Skill APIs

- `GET /api/skills`: list discovered skills
- `GET /api/sessions/{session_id}/skills`: list active skills for a session

You can also expose multiple selectable models in the frontend by setting:

- `OPENAI_AVAILABLE_MODELS=model-a,model-b`
- `ANTHROPIC_AVAILABLE_MODELS=model-x,model-y`
