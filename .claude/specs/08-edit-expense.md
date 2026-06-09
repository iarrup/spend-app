# Spec: Edit Expense

## Overview
Implement the edit-expense feature so that logged-in users can update any expense
they previously recorded. This step replaces the `GET /expenses/<id>/edit` stub with
a real form-based flow: a GET loads the expense pre-populated, a POST validates and
persists the changes, and the user is redirected back to the profile page with a
confirmation message. Because edit links need to live somewhere, this step also adds
a per-user expense list table to the profile page (respecting the existing date
filter) so that each row has an Edit button. Ownership is enforced at the database
level — users can only edit their own expenses.

## Depends on
- Step 01 — Database Setup (`get_db()`, `expenses` table must exist)
- Step 03 — Login and Logout (session must carry `user_id`)
- Step 05 — Backend Routes for Profile Page (profile page must be in place)
- Step 07 — Add Expense (`expenses` table must have data to edit)

## Routes
- `GET /expenses/<int:id>/edit` — render the edit form pre-populated with the
  expense's current values — logged-in only; 404 if expense not found or belongs to
  another user
- `POST /expenses/<int:id>/edit` — validate and update the expense row, then redirect
  to `/profile?edited=1` — logged-in only; 404 if expense not found or belongs to
  another user

## Database changes
No new tables or columns. The existing `expenses` table (`id`, `user_id`, `amount`,
`category`, `date`, `description`) has all required columns.

## Templates
- **Create:** `templates/edit_expense.html`
  - Extends `base.html`
  - A form with `method="POST"` and `action="{{ url_for('edit_expense', id=expense.id) }}"`
  - Same four fields as `add_expense.html`, pre-populated with the expense's current values:
    - `amount` — `<input type="number" step="0.01" min="0.01">` — required
    - `category` — `<select>` dropdown, current category pre-selected — required
    - `date` — `<input type="date">` — required; pre-populated with expense date
    - `description` — `<textarea>` — optional; pre-populated if set
  - Inline error message block (same `auth-error` class pattern)
  - A "Save changes" submit button
  - A "Cancel" link back to `url_for('profile')`

- **Modify:** `templates/profile.html`
  - Below the stats row, add an expense list table (card-style, same `.profile-card`
    wrapper) with columns: Date, Category, Amount, Description, Actions
  - Each row has an Edit link: `<a href="{{ url_for('edit_expense', id=e.id) }}">Edit</a>`
  - The list respects the existing date filter (uses the `expenses` list passed from
    the route)
  - Show "No expenses yet." if the list is empty
  - Display a success flash when `success` contains "edited" text (reuse the existing
    `success` variable — the route passes the right string)

## Files to change
- `app.py`
  1. Modify the `profile()` GET route to also fetch the filtered expense list and pass
     it as `expenses` to `render_template`. Use the same `where` / `params` already
     built for the stats queries. Add an `ORDER BY date DESC, id DESC` clause.
  2. Detect `request.args.get("edited")` in the `profile()` route and set
     `success = "Expense updated successfully."` (alongside the existing `?updated`
     and `?added` checks).
  3. Replace the `edit_expense` stub with a real view that handles both GET and POST:
     - Both methods: redirect to login if `session.get("user_id")` is falsy; abort
       with 404 if the expense does not exist or `user_id` does not match the session
     - `GET`: query the expense row, render `edit_expense.html` with `expense`,
       `categories`, and `today=date.today().isoformat()`
     - `POST`: read `amount`, `category`, `date`, `description` from `request.form`;
       apply the same validation rules as `add_expense`; UPDATE the row; redirect to
       `url_for('profile', edited=1)`
  4. Change the `edit_expense` route to accept both `GET` and `POST` methods:
     `@app.route("/expenses/<int:id>/edit", methods=["GET", "POST"])`

- `templates/profile.html`
  - Add the expense list table section below `.mock-stat-row`

## Files to create
- `templates/edit_expense.html`

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs — raw `sqlite3` only via `get_db()`
- Parameterised queries only — never use string formatting in SQL
- Passwords hashed with werkzeug (no changes to auth logic in this step)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Ownership check: after fetching the expense, verify `expense["user_id"] == session["user_id"]`; if not, abort with 404 (do not reveal that the expense exists)
- `amount` must be validated as a positive float (`> 0`); reject on invalid format or zero/negative value with a user-facing error message
- `category` must be one of the seven fixed options in `VALID_CATEGORIES`
- `date` must be a valid `YYYY-MM-DD` string parseable by `date.fromisoformat()`
- `description` is optional — store `None` if blank
- On validation failure, re-render `edit_expense.html` with the error and the form values the user submitted (sticky form)
- Close every database connection in a `finally` block
- Use `abort(404)` (import `abort` from `flask`) for missing/unauthorised expenses

## Definition of done
- [ ] `GET /expenses/<id>/edit` renders the edit form pre-populated with the expense's current values for a logged-in owner
- [ ] `GET /expenses/<id>/edit` redirects to `/login` for an unauthenticated visitor
- [ ] `GET /expenses/<id>/edit` returns 404 when the expense does not exist or belongs to another user
- [ ] Submitting the edit form with valid data updates the row in the `expenses` table and redirects to `/profile?edited=1`
- [ ] The profile page shows "Expense updated successfully." after the redirect
- [ ] Submitting with a missing or zero/negative amount re-renders the form with an error and does not update the row
- [ ] Submitting with an invalid category re-renders the form with an error
- [ ] Submitting with a missing or invalid date re-renders the form with an error
- [ ] Previously submitted form values are preserved on validation failure (sticky form)
- [ ] The profile page expense list shows all expenses for the logged-in user (respecting the date filter) with an Edit link per row
- [ ] App starts without errors after all changes
