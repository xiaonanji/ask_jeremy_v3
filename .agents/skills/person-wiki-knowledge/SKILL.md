---
name: person-wiki-knowledge
description: Use this skill when the user wants to query, ingest, maintain, or reuse knowledge from the `person-wiki` repository. Use it for questions about what the wiki contains, how to search it, how to ingest new raw sources, how to refresh qmd search, or how to leverage this wiki from other projects. This skill is intended to work across agents that support `SKILL.md`-based skills and the `.agents/skills/` convention.
---

# Person Wiki Knowledge

## Overview

This skill teaches you how to use the `person-wiki` repository as a persistent knowledge base.

The repo contains:

- `raw/`: immutable source material
- `wiki/`: maintained markdown knowledge base
- `AGENTS.md`: operating schema for ingest/query/lint workflow
- `scripts/wiki.py`: helper CLI for search, lint, and qmd-backed lookup

## Locate The Repository

Before using this skill, locate the `person-wiki` repository.

Preferred order:

1. Check whether the environment variable `PERSON_WIKI_ROOT` is set.
2. If not set, look for a local repository named `person-wiki` in common user locations.
3. Confirm a candidate by checking for all of:
   - `AGENTS.md`
   - `wiki/index.md`
   - `scripts/wiki.py`
4. If multiple candidates exist, ask the user which repo to use.

Common candidate paths on this machine may include:

- `C:\Users\stick\Documents\person-wiki`
- nearby sibling repositories to the current working directory

In all commands below, substitute the resolved repo root for `<PERSON_WIKI_ROOT>`.

## Query Workflow

When the user asks a question that should be answered from this wiki:

1. Read `<PERSON_WIKI_ROOT>\wiki\index.md` first.
2. If the wiki branch is obvious and small, open the relevant `wiki/` pages directly.
3. If retrieval is unclear or the question is broad, use qmd-backed search first.
4. Read the most relevant wiki pages, not the raw inbox, unless the user explicitly wants raw-source inspection.
5. Answer with references to wiki pages when possible.

Prefer these commands:

```bash
python <PERSON_WIKI_ROOT>\scripts\wiki.py qquery "your question"
python <PERSON_WIKI_ROOT>\scripts\wiki.py qsearch "keywords"
```

Fallback:

```bash
python <PERSON_WIKI_ROOT>\scripts\wiki.py search "keywords"
```

Useful support commands:

```bash
python <PERSON_WIKI_ROOT>\scripts\wiki.py recent
python <PERSON_WIKI_ROOT>\scripts\wiki.py lint
```

## Ingest Workflow

When the user asks to ingest new material:

1. Look in `<PERSON_WIKI_ROOT>\raw\inbox`.
2. Compare inbox files against existing pages in `<PERSON_WIKI_ROOT>\wiki\sources`.
3. Read `<PERSON_WIKI_ROOT>\AGENTS.md` and follow the ingest rules there.
4. Treat `raw/` as immutable.
5. Write or update pages in `wiki/sources`, `wiki/entities`, `wiki/concepts`, `wiki/analyses`, `wiki/meta`, `wiki/index.md`, and `wiki/log.md` as needed.
6. After wiki changes, refresh qmd search if available.

Refresh command:

```bash
npm --prefix <PERSON_WIKI_ROOT> run qmd:refresh
```

If qmd is not initialized on the machine yet, note that refresh is pending rather than blocking the ingest.

## QMD Notes

The repo uses repo-local qmd state under:

- `<PERSON_WIKI_ROOT>\.cache\qmd`

Initial setup on a new machine:

```bash
npm --prefix <PERSON_WIKI_ROOT> install
npm --prefix <PERSON_WIKI_ROOT> run qmd:init
```

Do not run multiple qmd commands against this repo at the same time. The repo-local SQLite index can hit locking errors.

## Reuse Guidance

Use this wiki as a reference repo when:

- the user wants knowledge previously ingested here
- another project needs guidance that already exists in this wiki
- the user wants to turn durable wiki knowledge into skills, analyses, or implementation instructions

Do not assume this wiki is relevant to every task. Use it only when the user asks about this knowledge base or when the task clearly benefits from it.
