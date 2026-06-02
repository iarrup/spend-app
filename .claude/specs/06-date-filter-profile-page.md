# Spec: Date Filter for Profile Page

## Overview
Add a date range filter to the profile page so that logged-in users can narrow
the expense summary stats (total count, total amount spent, top category) to a
specific time window. The filter renders as a compact form above the stats row
with two date inputs ("From" and "To") and a submit button. When the form is
submitted the same `GET /profile` route re-renders with filtered stats; no new
routes are needed. A set of preset quick-filter links ("This month", "Last month",
"Last 3 months", "All time") let users apply common ranges without typing dates.

## Depends on
- Step 01 — Database Setup (`get_db()`, `expenses` table must exist)
- Step 03 — Login and Logout (session must carry `user_id`)
- Step 04 — Profile Page Design (`templates/profile.html` and `GET /profile` must be in place)
- Step 05 — Backend Routes for Profile Page (profile page must be fully functional)

## Routes
No new routes. The existing route is extended:
- `GET /profile?from_date=YYYY-MM-DD&to_date=YYYY-MM-DD` — render the profile
  page with expense stats filtered to the given date range — logged-in only

## Database changes
No database changes. Adds optional `WHERE date BETWEEN ? AND ?` clauses to the
two existing expense queries that already run inside `GET /profile`.

## Templates
- **Modify:** `templates/profile.html`
  1. Add a **date filter form** above the stats row:
     - Two `<input type="date">` fields: `from_date` and `to_date`
     - A "Filter" submit button
     - Pre-populated with the current filter values from the request (so the
       chosen dates remain visible after the page reloads)
     - Method `GET`, action `url_for('profile')`
  2. Add **preset quick-filter links** beside or below the date inputs:
     - "This month", "Last month", "Last 3 months", "All time"
     - Each is a plain `<a>` tag that constructs the correct `?from_date=&to_date=`
       query string using Jinja2 — the dates are computed in the route and passed
       to the template as `preset_ranges` (a dict of label → (from_date, to_date))
  3. Display the **active filter label** (e.g. "Showing: May 2026") in a small
     subheading above the stats cards when a filter is active; omit when showing
     all time
  4. No changes to the edit-profile form or delete-account section

## Files to change
- `app.py` — extend the `profile()` route function:
  1. Read `from_date` and `to_date` from `request.args`; strip and default to
     empty string if absent
  2. Validate format: if either value is non-empty and does not match
     `YYYY-MM-DD`, ignore it (treat as "no filter") rather than crashing
  3. Build the two expense queries conditionally:
     - If both dates are valid and non-empty: add `AND date BETWEEN ? AND ?`
     - If only `from_date`: add `AND date >= ?`
     - If only `to_date`: add `AND date <= ?`
     - If neither: run queries unchanged (current behaviour)
  4. Compute `preset_ranges` — a dict of five entries built using `datetime` and
     `date.today()`:
     - `"This month"` → first day of current month to today
     - `"Last month"` → first and last day of previous calendar month
     - `"Last 3 months"` → 90 days ago to today
     - `"All time"` → empty strings (no filter)
  5. Pass `from_date`, `to_date`, and `preset_ranges` to `render_template`

## Files to create
None.

## New dependencies
No new pip packages. Uses:
- `datetime.date`, `datetime.timedelta` (stdlib, already imported)

## Rules for implementation
- No SQLAlchemy or ORMs — raw `sqlite3` only via `get_db()`
- Parameterised queries only — never use string formatting in SQL
- Passwords hashed with werkzeug (no changes to auth logic)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Date validation must be done with `datetime.date.fromisoformat()` inside a
  `try/except ValueError` — do not use regex
- Invalid or missing dates silently fall back to "no filter"; never show a 500
- The filter form must use `method="get"` so the URL stays bookmarkable
- Preset links must be `<a>` tags (not buttons) — they navigate via URL, not form
  submission, so JavaScript is not required
- Close every database connection in a `finally` block (no change to existing
  pattern)

## Definition of done
- [ ] Visiting `/profile` with no query params renders the profile page with
  unfiltered stats (existing behaviour preserved, no regression)
- [ ] Visiting `/profile?from_date=2026-05-01&to_date=2026-05-31` renders stats
  filtered to May 2026 (for the demo user: 8 expenses, total ≈ 272.89, top
  category "Food")
- [ ] Visiting `/profile?from_date=2026-05-10&to_date=2026-05-18` shows only
  expenses in that window (3 for the demo user: 15.00, 67.80, 10.00 → 92.80,
  top category varies)
- [ ] The date filter form is visible on the profile page and pre-populated with
  the current filter values after submission
- [ ] Clicking "This month" loads the profile with the correct from/to dates for
  the current calendar month
- [ ] Clicking "All time" loads the profile with no date params and unfiltered stats
- [ ] Supplying a malformed date (e.g. `?from_date=not-a-date`) does not crash
  the app — stats fall back to unfiltered
- [ ] Supplying only `from_date` filters to expenses on or after that date
- [ ] Supplying only `to_date` filters to expenses on or before that date
- [ ] The active filter label ("Showing: …") appears when a date filter is active
  and is absent when viewing all time
- [ ] App starts without errors after all changes
