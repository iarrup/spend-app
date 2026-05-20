# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

This project uses [uv](https://docs.astral.sh/uv/) for dependency and environment management.

```bash
# Install dependencies
uv sync

# Run the Flask dev server (port 5001)
uv run python app.py

# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/test_foo.py

# Run a single test by name
uv run pytest -k "test_name"
```

Flask can also be run with the standard `flask` CLI:
```bash
uv run flask --app app run --debug --port 5001
```

## Architecture

**Spendly** is a Flask-based personal expense tracker being built incrementally (likely as a course project). The current state is mostly the public-facing landing/auth pages; the core expense features are stubbed out as placeholder routes in `app.py`.

### Key files

- `app.py` — single Flask application module; all routes live here
- `database/db.py` — SQLite helpers (`get_db`, `init_db`, `seed_db`); **not yet implemented** — students fill this in Step 1
- `templates/base.html` — Jinja2 base layout with navbar and footer; all pages extend this
- `static/css/style.css` — single stylesheet using CSS custom properties (`--ink`, `--accent`, `--paper-*`, etc.)
- `static/js/main.js` — shared JS file, currently empty; per-page JS is inlined in `{% block scripts %}`

### Template/routing pattern

Routes return `render_template("<name>.html")`. Templates extend `base.html` and fill `{% block title %}`, `{% block content %}`, and optionally `{% block scripts %}`. Page-specific JS (e.g. the video modal on the landing page) goes in `{% block scripts %}`.

### Database

SQLite via Python's `sqlite3`. The `database/db.py` module is the designated place for `get_db()` (returns a row-factory-enabled connection with foreign keys on), `init_db()`, and `seed_db()`. Not yet wired into the Flask app context.

### Placeholder routes

The following routes in `app.py` return stub strings and are meant to be implemented in later steps: `/logout`, `/profile`, `/expenses/add`, `/expenses/<id>/edit`, `/expenses/<id>/delete`.
