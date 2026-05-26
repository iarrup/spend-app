# Spec: Login and Logout

## Overview
Implement session-based authentication so that registered users can sign in and out of Spendly. The `login.html` template already renders a working form that POSTs to `/login`; this step wires it to a `POST /login` handler that verifies credentials with `check_password_hash`, stores the user's id and name in Flask's signed cookie session, and redirects on success. The `/logout` stub is replaced with a handler that clears the session and redirects to the landing page. The navbar in `base.html` is updated to show context-sensitive links — "Sign in / Get started" for guests, and "Hi, {name} / Sign out" for authenticated users.

## Depends on
- Step 01 — Database Setup (`get_db()` must be implemented)
- Step 02 — Registration (users must exist in the `users` table)

## Routes
- `GET /login` — render the login form — public (already exists, no change to GET logic)
- `POST /login` — validate credentials, set session, redirect to landing — public
- `GET /logout` — clear session, redirect to landing — public (harmless if called when not logged in)

## Database changes
No database changes. Reads from the existing `users` table:
```
users(id, name, email, password_hash)
```

## Templates
- **Modify:** `templates/base.html` — update the `nav-links` div to show conditional nav items:
  - When `session.user_id` is not set: show "Sign in" and "Get started" links (current behaviour)
  - When `session.user_id` is set: show "Hi, {{ session.user_name }}" text and a "Sign out" link pointing to `url_for('logout')`
- **No new templates required** — `login.html` already has the form with `{{ error }}` support and POSTs to `/login`

## Files to change
- `app.py` — four changes:
  1. Add `session` to the Flask import line
  2. Add `check_password_hash` to the werkzeug import line
  3. Set `app.secret_key` immediately after `app = Flask(__name__)` — use a hardcoded dev string for now (e.g. `"dev-secret-change-in-prod"`)
  4. Convert `/login` to a GET+POST route with full POST handler logic
  5. Replace the `/logout` stub with a real implementation
- `templates/base.html` — update `nav-links` div with session-conditional markup

## Files to create
None.

## New dependencies
No new pip packages. Uses:
- `flask.session` (already installed)
- `werkzeug.security.check_password_hash` (already installed)

## Rules for implementation
- No SQLAlchemy or ORMs — raw `sqlite3` only via `get_db()`
- Parameterised queries only — never use string formatting in SQL
- Passwords verified with `werkzeug.security.check_password_hash`
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Validate that both `email` and `password` fields are non-empty before querying the database
- Do **not** distinguish between "email not found" and "wrong password" in error messages — use a generic message like "Invalid email or password." to avoid account enumeration
- Store exactly two values in the session: `session['user_id']` (integer) and `session['user_name']` (string) — nothing else
- `logout` must call `session.clear()`, not `session.pop(...)` for individual keys
- After successful login, redirect to `url_for('landing')` — a dedicated post-login dashboard comes in a later step
- After logout, redirect to `url_for('landing')`
- The `/logout` route requires no login guard — if called when already logged out it is harmless

## Definition of done
- [ ] `GET /login` still renders the form with no errors (no regression)
- [ ] Submitting the login form with the demo user credentials (`demo@spendly.com` / `demo123`) redirects to the landing page
- [ ] Submitting with an unrecognised email shows "Invalid email or password." on the form
- [ ] Submitting with a correct email but wrong password shows "Invalid email or password." on the form
- [ ] Submitting with empty email or password fields shows a validation error without hitting the database
- [ ] After a successful login, `session['user_id']` and `session['user_name']` are set (verify via Flask debug or print)
- [ ] The navbar shows "Hi, Demo User" and a "Sign out" link when logged in
- [ ] The navbar shows "Sign in" and "Get started" when logged out
- [ ] Visiting `/logout` clears the session and redirects to the landing page
- [ ] Visiting `/logout` when already logged out redirects to the landing page without error
- [ ] App starts without errors after all changes
