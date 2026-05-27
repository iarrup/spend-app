# Spec: Profile Page Design

## Overview
Implement the `/profile` page for logged-in users. The page displays the user's account information (name, email, member since date) alongside a summary of their expense activity (total expenses logged, total amount spent, and most-used category). The route replaces the existing stub and enforces a login guard — unauthenticated visitors are redirected to `/login`. A "Profile" link is added to the navbar for logged-in users so the page is reachable from anywhere in the app.

## Depends on
- Step 01 — Database Setup (`get_db()`, `users` table, `expenses` table must exist)
- Step 02 — Registration (users must exist)
- Step 03 — Login and Logout (session must carry `user_id` and `user_name`)

## Routes
- `GET /profile` — render the profile page with user info and expense summary stats — logged-in only (redirect to `/login` if no session)

## Database changes
No new tables or columns. Reads from existing tables:
- `users(id, name, email, created_at)` — fetch the full user row by `session['user_id']`
- `expenses(user_id, amount, category)` — aggregate stats for the logged-in user:
  - `COUNT(*)` → total number of expenses
  - `SUM(amount)` → total amount spent (default to 0 if no expenses)
  - Most-used category via `GROUP BY category ORDER BY COUNT(*) DESC LIMIT 1`

## Templates
- **Create:** `templates/profile.html` — extends `base.html`; sections:
  1. **Page header** — "My Profile" heading with a short subtitle
  2. **Account card** — displays name, email, and member-since date (format `created_at` as a human-readable date, e.g. "May 1, 2026")
  3. **Stats row** — three stat cards: Total Expenses (count), Total Spent (formatted currency, e.g. "₹ 272.89"), Top Category (string or "—" if no expenses)
- **Modify:** `templates/base.html` — add a "Profile" link inside the `{% if session.user_id %}` block in `nav-links`, between the "Hi, {name}" span and the "Sign out" link

## Files to change
- `app.py` — replace the `/profile` stub with a full implementation:
  1. Add a login guard at the top of the function: if `session.get('user_id')` is falsy, `redirect(url_for('login'))`
  2. Query `users` for the authenticated user's full row
  3. Run the three expense aggregate queries
  4. Pass all values to `render_template('profile.html', ...)`
- `templates/base.html` — add the "Profile" nav link for authenticated users

## Files to create
- `templates/profile.html`

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs — raw `sqlite3` only via `get_db()`
- Parameterised queries only — never use string formatting in SQL
- Passwords hashed with werkzeug (no change needed here, just no plaintext handling)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Login guard uses `session.get('user_id')` (not `session['user_id']`) to avoid `KeyError`
- If the user has no expenses, `total_count` = 0, `total_spent` = 0.0, `top_category` = `None`; the template must handle `None` gracefully (display "—")
- Format currency in the template using Jinja2 (e.g. `"₹ {{ '%.2f'|format(total_spent) }}"`) — no Python-side string formatting
- Format `created_at` (stored as ISO datetime string `"YYYY-MM-DD HH:MM:SS"`) to a readable date using Python's `datetime.strptime` before passing to the template, or format it in the template with a Jinja2 filter
- Close every database connection in a `finally` block
- The profile link in the navbar must use `url_for('profile')` — no hardcoded paths

## Definition of done
- [ ] Visiting `/profile` while logged out redirects to `/login`
- [ ] Visiting `/profile` after logging in as the demo user renders the profile page without errors
- [ ] The profile page displays the correct name ("Demo User") and email ("demo@spendly.com")
- [ ] The member-since date is shown in a human-readable format (not raw ISO string)
- [ ] Total Expenses shows the correct count (8 for the seeded demo user)
- [ ] Total Spent shows the correct sum formatted to 2 decimal places (272.89 for the seeded demo user)
- [ ] Top Category shows the most-used category ("Food" for the seeded demo user, which has 2 entries)
- [ ] A registered user with no expenses sees 0 expenses, ₹ 0.00 spent, and "—" for top category
- [ ] The navbar shows a "Profile" link for logged-in users that navigates to `/profile`
- [ ] The navbar does not show a "Profile" link for logged-out users
- [ ] App starts without errors after all changes
