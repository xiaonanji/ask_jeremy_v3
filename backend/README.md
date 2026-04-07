# Ask Jeremy Backend

FastAPI backend for the first slice of the Ask Jeremy project.

## Features

- Session-scoped chat API
- Filesystem workspace for every conversation
- LangGraph v1 chat workflow with SQLite-backed checkpointing per session
- Local tool calling for shell commands and inline Python execution
- Read-only SQL execution for SQLite and Snowflake with session artifact persistence
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
- `PERSON_WIKI_ROOT`
- `TOOL_TIMEOUT_SECONDS`
- `DEFAULT_DATABASE_BACKEND`
- `SQLITE_DATABASE_PATH`
- `SQL_QUERY_MAX_ROWS`
- `SQL_QUERY_TIMEOUT_SECONDS`
- `SNOWFLAKE_ACCOUNT`
- `SNOWFLAKE_USER`
- `SNOWFLAKE_ROLE`
- `SNOWFLAKE_WAREHOUSE`
- `SNOWFLAKE_DATABASE`
- `SNOWFLAKE_SCHEMA`
- `SNOWFLAKE_AUTHENTICATOR`

## Local Tools

The chat agent can call three local tools during a turn:

- `run_shell_command`: runs local shell commands from the backend host
- `run_python_script`: runs inline Python using the backend virtualenv interpreter
- `execute_sql_query`: executes read-only SQL against the session-selected SQLite or Snowflake backend and writes the result set to the active session's `artifacts/sql/...` folder

## Database Backends

Each session stores its own database backend selection. The SQL tool executes against that backend, so users can switch a conversation between SQLite and Snowflake without changing prompts.

SQLite uses a single env var:

- `SQLITE_DATABASE_PATH`

Snowflake uses env-backed browser auth:

- `SNOWFLAKE_ACCOUNT`
- `SNOWFLAKE_USER`
- `SNOWFLAKE_ROLE`
- `SNOWFLAKE_WAREHOUSE`
- `SNOWFLAKE_DATABASE`
- `SNOWFLAKE_SCHEMA`
- `SNOWFLAKE_AUTHENTICATOR` with the default `externalbrowser`

These tools are not sandboxed. They should only be enabled in a trusted local environment.

If you want the agent to search a personal wiki repository reliably, set `PERSON_WIKI_ROOT` in `backend/.env`.

## Skill APIs

- `GET /api/skills`: list discovered skills
- `GET /api/sessions/{session_id}/skills`: list active skills for a session

You can also expose multiple selectable models in the frontend by setting:

- `OPENAI_AVAILABLE_MODELS=model-a,model-b`
- `ANTHROPIC_AVAILABLE_MODELS=model-x,model-y`
