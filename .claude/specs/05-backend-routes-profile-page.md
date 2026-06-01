# Spec: Backend Routes for Profile Page

## Overview
Add the write-side backend to the profile page so that logged-in users can update their account details (name, email, and optionally their password) and permanently delete their account. Step 04 delivered the read-only `/profile` view; this step adds a `POST /profile` handler for edits and a `POST /profile/delete` handler for account deletion. Both routes enforce the session login guard and give clear inline feedback on success or validation failure.

## Depends on
- Step 01 — Database Setup (`get_db()`, `users` table, `expenses` table must exist)
- Step 02 — Registration (users must exist in `users` table)
- Step 03 — Login and Logout (session carries `user_id` and `user_name`)
- Step 04 — Profile Page Design (`templates/profile.html` and the read-only `GET /profile` route must be in place)

## Routes
- `GET /profile` — render the profile page — logged-in only (already implemented; no changes needed)
- `POST /profile` — update name, email, and optionally password — logged-in only
- `POST /profile/delete` — delete the account and all its expenses, then log out — logged-in only

## Database changes
No new tables or columns. Existing schema is sufficient:
- `users(id, name, email, password_hash)` — UPDATE target for profile edits; DELETE target for account removal
- `expenses(user_id, ...)` — DELETE all rows for the user before deleting the user row (foreign key constraint)

## Templates
- **Modify:** `templates/profile.html` — three additions:
  1. An edit-profile form (name, email, current password for confirmation, new password + confirm fields) that POSTs to `url_for('update_profile')`; pre-populated with the user's current name and email; shows `{{ error }}` or `{{ success }}` flash-style message
  2. A delete-account section at the bottom with a confirmation form (password field) that POSTs to `url_for('delete_profile')`; styled as a danger zone
  3. Conditionally render `{{ error }}` or `{{ success }}` at the top of the page using CSS variables (`--error` / `--accent`) — no hardcoded hex values

## Files to change
- `app.py` — add two new route functions:
  1. `update_profile()` — `POST /profile`: validate fields, check current password, apply updates, refresh `session['user_name']` if name changed
  2. `delete_profile()` — `POST /profile/delete`: verify password, delete expenses then user, call `session.clear()`, redirect to landing
- `templates/profile.html` — add the edit form, flash message area, and danger-zone delete form

## Files to create
None.

## New dependencies
No new pip packages. Uses:
- `werkzeug.security.check_password_hash` and `generate_password_hash` (already installed)
- `flask.session`, `flask.request`, `flask.redirect`, `flask.url_for` (already installed)

## Rules for implementation
- No SQLAlchemy or ORMs — raw `sqlite3` only via `get_db()`
- Parameterised queries only — never use string formatting in SQL
- Passwords hashed with `werkzeug.security.generate_password_hash`; verified with `check_password_hash`
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Both POST routes must start with a login guard: `if not session.get('user_id'): redirect(url_for('login'))`
- `update_profile` validation rules:
  - Name and email must not be empty after `.strip()`
  - Current password must be provided and verified with `check_password_hash` before any update is applied
  - If a new password is supplied: it must be at least 8 characters and match the confirm-password field
  - If new email differs from the current one and is already taken, catch `sqlite3.IntegrityError` and return an error message
  - On success, update `session['user_name']` if name changed, then redirect back to `GET /profile` with a success flash parameter (e.g. `?updated=1`)
- `delete_profile` validation rules:
  - Password must be provided and verified before deletion proceeds
  - Delete expenses first (`DELETE FROM expenses WHERE user_id = ?`), then delete the user row — order matters for foreign key constraint
  - Call `session.clear()` after deletion
  - Redirect to `url_for('landing')` after deletion
- Close every database connection in a `finally` block
- Do not use `redirect` with a flash cookie — pass `success` or `error` as a query param or re-render the template with the variable directly

## Definition of done
- [ ] `GET /profile` still renders correctly with no regression
- [ ] Submitting the edit form with valid name, email, and correct current password updates the `users` row (verify with `sqlite3 spendly.db "SELECT name, email FROM users WHERE id=1;"`)
- [ ] Changing the name updates the "Hi, {name}" display in the navbar immediately after redirect (session refreshed)
- [ ] Submitting the edit form with an incorrect current password shows an inline error and makes no DB changes
- [ ] Submitting a new password shorter than 8 characters shows a validation error
- [ ] Submitting mismatched new-password and confirm-password fields shows a validation error
- [ ] Attempting to change email to one already used by another account shows an error
- [ ] A success message is visible on the profile page after a successful update
- [ ] Submitting the delete form with the correct password deletes the user and all their expenses, then redirects to the landing page as a logged-out user
- [ ] Submitting the delete form with the wrong password shows an error and does not delete the account
- [ ] After account deletion, visiting `/profile` redirects to `/login`
- [ ] App starts without errors after all changes