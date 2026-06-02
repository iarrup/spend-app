"""
tests/test_06-date-filter-profile-page.py

Tests for the date-filter feature on GET /profile (Spec 06).

Isolation strategy
------------------
`database.db.get_db` normally opens a file-based SQLite connection. Every test
in this module replaces that function with one that opens the *same* in-memory
connection, giving full isolation from the real database.  The monkeypatch is
applied at the module level via a session-scoped fixture that seeds a known
corpus of expenses across two calendar months so that date filtering has
deterministic, verifiable effects.

Seed data summary (user_id determined at runtime, stored in fixture state)
--------------------------------------------------------------------------
April 2026 (2 expenses)
  2026-04-10  Food        30.00   April lunch
  2026-04-25  Transport   12.50   Monthly pass

May 2026 (5 expenses)
  2026-05-01  Food        42.00   May groceries
  2026-05-05  Bills       89.99   Electricity
  2026-05-12  Food        18.00   Lunch
  2026-05-20  Shopping    55.00   Shoes
  2026-05-28  Health      25.00   Pharmacy

Totals
  All time   : 7 expenses, 272.49 total, top category Food (3 hits)
  April only : 2 expenses,  42.50 total, top category Food (1) or Transport (1)
  May only   : 5 expenses, 229.99 total, top category Food (2 hits)
  from 2026-05-10 onwards : 3 expenses (05-12, 05-20, 05-28), 98.00 total
  up to 2026-04-30        : 2 expenses, 42.50 total
"""

import sqlite3
import pytest
from werkzeug.security import generate_password_hash

import database.db as db_module
from app import app as flask_app

# ---------------------------------------------------------------------------
# Named shared in-memory DB – multiple connections can open/close safely
# ---------------------------------------------------------------------------
#
# Using a named URI ("file:spendly_test?mode=memory&cache=shared") means all
# connections share the same in-memory database.  The route's `conn.close()`
# in its `finally` block no longer destroys the data because the keeper
# connection below keeps the DB alive for the entire test session.
#
_TEST_DB_URI = "file:spendly_test?mode=memory&cache=shared"
_keeper_conn: sqlite3.Connection | None = None


def _get_keeper_conn() -> sqlite3.Connection:
    """Open (once) and hold the keeper connection that keeps the named DB alive."""
    global _keeper_conn
    if _keeper_conn is None:
        _keeper_conn = sqlite3.connect(_TEST_DB_URI, uri=True, check_same_thread=False)
        _keeper_conn.row_factory = sqlite3.Row
        _keeper_conn.execute("PRAGMA foreign_keys = ON")
    return _keeper_conn


def _patched_get_db() -> sqlite3.Connection:
    """Drop-in replacement for app.get_db — opens a fresh connection to the shared test DB."""
    _get_keeper_conn()  # ensure keeper is open so the DB is not destroyed
    conn = sqlite3.connect(_TEST_DB_URI, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ---------------------------------------------------------------------------
# Module-level seed fixture (runs once; idempotent within the test session)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def seeded_user_id(monkeypatch_module):
    """
    Creates the schema and seed rows in the in-memory DB.
    Returns the integer user_id of the seeded test user.
    """
    conn = _get_keeper_conn()

    # Schema
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT    NOT NULL,
            email         TEXT    UNIQUE NOT NULL,
            password_hash TEXT    NOT NULL,
            created_at    TEXT    DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            amount      REAL    NOT NULL,
            category    TEXT    NOT NULL,
            date        TEXT    NOT NULL,
            description TEXT,
            created_at  TEXT    DEFAULT (datetime('now'))
        )
    """)
    conn.commit()

    # Test user
    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Filter Tester", "filter@test.com", generate_password_hash("testpass123")),
    )
    user_id = cur.lastrowid

    # Seed expenses (spread across April and May 2026)
    seed_expenses = [
        (user_id, 30.00,  "Food",      "2026-04-10", "April lunch"),
        (user_id, 12.50,  "Transport", "2026-04-25", "Monthly pass"),
        (user_id, 42.00,  "Food",      "2026-05-01", "May groceries"),
        (user_id, 89.99,  "Bills",     "2026-05-05", "Electricity"),
        (user_id, 18.00,  "Food",      "2026-05-12", "Lunch"),
        (user_id, 55.00,  "Shopping",  "2026-05-20", "Shoes"),
        (user_id, 25.00,  "Health",    "2026-05-28", "Pharmacy"),
    ]
    conn.executemany(
        "INSERT INTO expenses (user_id, amount, category, date, description)"
        " VALUES (?, ?, ?, ?, ?)",
        seed_expenses,
    )
    conn.commit()

    return user_id


# pytest does not ship a monkeypatch fixture at module scope; build a thin one.
@pytest.fixture(scope="module")
def monkeypatch_module():
    """Module-scoped monkeypatch so we can patch get_db once for the whole module."""
    import unittest.mock as mock
    patcher = mock.patch("app.get_db", side_effect=_patched_get_db)
    patcher.start()
    yield
    patcher.stop()


# ---------------------------------------------------------------------------
# Per-test fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app(monkeypatch_module):
    flask_app.config.update({
        "TESTING": True,
        "SECRET_KEY": "test-secret-key",
        "WTF_CSRF_ENABLED": False,
    })
    yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_client(client, seeded_user_id):
    """Test client with user_id and user_name already in the session."""
    with client.session_transaction() as sess:
        sess["user_id"]   = seeded_user_id
        sess["user_name"] = "Filter Tester"
    return client


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _get(client, path: str, **kwargs):
    return client.get(path, follow_redirects=False, **kwargs)


# ===========================================================================
# 1. Auth guard
# ===========================================================================

class TestAuthGuard:
    def test_unauthenticated_redirects_to_login(self, client):
        """GET /profile without a session must redirect to /login."""
        response = _get(client, "/profile")
        assert response.status_code == 302, (
            "Expected 302 redirect for unauthenticated request to /profile"
        )
        assert "/login" in response.headers["Location"], (
            "Redirect target must be /login"
        )

    def test_unauthenticated_with_date_params_redirects_to_login(self, client):
        """Date params must not bypass the auth guard."""
        response = _get(client, "/profile?from_date=2026-05-01&to_date=2026-05-31")
        assert response.status_code == 302, (
            "Expected 302 even when date params are supplied without auth"
        )
        assert "/login" in response.headers["Location"], (
            "Redirect target must be /login"
        )


# ===========================================================================
# 2. Unfiltered (no query params)
# ===========================================================================

class TestUnfilteredProfile:
    def test_returns_200(self, auth_client):
        response = _get(auth_client, "/profile")
        assert response.status_code == 200, "Expected 200 for authenticated GET /profile"

    def test_total_count_all_expenses(self, auth_client):
        """All 7 seed expenses must appear in the unfiltered count."""
        response = _get(auth_client, "/profile")
        # The template renders total_count as the stat value
        assert b"7" in response.data, (
            "Expected total count of 7 in unfiltered profile page"
        )

    def test_total_spent_all_expenses(self, auth_client):
        """Unfiltered total spent must equal sum of all seed amounts (272.49)."""
        response = _get(auth_client, "/profile")
        assert b"272.49" in response.data, (
            "Expected total spent of 272.49 in unfiltered profile page"
        )

    def test_top_category_is_food(self, auth_client):
        """Food appears 3 times across all seed data — it must be top category."""
        response = _get(auth_client, "/profile")
        assert b"Food" in response.data, (
            "Expected top category 'Food' in unfiltered profile page"
        )

    def test_no_showing_label_when_unfiltered(self, auth_client):
        """The 'Showing:' active-filter label must NOT appear when no filter is active."""
        response = _get(auth_client, "/profile")
        assert b"Showing:" not in response.data, (
            "Expected no 'Showing:' label when viewing all-time (no filter)"
        )


# ===========================================================================
# 3. Both from_date and to_date provided
# ===========================================================================

class TestBothDatesFilter:
    def test_may_only_count(self, auth_client):
        """Filtering to 2026-05-01 – 2026-05-31 must return 5 May expenses."""
        response = _get(
            auth_client, "/profile?from_date=2026-05-01&to_date=2026-05-31"
        )
        assert response.status_code == 200
        assert b"5" in response.data, (
            "Expected 5 expenses for May 2026 filter"
        )

    def test_may_only_total_spent(self, auth_client):
        """May expenses total: 42.00 + 89.99 + 18.00 + 55.00 + 25.00 = 229.99."""
        response = _get(
            auth_client, "/profile?from_date=2026-05-01&to_date=2026-05-31"
        )
        assert b"229.99" in response.data, (
            "Expected total spent of 229.99 for May 2026 filter"
        )

    def test_may_only_top_category_food(self, auth_client):
        """Food appears twice in May (05-01, 05-12) — should be top category."""
        response = _get(
            auth_client, "/profile?from_date=2026-05-01&to_date=2026-05-31"
        )
        assert b"Food" in response.data, (
            "Expected top category 'Food' for May 2026 filter"
        )

    def test_april_only_count(self, auth_client):
        """Filtering to April must return exactly 2 expenses."""
        response = _get(
            auth_client, "/profile?from_date=2026-04-01&to_date=2026-04-30"
        )
        assert response.status_code == 200
        assert b"2" in response.data, (
            "Expected 2 expenses for April 2026 filter"
        )

    def test_april_only_total_spent(self, auth_client):
        """April expenses total: 30.00 + 12.50 = 42.50."""
        response = _get(
            auth_client, "/profile?from_date=2026-04-01&to_date=2026-04-30"
        )
        assert b"42.50" in response.data, (
            "Expected total spent of 42.50 for April 2026 filter"
        )

    def test_range_with_no_expenses_returns_zero_count(self, auth_client):
        """A date range with no expenses must show count 0, not an error."""
        response = _get(
            auth_client, "/profile?from_date=2025-01-01&to_date=2025-12-31"
        )
        assert response.status_code == 200, (
            "Expected 200 even when filtered range contains no expenses"
        )
        assert b"0" in response.data, (
            "Expected count of 0 for a range with no matching expenses"
        )

    def test_showing_label_present_when_both_dates_given(self, auth_client):
        """'Showing:' label must appear when both date params are provided."""
        response = _get(
            auth_client, "/profile?from_date=2026-05-01&to_date=2026-05-31"
        )
        assert b"Showing:" in response.data, (
            "Expected 'Showing:' active-filter label when both dates are supplied"
        )

    def test_boundary_dates_are_inclusive(self, auth_client):
        """Expenses on the exact from_date and to_date boundaries must be included."""
        # 2026-05-01 is the start boundary — the May groceries expense (42.00)
        # 2026-05-01 to 2026-05-01 should match exactly 1 expense
        response = _get(
            auth_client, "/profile?from_date=2026-05-01&to_date=2026-05-01"
        )
        assert response.status_code == 200
        assert b"42.00" in response.data, (
            "Expected boundary date 2026-05-01 to be included in results"
        )


# ===========================================================================
# 4. Only from_date provided
# ===========================================================================

class TestFromDateOnlyFilter:
    def test_from_date_only_count(self, auth_client):
        """from_date=2026-05-10 should match 3 expenses: 05-12, 05-20, 05-28."""
        response = _get(auth_client, "/profile?from_date=2026-05-10")
        assert response.status_code == 200
        assert b"3" in response.data, (
            "Expected 3 expenses on or after 2026-05-10"
        )

    def test_from_date_only_total_spent(self, auth_client):
        """18.00 + 55.00 + 25.00 = 98.00 for expenses from 2026-05-10 onwards."""
        response = _get(auth_client, "/profile?from_date=2026-05-10")
        assert b"98.00" in response.data, (
            "Expected total spent of 98.00 for from_date=2026-05-10"
        )

    def test_from_date_only_showing_label_present(self, auth_client):
        """'Showing:' label must appear when only from_date is provided."""
        response = _get(auth_client, "/profile?from_date=2026-05-10")
        assert b"Showing:" in response.data, (
            "Expected 'Showing:' label when from_date filter is active"
        )

    def test_from_date_at_very_start_returns_all(self, auth_client):
        """from_date earlier than all expenses should return all 7."""
        response = _get(auth_client, "/profile?from_date=2020-01-01")
        assert response.status_code == 200
        assert b"7" in response.data, (
            "Expected all 7 expenses when from_date precedes all records"
        )


# ===========================================================================
# 5. Only to_date provided
# ===========================================================================

class TestToDateOnlyFilter:
    def test_to_date_only_count(self, auth_client):
        """to_date=2026-04-30 should match only 2 April expenses."""
        response = _get(auth_client, "/profile?to_date=2026-04-30")
        assert response.status_code == 200
        assert b"2" in response.data, (
            "Expected 2 expenses on or before 2026-04-30"
        )

    def test_to_date_only_total_spent(self, auth_client):
        """30.00 + 12.50 = 42.50 for expenses up to 2026-04-30."""
        response = _get(auth_client, "/profile?to_date=2026-04-30")
        assert b"42.50" in response.data, (
            "Expected total spent of 42.50 for to_date=2026-04-30"
        )

    def test_to_date_only_showing_label_present(self, auth_client):
        """'Showing:' label must appear when only to_date is provided."""
        response = _get(auth_client, "/profile?to_date=2026-04-30")
        assert b"Showing:" in response.data, (
            "Expected 'Showing:' label when to_date filter is active"
        )

    def test_to_date_after_all_expenses_returns_all(self, auth_client):
        """to_date later than all expenses should return all 7."""
        response = _get(auth_client, "/profile?to_date=2099-12-31")
        assert response.status_code == 200
        assert b"7" in response.data, (
            "Expected all 7 expenses when to_date is beyond all records"
        )


# ===========================================================================
# 6. Malformed / invalid date params
# ===========================================================================

class TestMalformedDateParams:
    @pytest.mark.parametrize("bad_from", [
        "not-a-date",
        "2026-99-99",
        "05/01/2026",
        "2026/05/01",
        "abcdefgh",
        "",
    ])
    def test_malformed_from_date_returns_200_unfiltered(self, auth_client, bad_from):
        """Any malformed from_date must not crash the app; fallback to unfiltered."""
        url = f"/profile?from_date={bad_from}"
        response = _get(auth_client, url)
        assert response.status_code == 200, (
            f"Expected 200 (not 500) for malformed from_date='{bad_from}'"
        )
        # Unfiltered total count should be all 7 expenses
        assert b"7" in response.data, (
            f"Expected unfiltered count of 7 when from_date='{bad_from}' is invalid"
        )

    @pytest.mark.parametrize("bad_to", [
        "not-a-date",
        "2026-13-01",
        "01-05-2026",
        "tomorrow",
    ])
    def test_malformed_to_date_returns_200_unfiltered(self, auth_client, bad_to):
        """Any malformed to_date must not crash the app; fallback to unfiltered."""
        url = f"/profile?to_date={bad_to}"
        response = _get(auth_client, url)
        assert response.status_code == 200, (
            f"Expected 200 (not 500) for malformed to_date='{bad_to}'"
        )
        assert b"7" in response.data, (
            f"Expected unfiltered count of 7 when to_date='{bad_to}' is invalid"
        )

    def test_malformed_both_dates_returns_200_unfiltered(self, auth_client):
        """Both dates malformed — must return 200 with unfiltered stats."""
        response = _get(
            auth_client, "/profile?from_date=bad&to_date=alsoBad"
        )
        assert response.status_code == 200, (
            "Expected 200 when both from_date and to_date are malformed"
        )
        assert b"7" in response.data, (
            "Expected unfiltered count of 7 when both date params are invalid"
        )

    def test_valid_from_date_invalid_to_date_uses_from_only(self, auth_client):
        """Valid from_date with invalid to_date should filter as from_date-only."""
        # from_date=2026-05-10 with bad to_date → treats to_date as absent
        # So only from_date filter applies: 3 expenses (05-12, 05-20, 05-28)
        response = _get(
            auth_client, "/profile?from_date=2026-05-10&to_date=not-valid"
        )
        assert response.status_code == 200, (
            "Expected 200 for valid from_date + invalid to_date"
        )
        assert b"3" in response.data, (
            "Expected from_date-only filter (3 results) when to_date is invalid"
        )


# ===========================================================================
# 7. HTML structure — filter form
# ===========================================================================

class TestFilterFormPresence:
    def test_form_method_is_get(self, auth_client):
        """The date filter form must use method='get'."""
        response = _get(auth_client, "/profile")
        assert b'method="get"' in response.data or b"method=get" in response.data, (
            "Expected date filter form with method='get'"
        )

    def test_from_date_input_present(self, auth_client):
        """The form must contain an input with name='from_date'."""
        response = _get(auth_client, "/profile")
        assert b'name="from_date"' in response.data, (
            "Expected input[name='from_date'] in the date filter form"
        )

    def test_to_date_input_present(self, auth_client):
        """The form must contain an input with name='to_date'."""
        response = _get(auth_client, "/profile")
        assert b'name="to_date"' in response.data, (
            "Expected input[name='to_date'] in the date filter form"
        )

    def test_filter_submit_button_present(self, auth_client):
        """A submit button labelled 'Filter' must be present in the form."""
        response = _get(auth_client, "/profile")
        assert b"Filter" in response.data, (
            "Expected a 'Filter' submit button in the date filter form"
        )

    def test_from_date_input_type_date(self, auth_client):
        """The from_date input must be type='date' for native browser date pickers."""
        response = _get(auth_client, "/profile")
        assert b'type="date"' in response.data, (
            "Expected input type='date' for the date filter inputs"
        )

    def test_filter_form_prepopulated_from_date(self, auth_client):
        """After submitting a from_date, it must appear as value= in the rendered form."""
        response = _get(auth_client, "/profile?from_date=2026-05-01")
        assert b"2026-05-01" in response.data, (
            "Expected from_date value '2026-05-01' to be pre-populated in the form"
        )

    def test_filter_form_prepopulated_to_date(self, auth_client):
        """After submitting a to_date, it must appear as value= in the rendered form."""
        response = _get(auth_client, "/profile?to_date=2026-05-31")
        assert b"2026-05-31" in response.data, (
            "Expected to_date value '2026-05-31' to be pre-populated in the form"
        )

    def test_filter_form_prepopulated_both_dates(self, auth_client):
        """Both from_date and to_date must be pre-populated after a full filter submit."""
        response = _get(
            auth_client, "/profile?from_date=2026-04-01&to_date=2026-04-30"
        )
        assert b"2026-04-01" in response.data, (
            "Expected from_date '2026-04-01' to be pre-populated"
        )
        assert b"2026-04-30" in response.data, (
            "Expected to_date '2026-04-30' to be pre-populated"
        )


# ===========================================================================
# 8. Preset quick-links
# ===========================================================================

class TestPresetQuickLinks:
    def test_this_month_link_present(self, auth_client):
        """'This month' preset link must be present on the profile page."""
        response = _get(auth_client, "/profile")
        assert b"This month" in response.data, (
            "Expected 'This month' preset quick-link on the profile page"
        )

    def test_last_month_link_present(self, auth_client):
        """'Last month' preset link must be present on the profile page."""
        response = _get(auth_client, "/profile")
        assert b"Last month" in response.data, (
            "Expected 'Last month' preset quick-link on the profile page"
        )

    def test_last_3_months_link_present(self, auth_client):
        """'Last 3 months' preset link must be present on the profile page."""
        response = _get(auth_client, "/profile")
        assert b"Last 3 months" in response.data, (
            "Expected 'Last 3 months' preset quick-link on the profile page"
        )

    def test_all_time_link_present(self, auth_client):
        """'All time' preset link must be present on the profile page."""
        response = _get(auth_client, "/profile")
        assert b"All time" in response.data, (
            "Expected 'All time' preset quick-link on the profile page"
        )

    def test_preset_links_are_anchor_tags(self, auth_client):
        """Preset links must be <a> tags (navigable via URL, not form submissions)."""
        response = _get(auth_client, "/profile")
        html = response.data.decode("utf-8")
        # Each preset label should appear inside an <a …> context
        for label in ("This month", "Last month", "Last 3 months", "All time"):
            idx = html.find(label)
            assert idx != -1, f"Preset link '{label}' not found in profile HTML"
            # The nearest preceding tag start should be an <a
            preceding = html[:idx].rfind("<")
            tag_start = html[preceding:preceding + 2]
            assert tag_start == "<a", (
                f"Expected preset '{label}' to be inside an <a> tag, "
                f"found tag start: '{tag_start}'"
            )

    def test_all_time_link_has_no_date_params(self, auth_client):
        """'All time' preset link must point to /profile without date params."""
        response = _get(auth_client, "/profile")
        html = response.data.decode("utf-8")
        # Locate the "All time" link
        idx = html.find("All time")
        assert idx != -1, "Expected 'All time' link in profile HTML"
        # The href for All time should not carry from_date/to_date query params
        href_region = html[max(0, idx - 200):idx]
        # Find the last <a href=" before the label
        a_idx = href_region.rfind('href="')
        assert a_idx != -1, "Expected href attribute near 'All time' link"
        href_value_start = a_idx + len('href="')
        href_value_end = href_region.find('"', href_value_start)
        href = href_region[href_value_start:href_value_end]
        assert "from_date" not in href, (
            f"'All time' link must not include from_date, got href='{href}'"
        )
        assert "to_date" not in href, (
            f"'All time' link must not include to_date, got href='{href}'"
        )

    def test_preset_links_contain_from_date_params(self, auth_client):
        """Non-'All time' preset links must include from_date query params in their href."""
        response = _get(auth_client, "/profile")
        html = response.data.decode("utf-8")
        for label in ("This month", "Last month", "Last 3 months"):
            idx = html.find(label)
            assert idx != -1, f"Preset '{label}' not found"
            # Check in the surrounding 300 chars before the label for the href
            preceding = html[max(0, idx - 300):idx]
            assert "from_date" in preceding, (
                f"Expected 'from_date' in href of preset link '{label}'"
            )


# ===========================================================================
# 9. Active filter label ("Showing:")
# ===========================================================================

class TestShowingLabel:
    def test_showing_label_present_with_both_dates(self, auth_client):
        response = _get(
            auth_client, "/profile?from_date=2026-05-01&to_date=2026-05-31"
        )
        assert b"Showing:" in response.data, (
            "Expected 'Showing:' label when both date params are active"
        )

    def test_showing_label_present_with_from_date_only(self, auth_client):
        response = _get(auth_client, "/profile?from_date=2026-05-01")
        assert b"Showing:" in response.data, (
            "Expected 'Showing:' label when only from_date is active"
        )

    def test_showing_label_present_with_to_date_only(self, auth_client):
        response = _get(auth_client, "/profile?to_date=2026-05-31")
        assert b"Showing:" in response.data, (
            "Expected 'Showing:' label when only to_date is active"
        )

    def test_showing_label_absent_with_no_dates(self, auth_client):
        """No 'Showing:' label when no date filter is active."""
        response = _get(auth_client, "/profile")
        assert b"Showing:" not in response.data, (
            "Expected no 'Showing:' label when viewing all expenses (no filter)"
        )

    def test_showing_label_absent_after_malformed_dates(self, auth_client):
        """Malformed dates fall back to no filter — 'Showing:' must be absent."""
        response = _get(
            auth_client, "/profile?from_date=garbage&to_date=alsogarbagé"
        )
        assert b"Showing:" not in response.data, (
            "Expected no 'Showing:' label when both date params are malformed"
        )

    def test_showing_label_contains_from_date_value(self, auth_client):
        """The 'Showing:' label must include the active from_date value."""
        response = _get(auth_client, "/profile?from_date=2026-05-01&to_date=2026-05-31")
        assert b"2026-05-01" in response.data, (
            "Expected from_date '2026-05-01' to appear in the active filter label"
        )

    def test_showing_label_contains_to_date_value(self, auth_client):
        """The 'Showing:' label must include the active to_date value."""
        response = _get(auth_client, "/profile?from_date=2026-05-01&to_date=2026-05-31")
        assert b"2026-05-31" in response.data, (
            "Expected to_date '2026-05-31' to appear in the active filter label"
        )


# ===========================================================================
# 10. Stats card rendering
# ===========================================================================

class TestStatsCardRendering:
    def test_total_expenses_label_present(self, auth_client):
        """'Total Expenses' stat label must be visible on the profile page."""
        response = _get(auth_client, "/profile")
        assert b"Total Expenses" in response.data, (
            "Expected 'Total Expenses' stat label in profile page HTML"
        )

    def test_total_spent_label_present(self, auth_client):
        """'Total Spent' stat label must be visible on the profile page."""
        response = _get(auth_client, "/profile")
        assert b"Total Spent" in response.data, (
            "Expected 'Total Spent' stat label in profile page HTML"
        )

    def test_top_category_label_present(self, auth_client):
        """'Top Category' stat label must be visible on the profile page."""
        response = _get(auth_client, "/profile")
        assert b"Top Category" in response.data, (
            "Expected 'Top Category' stat label in profile page HTML"
        )

    def test_top_category_dash_when_no_expenses_in_range(self, auth_client):
        """When no expenses match the filter, top category must show '—' (em dash)."""
        response = _get(
            auth_client, "/profile?from_date=2020-01-01&to_date=2020-12-31"
        )
        assert response.status_code == 200
        assert "—".encode("utf-8") in response.data, (
            "Expected '—' placeholder for top category when no expenses match"
        )

    def test_total_spent_formatted_to_two_decimals(self, auth_client):
        """Total spent must be formatted to two decimal places."""
        response = _get(
            auth_client, "/profile?from_date=2026-05-01&to_date=2026-05-31"
        )
        # 229.99 is already two decimals; check the pattern appears
        assert b"229.99" in response.data, (
            "Expected total spent to be formatted as '229.99' (2 decimal places)"
        )
