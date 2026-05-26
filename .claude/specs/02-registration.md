# Spec: Registration

## Overview
Implement the user sign-up flow so that new visitors can create a Spendly account. The existing `register.html` template already renders the form; this step wires it to a real `POST /register` handler that validates input, hashes the password with werkzeug, and inserts the new user into the `users` table. On success the user is redirected to the login page. On failure the form re-renders with an inline error message via the `{{ error }}` variable already present in the template.

## Depends on
Step 01 — Database Setup (`database/db.py` must be fully implemented with `get_db()` and `init_db()`).

## Routes
- `GET /register` — render the registration form — public (already exists, no change needed)
- `POST /register` — process form submission; insert user or return error — public

## Database changes
No new tables or columns. Uses the existing `users` table:
```
users(id, name, email, password_hash, created_at)
```

## Templates
- **Modify:** `templates/register.html` — already renders `{{ error }}`; no changes needed unless UX improvements are warranted
- **No new templates**

## Files to change
- `app.py` — add `request`, `redirect`, `url_for` to Flask imports; convert `/register` from GET-only to a GET+POST route with full handler logic

## Files to create
None.

## New dependencies
No new dependencies. Uses:
- `werkzeug.security.generate_password_hash` (already installed)
- `sqlite3` (stdlib)
- `flask.request`, `flask.redirect`, `flask.url_for` (already installed)

## Rules for implementation
- No SQLAlchemy or ORMs — raw `sqlite3` only via `get_db()`
- Parameterised queries only — never use string formatting in SQL
- Passwords hashed with `werkzeug.security.generate_password_hash`
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Validate all three fields (name, email, password) server-side; do not rely solely on HTML `required`
- Password must be at least 8 characters
- On duplicate email, catch the `sqlite3.IntegrityError` and re-render the form with a user-friendly error (e.g. "An account with that email already exists.")
- On success, redirect to `url_for('login')` — do **not** auto-login the user (sessions come in Step 3)
- Do not commit the connection before inserting; use `conn.commit()` only after a successful insert

## Definition of done
- [ ] `GET /register` still renders the form (no regression)
- [ ] Submitting the form with valid data inserts a row into `users` with a hashed password (verify in SQLite browser or with `sqlite3 spendly.db "SELECT email, password_hash FROM users;"`)
- [ ] Submitting with an empty name, email, or password re-renders the form with an error message visible on the page
- [ ] Submitting with a password shorter than 8 characters shows a validation error
- [ ] Submitting with an already-registered email shows "An account with that email already exists." (or similar)
- [ ] Successful registration redirects to `/login`
- [ ] The `password_hash` column never contains a plaintext password
- [ ] App starts without errors after the change
