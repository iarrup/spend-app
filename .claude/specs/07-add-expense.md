# Spec: Add Expense

## Overview
Implement the add-expense feature so that logged-in users can record a new expense
entry from a dedicated form page. The form collects the four required fields
(amount, category, date, description) and inserts a row into the existing
`expenses` table. On success the user is redirected back to the profile page with
a brief confirmation message. This replaces the placeholder stub at
`GET /expenses/add` and is the first feature that lets users grow their expense
history beyond the seeded demo data.

## Depends on
- Step 01 — Database Setup (`get_db()`, `expenses` table must exist)
- Step 03 — Login and Logout (session must carry `user_id`)
- Step 05 — Backend Routes for Profile Page (profile page must be in place for the
  post-submit redirect)

## Routes
- `GET /expenses/add` — render the add-expense form — logged-in only
- `POST /expenses/add` — validate and insert the new expense, then redirect — logged-in only

## Database changes
No new tables or columns. The existing `expenses` table has all required columns:
`user_id`, `amount`, `category`, `date`, `description`.

## Templates
- **Create:** `templates/add_expense.html`
  - Extends `base.html`
  - A form with `method="POST"` and `action="{{ url_for('add_expense') }}"`
  - Fields:
    - `amount` — `<input type="number" step="0.01" min="0.01">` — required
    - `category` — `<select>` dropdown with fixed options: Food, Transport, Bills,
      Health, Entertainment, Shopping, Other — required
    - `date` — `<input type="date">` — required; default to today's date
    - `description` — `<textarea>` — optional
  - Inline error message block (same `auth-error` class pattern as register/login)
  - A "Save expense" submit button
  - A "Cancel" link back to `url_for('profile')`

- **Modify:** `templates/profile.html`
  - Add an "Add expense" button/link (e.g. `<a href="{{ url_for('add_expense') }}">`)
    near the stats section or page header, visible only when logged in
  - Display a success flash when `request.args.get('added')` is truthy (mirror the
    existing `?updated=1` pattern used for profile edits)

## Files to change
- `app.py`
  1. Replace the existing `add_expense` stub with a proper view that handles both
     `GET` and `POST` methods:
     - Both methods must redirect to login if `session.get("user_id")` is falsy
     - `GET`: render `add_expense.html` with `date` pre-populated to today via
       `date.today().isoformat()`
     - `POST`: read `amount`, `category`, `date`, `description` from `request.form`;
       validate (see rules); insert row; redirect to `url_for('profile', added=1)`
  2. Update the existing `profile()` `GET` route to detect `request.args.get('added')`
     and pass an `added_success` flag (or reuse the existing `success` variable with
     message "Expense added successfully.") to `render_template`

- `templates/profile.html`
  - Add "Add expense" link near the stats/header area
  - Show success message when `?added=1` is present (can reuse the `success`
    variable already passed from the route, or add a new `added` variable)

## Files to create
- `templates/add_expense.html`

## New dependencies
No new dependencies. Uses `date` from `datetime` (already imported in `app.py`).

## Rules for implementation
- No SQLAlchemy or ORMs — raw `sqlite3` only via `get_db()`
- Parameterised queries only — never use string formatting in SQL
- Passwords hashed with werkzeug (no changes to auth logic in this step)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- `amount` must be validated as a positive float (`> 0`); reject on invalid format
  or zero/negative value with a user-facing error message
- `category` must be one of the seven fixed options; reject anything else with an
  error message (prevents spoofed form submissions)
- `date` must be a valid `YYYY-MM-DD` string parseable by `date.fromisoformat()`;
  reject invalid values with an error message
- `description` is optional — store `None` if blank
- On validation failure, re-render the form with the error message and the values
  the user already typed (sticky form), using the same field values from
  `request.form`
- Close every database connection in a `finally` block
- Guard both GET and POST with a session check; redirect to login if not logged in

## Definition of done
- [ ] `GET /expenses/add` renders the add-expense form for a logged-in user
- [ ] `GET /expenses/add` redirects to `/login` for an unauthenticated visitor
- [ ] The form's date field defaults to today's date on first load
- [ ] Submitting the form with valid data inserts a row in the `expenses` table for
  the current user and redirects to `/profile?added=1`
- [ ] The profile page shows "Expense added successfully." after the redirect
- [ ] Submitting with a missing or zero/negative amount re-renders the form with an
  error and does not insert a row
- [ ] Submitting with a missing category re-renders the form with an error
- [ ] Submitting with a missing or invalid date re-renders the form with an error
- [ ] Previously entered form values are preserved on validation failure (sticky form)
- [ ] The profile page has a visible "Add expense" link that navigates to the form
- [ ] App starts without errors after all changes
