"""
tests/test_07-add-expense.py

Tests for the Add Expense feature (Spec 07).

Routes under test
-----------------
  GET  /expenses/add  — render the add-expense form (auth required)
  POST /expenses/add  — validate and insert the expense (auth required)

Isolation strategy
------------------
`database.db.get_db` is replaced with a function that opens a shared in-memory
SQLite database for every test.  A module-scoped keeper connection keeps the
named in-memory DB alive across the `conn.close()` calls the route handlers
make in their `finally` blocks.

A fresh test user is registered once per module (via `seeded_user_id`).  Each
test that writes to the DB operates independently: the per-test `auth_client`
fixture injects the session, and DB-side-effect tests query the keeper
connection directly to verify what was (or was not) inserted.

Valid categories accepted by the app (from the spec):
  Food, Transport, Bills, Health, Entertainment, Shopping, Other
"""

import sqlite3
import datetime
import unittest.mock as mock

import pytest
from werkzeug.security import generate_password_hash

import database.db as db_module
from app import app as flask_app

# ---------------------------------------------------------------------------
# Shared in-memory database (named URI so multiple connections share it)
# ---------------------------------------------------------------------------

_TEST_DB_URI = "file:spendly_test_07?mode=memory&cache=shared"
_keeper_conn: sqlite3.Connection | None = None


def _get_keeper_conn() -> sqlite3.Connection:
    """Open (once) and return the keeper connection that keeps the named DB alive."""
    global _keeper_conn
    if _keeper_conn is None:
        _keeper_conn = sqlite3.connect(_TEST_DB_URI, uri=True, check_same_thread=False)
        _keeper_conn.row_factory = sqlite3.Row
        _keeper_conn.execute("PRAGMA foreign_keys = ON")
    return _keeper_conn


def _patched_get_db() -> sqlite3.Connection:
    """Drop-in replacement for app.get_db — opens a fresh connection to the shared test DB."""
    _get_keeper_conn()  # ensure keeper is alive so the DB is not destroyed on close
    conn = sqlite3.connect(_TEST_DB_URI, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ---------------------------------------------------------------------------
# Module-scoped fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def monkeypatch_module():
    """Module-scoped patch replacing get_db with the in-memory test version."""
    patcher = mock.patch("app.get_db", side_effect=_patched_get_db)
    patcher.start()
    yield
    patcher.stop()


@pytest.fixture(scope="module")
def seeded_user_id(monkeypatch_module):
    """
    Creates the schema and inserts one test user.
    Returns the integer user_id of that user.
    The password is 'securepass1'.
    """
    conn = _get_keeper_conn()

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

    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Add Tester", "addtest@example.com", generate_password_hash("securepass1")),
    )
    conn.commit()
    return cur.lastrowid


@pytest.fixture(scope="module")
def app(monkeypatch_module):
    flask_app.config.update({
        "TESTING": True,
        "SECRET_KEY": "test-secret-key-07",
        "WTF_CSRF_ENABLED": False,
    })
    yield flask_app


# ---------------------------------------------------------------------------
# Per-test fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_client(client, seeded_user_id):
    """A test client with the test user already in the session."""
    with client.session_transaction() as sess:
        sess["user_id"]   = seeded_user_id
        sess["user_name"] = "Add Tester"
    return client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get(client, path: str, **kwargs):
    return client.get(path, follow_redirects=False, **kwargs)


def _post(client, path: str, data: dict, **kwargs):
    return client.post(path, data=data, follow_redirects=False, **kwargs)


def _expense_count(user_id: int) -> int:
    """Return the number of expense rows in the test DB for a given user."""
    conn = _get_keeper_conn()
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM expenses WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    return row["cnt"]


def _last_expense(user_id: int):
    """Return the most-recently inserted expense row for a given user, or None."""
    conn = _get_keeper_conn()
    return conn.execute(
        "SELECT * FROM expenses WHERE user_id = ? ORDER BY id DESC LIMIT 1",
        (user_id,),
    ).fetchone()


# ===========================================================================
# 1. Auth guard
# ===========================================================================

class TestAuthGuard:
    def test_get_unauthenticated_redirects_to_login(self, client):
        """GET /expenses/add without a session must redirect to /login."""
        response = _get(client, "/expenses/add")
        assert response.status_code == 302, (
            "Expected 302 redirect for unauthenticated GET /expenses/add"
        )
        assert "/login" in response.headers["Location"], (
            "Expected redirect target to be /login for unauthenticated GET"
        )

    def test_post_unauthenticated_redirects_to_login(self, client):
        """POST /expenses/add without a session must redirect to /login."""
        response = _post(client, "/expenses/add", data={
            "amount": "12.50",
            "category": "Food",
            "date": "2026-06-01",
            "description": "Test",
        })
        assert response.status_code == 302, (
            "Expected 302 redirect for unauthenticated POST /expenses/add"
        )
        assert "/login" in response.headers["Location"], (
            "Expected redirect target to be /login for unauthenticated POST"
        )


# ===========================================================================
# 2. GET — form rendering
# ===========================================================================

class TestGetFormRendering:
    def test_get_returns_200_for_logged_in_user(self, auth_client):
        """GET /expenses/add must return 200 for an authenticated user."""
        response = _get(auth_client, "/expenses/add")
        assert response.status_code == 200, (
            "Expected 200 for authenticated GET /expenses/add"
        )

    def test_get_renders_amount_input(self, auth_client):
        """The form must contain an input for the amount field."""
        response = _get(auth_client, "/expenses/add")
        assert b'name="amount"' in response.data, (
            "Expected input[name='amount'] in add-expense form"
        )

    def test_get_renders_category_input(self, auth_client):
        """The form must contain a category selector."""
        response = _get(auth_client, "/expenses/add")
        assert b'name="category"' in response.data, (
            "Expected input/select[name='category'] in add-expense form"
        )

    def test_get_renders_date_input(self, auth_client):
        """The form must contain a date field."""
        response = _get(auth_client, "/expenses/add")
        assert b'name="date"' in response.data, (
            "Expected input[name='date'] in add-expense form"
        )

    def test_get_renders_description_input(self, auth_client):
        """The form must contain a description field."""
        response = _get(auth_client, "/expenses/add")
        assert b'name="description"' in response.data, (
            "Expected input/textarea[name='description'] in add-expense form"
        )

    def test_get_date_field_defaults_to_today(self, auth_client):
        """The date field must be pre-filled with today's ISO date (YYYY-MM-DD)."""
        today = datetime.date.today().isoformat().encode()
        response = _get(auth_client, "/expenses/add")
        assert today in response.data, (
            f"Expected today's date {today!r} to be pre-filled in the date field"
        )

    def test_get_form_lists_valid_categories(self, auth_client):
        """All seven valid categories must appear as options in the form."""
        valid_categories = [
            b"Food", b"Transport", b"Bills", b"Health",
            b"Entertainment", b"Shopping", b"Other",
        ]
        response = _get(auth_client, "/expenses/add")
        for cat in valid_categories:
            assert cat in response.data, (
                f"Expected category option {cat!r} to appear in add-expense form"
            )

    def test_get_form_has_submit_element(self, auth_client):
        """The form must contain a submit button or input."""
        response = _get(auth_client, "/expenses/add")
        html = response.data
        assert b'type="submit"' in html or b"<button" in html, (
            "Expected a submit element in the add-expense form"
        )


# ===========================================================================
# 3. POST — happy path
# ===========================================================================

class TestPostHappyPath:
    def test_valid_post_redirects_to_profile_with_added_flag(self, auth_client, seeded_user_id):
        """Valid POST must redirect to /profile?added=1."""
        before = _expense_count(seeded_user_id)
        response = _post(auth_client, "/expenses/add", data={
            "amount": "29.99",
            "category": "Food",
            "date": "2026-06-01",
            "description": "Test groceries",
        })
        assert response.status_code == 302, (
            "Expected 302 redirect after successful expense submission"
        )
        location = response.headers["Location"]
        assert "/profile" in location, (
            f"Expected redirect to /profile, got: {location}"
        )
        assert "added=1" in location, (
            f"Expected 'added=1' query parameter in redirect, got: {location}"
        )
        # Verify row was inserted
        after = _expense_count(seeded_user_id)
        assert after == before + 1, (
            f"Expected one new expense row; before={before}, after={after}"
        )

    def test_valid_post_inserts_correct_amount(self, auth_client, seeded_user_id):
        """Inserted row must store the submitted amount as a float."""
        response = _post(auth_client, "/expenses/add", data={
            "amount": "55.50",
            "category": "Transport",
            "date": "2026-06-02",
            "description": "Bus pass",
        })
        assert response.status_code == 302
        row = _last_expense(seeded_user_id)
        assert row is not None, "Expected an expense row to exist after POST"
        assert abs(row["amount"] - 55.50) < 0.001, (
            f"Expected amount 55.50, got {row['amount']}"
        )

    def test_valid_post_inserts_correct_category(self, auth_client, seeded_user_id):
        """Inserted row must store the submitted category exactly."""
        response = _post(auth_client, "/expenses/add", data={
            "amount": "12.00",
            "category": "Bills",
            "date": "2026-06-03",
            "description": "Water bill",
        })
        assert response.status_code == 302
        row = _last_expense(seeded_user_id)
        assert row is not None
        assert row["category"] == "Bills", (
            f"Expected category 'Bills', got {row['category']!r}"
        )

    def test_valid_post_inserts_correct_date(self, auth_client, seeded_user_id):
        """Inserted row must store the submitted date in YYYY-MM-DD format."""
        response = _post(auth_client, "/expenses/add", data={
            "amount": "8.75",
            "category": "Other",
            "date": "2026-06-04",
            "description": "Misc",
        })
        assert response.status_code == 302
        row = _last_expense(seeded_user_id)
        assert row is not None
        assert row["date"] == "2026-06-04", (
            f"Expected date '2026-06-04', got {row['date']!r}"
        )

    def test_valid_post_blank_description_stored_as_none(self, auth_client, seeded_user_id):
        """A blank description must be stored as NULL, not an empty string."""
        response = _post(auth_client, "/expenses/add", data={
            "amount": "5.00",
            "category": "Health",
            "date": "2026-06-05",
            "description": "",
        })
        assert response.status_code == 302
        row = _last_expense(seeded_user_id)
        assert row is not None
        assert row["description"] is None, (
            f"Expected description to be None (NULL), got {row['description']!r}"
        )

    def test_valid_post_stores_description_when_provided(self, auth_client, seeded_user_id):
        """A non-blank description must be stored verbatim."""
        response = _post(auth_client, "/expenses/add", data={
            "amount": "30.00",
            "category": "Entertainment",
            "date": "2026-06-06",
            "description": "Cinema night",
        })
        assert response.status_code == 302
        row = _last_expense(seeded_user_id)
        assert row is not None
        assert row["description"] == "Cinema night", (
            f"Expected description 'Cinema night', got {row['description']!r}"
        )

    def test_valid_post_associates_expense_with_logged_in_user(self, auth_client, seeded_user_id):
        """Inserted row must carry the current user's user_id."""
        response = _post(auth_client, "/expenses/add", data={
            "amount": "18.00",
            "category": "Shopping",
            "date": "2026-06-07",
            "description": "Pen set",
        })
        assert response.status_code == 302
        row = _last_expense(seeded_user_id)
        assert row is not None
        assert row["user_id"] == seeded_user_id, (
            f"Expected user_id {seeded_user_id}, got {row['user_id']}"
        )


# ===========================================================================
# 4. POST — amount validation failures
# ===========================================================================

class TestAmountValidation:
    @pytest.mark.parametrize("bad_amount", [
        "",        # missing
        "0",       # zero
        "0.00",    # zero as float
        "-5",      # negative
        "-0.01",   # small negative
        "abc",     # non-numeric
        "  ",      # whitespace only
        "1e999",   # overflow / non-finite (Python float("1e999") == inf)
    ])
    def test_invalid_amount_rerenders_form_with_200(self, auth_client, bad_amount):
        """Any invalid amount must re-render the form (200), not redirect."""
        response = _post(auth_client, "/expenses/add", data={
            "amount": bad_amount,
            "category": "Food",
            "date": "2026-06-10",
            "description": "Test",
        })
        assert response.status_code == 200, (
            f"Expected 200 (form re-render) for invalid amount {bad_amount!r}, "
            f"got {response.status_code}"
        )

    @pytest.mark.parametrize("bad_amount", ["", "0", "-5", "abc"])
    def test_invalid_amount_shows_error_message(self, auth_client, bad_amount):
        """The re-rendered form must contain an error message for invalid amount."""
        response = _post(auth_client, "/expenses/add", data={
            "amount": bad_amount,
            "category": "Food",
            "date": "2026-06-10",
            "description": "Test",
        })
        html = response.data.decode("utf-8", errors="replace")
        assert "error" in html.lower() or "invalid" in html.lower() or "positive" in html.lower(), (
            f"Expected an error message for invalid amount {bad_amount!r}"
        )

    @pytest.mark.parametrize("bad_amount", ["", "0", "-5", "abc"])
    def test_invalid_amount_does_not_insert_row(self, auth_client, seeded_user_id, bad_amount):
        """No expense row must be inserted when the amount is invalid."""
        before = _expense_count(seeded_user_id)
        _post(auth_client, "/expenses/add", data={
            "amount": bad_amount,
            "category": "Food",
            "date": "2026-06-10",
            "description": "Test",
        })
        after = _expense_count(seeded_user_id)
        assert after == before, (
            f"Expected no new DB row for invalid amount {bad_amount!r}; "
            f"before={before}, after={after}"
        )


# ===========================================================================
# 5. POST — category validation failures
# ===========================================================================

class TestCategoryValidation:
    @pytest.mark.parametrize("bad_category", [
        "",             # missing / blank
        "food",         # wrong case
        "Groceries",    # not in the valid list
        "FOOD",         # all caps
        "Invalid",
        "<script>",     # injection attempt
    ])
    def test_invalid_category_rerenders_form_with_200(self, auth_client, bad_category):
        """An invalid category must cause a form re-render (200)."""
        response = _post(auth_client, "/expenses/add", data={
            "amount": "10.00",
            "category": bad_category,
            "date": "2026-06-10",
            "description": "Test",
        })
        assert response.status_code == 200, (
            f"Expected 200 (form re-render) for invalid category {bad_category!r}, "
            f"got {response.status_code}"
        )

    def test_invalid_category_shows_error_message(self, auth_client):
        """The re-rendered form must contain an error message for invalid category."""
        response = _post(auth_client, "/expenses/add", data={
            "amount": "10.00",
            "category": "Groceries",
            "date": "2026-06-10",
            "description": "Test",
        })
        html = response.data.decode("utf-8", errors="replace")
        assert "error" in html.lower() or "valid" in html.lower() or "category" in html.lower(), (
            "Expected an error message for invalid category"
        )

    @pytest.mark.parametrize("bad_category", ["", "food", "Groceries"])
    def test_invalid_category_does_not_insert_row(self, auth_client, seeded_user_id, bad_category):
        """No expense row must be inserted when the category is invalid."""
        before = _expense_count(seeded_user_id)
        _post(auth_client, "/expenses/add", data={
            "amount": "10.00",
            "category": bad_category,
            "date": "2026-06-10",
            "description": "Test",
        })
        after = _expense_count(seeded_user_id)
        assert after == before, (
            f"Expected no new DB row for invalid category {bad_category!r}; "
            f"before={before}, after={after}"
        )


# ===========================================================================
# 6. POST — date validation failures
# ===========================================================================

class TestDateValidation:
    @pytest.mark.parametrize("bad_date", [
        "",              # missing
        "not-a-date",    # garbage string
        "06/10/2026",    # US format — not ISO
        "2026/06/10",    # slashes instead of dashes
        "2026-99-99",    # out-of-range values
        "20260610",      # no separators
        "tomorrow",      # natural language
    ])
    def test_invalid_date_rerenders_form_with_200(self, auth_client, bad_date):
        """Any invalid date must cause a form re-render (200), not a redirect."""
        response = _post(auth_client, "/expenses/add", data={
            "amount": "10.00",
            "category": "Food",
            "date": bad_date,
            "description": "Test",
        })
        assert response.status_code == 200, (
            f"Expected 200 (form re-render) for invalid date {bad_date!r}, "
            f"got {response.status_code}"
        )

    def test_missing_date_shows_error_message(self, auth_client):
        """The re-rendered form must contain an error message for a missing date."""
        response = _post(auth_client, "/expenses/add", data={
            "amount": "10.00",
            "category": "Food",
            "date": "",
            "description": "Test",
        })
        html = response.data.decode("utf-8", errors="replace")
        assert "error" in html.lower() or "valid" in html.lower() or "date" in html.lower(), (
            "Expected an error message for missing date"
        )

    @pytest.mark.parametrize("bad_date", ["", "not-a-date", "06/10/2026"])
    def test_invalid_date_does_not_insert_row(self, auth_client, seeded_user_id, bad_date):
        """No expense row must be inserted when the date is invalid."""
        before = _expense_count(seeded_user_id)
        _post(auth_client, "/expenses/add", data={
            "amount": "10.00",
            "category": "Food",
            "date": bad_date,
            "description": "Test",
        })
        after = _expense_count(seeded_user_id)
        assert after == before, (
            f"Expected no new DB row for invalid date {bad_date!r}; "
            f"before={before}, after={after}"
        )


# ===========================================================================
# 7. POST — description length validation
# ===========================================================================

class TestDescriptionValidation:
    def test_description_over_500_chars_rerenders_form(self, auth_client):
        """A description longer than 500 characters must re-render the form (200)."""
        long_desc = "A" * 501
        response = _post(auth_client, "/expenses/add", data={
            "amount": "10.00",
            "category": "Food",
            "date": "2026-06-10",
            "description": long_desc,
        })
        assert response.status_code == 200, (
            "Expected 200 (form re-render) when description exceeds 500 chars"
        )

    def test_description_over_500_chars_shows_error(self, auth_client):
        """The re-rendered form must show an error for an over-length description."""
        long_desc = "B" * 501
        response = _post(auth_client, "/expenses/add", data={
            "amount": "10.00",
            "category": "Food",
            "date": "2026-06-10",
            "description": long_desc,
        })
        html = response.data.decode("utf-8", errors="replace")
        assert "error" in html.lower() or "500" in html or "characters" in html.lower(), (
            "Expected an error message for description over 500 characters"
        )

    def test_description_over_500_chars_does_not_insert_row(self, auth_client, seeded_user_id):
        """No expense row must be inserted when description is too long."""
        before = _expense_count(seeded_user_id)
        _post(auth_client, "/expenses/add", data={
            "amount": "10.00",
            "category": "Food",
            "date": "2026-06-10",
            "description": "C" * 501,
        })
        after = _expense_count(seeded_user_id)
        assert after == before, (
            f"Expected no new DB row for over-length description; "
            f"before={before}, after={after}"
        )

    def test_description_exactly_500_chars_is_accepted(self, auth_client, seeded_user_id):
        """A description of exactly 500 characters must be accepted (boundary case)."""
        before = _expense_count(seeded_user_id)
        response = _post(auth_client, "/expenses/add", data={
            "amount": "10.00",
            "category": "Food",
            "date": "2026-06-11",
            "description": "D" * 500,
        })
        assert response.status_code == 302, (
            "Expected redirect (302) for a description of exactly 500 characters"
        )
        after = _expense_count(seeded_user_id)
        assert after == before + 1, (
            "Expected one new expense row for a 500-character description"
        )


# ===========================================================================
# 8. POST — sticky form values on validation failure
# ===========================================================================

class TestStickyFormValues:
    def test_sticky_amount_on_invalid_category(self, auth_client):
        """After a category validation failure, the submitted amount must appear in the form."""
        response = _post(auth_client, "/expenses/add", data={
            "amount": "77.77",
            "category": "BadCategory",
            "date": "2026-06-10",
            "description": "Sticky test",
        })
        assert response.status_code == 200
        assert b"77.77" in response.data, (
            "Expected submitted amount '77.77' to be preserved in re-rendered form"
        )

    def test_sticky_date_on_invalid_amount(self, auth_client):
        """After an amount validation failure, the submitted date must appear in the form."""
        response = _post(auth_client, "/expenses/add", data={
            "amount": "0",
            "category": "Food",
            "date": "2026-03-15",
            "description": "Sticky date test",
        })
        assert response.status_code == 200
        assert b"2026-03-15" in response.data, (
            "Expected submitted date '2026-03-15' to be preserved in re-rendered form"
        )

    def test_sticky_description_on_invalid_date(self, auth_client):
        """After a date validation failure, the submitted description must appear in the form."""
        response = _post(auth_client, "/expenses/add", data={
            "amount": "15.00",
            "category": "Transport",
            "date": "not-a-date",
            "description": "My sticky description",
        })
        assert response.status_code == 200
        assert b"My sticky description" in response.data, (
            "Expected submitted description to be preserved in re-rendered form"
        )

    def test_sticky_category_on_invalid_amount(self, auth_client):
        """After an amount validation failure, the submitted category must appear in the form."""
        response = _post(auth_client, "/expenses/add", data={
            "amount": "-100",
            "category": "Bills",
            "date": "2026-06-10",
            "description": "",
        })
        assert response.status_code == 200
        assert b"Bills" in response.data, (
            "Expected submitted category 'Bills' to be preserved in re-rendered form"
        )

    def test_sticky_all_fields_on_invalid_amount(self, auth_client):
        """All submitted field values must be preserved after a validation failure."""
        response = _post(auth_client, "/expenses/add", data={
            "amount": "abc",
            "category": "Health",
            "date": "2026-07-20",
            "description": "Multi-field sticky check",
        })
        assert response.status_code == 200
        html = response.data
        assert b"abc" in html, "Expected sticky amount 'abc'"
        assert b"Health" in html, "Expected sticky category 'Health'"
        assert b"2026-07-20" in html, "Expected sticky date '2026-07-20'"
        assert b"Multi-field sticky check" in html, "Expected sticky description text"


# ===========================================================================
# 9. Profile page — success message after add
# ===========================================================================

class TestProfileSuccessMessage:
    def test_profile_shows_success_message_when_added_flag_present(self, auth_client):
        """GET /profile?added=1 must display 'Expense added successfully.'."""
        response = _get(auth_client, "/profile?added=1")
        assert response.status_code == 200, (
            "Expected 200 for GET /profile?added=1"
        )
        assert b"Expense added successfully." in response.data, (
            "Expected 'Expense added successfully.' message on profile page when added=1"
        )

    def test_profile_does_not_show_success_message_without_flag(self, auth_client):
        """GET /profile without ?added=1 must NOT show the expense-added message."""
        response = _get(auth_client, "/profile")
        assert response.status_code == 200
        assert b"Expense added successfully." not in response.data, (
            "Expected no 'Expense added successfully.' on profile without ?added=1"
        )


# ===========================================================================
# 10. Profile page — "Add expense" link
# ===========================================================================

class TestProfileAddExpenseLink:
    def test_profile_has_add_expense_link_href(self, auth_client):
        """The profile page must contain a link whose href points to /expenses/add."""
        response = _get(auth_client, "/profile")
        assert response.status_code == 200
        assert b"/expenses/add" in response.data, (
            "Expected a link to /expenses/add on the profile page"
        )

    def test_profile_add_expense_link_is_an_anchor_tag(self, auth_client):
        """The /expenses/add link on the profile page must be an <a> element."""
        response = _get(auth_client, "/profile")
        html = response.data.decode("utf-8")
        idx = html.find("/expenses/add")
        assert idx != -1, "Expected /expenses/add to appear in profile page HTML"
        # Look backwards for the nearest opening tag character
        preceding = html[:idx]
        last_tag_open = preceding.rfind("<")
        tag_snippet = html[last_tag_open: last_tag_open + 2]
        assert tag_snippet == "<a", (
            "Expected /expenses/add to appear inside an <a> element on the profile page"
        )

    def test_profile_add_expense_link_has_descriptive_text(self, auth_client):
        """The Add expense link must contain human-readable text (case-insensitive)."""
        response = _get(auth_client, "/profile")
        html = response.data.decode("utf-8").lower()
        assert "add expense" in html or "add an expense" in html or "new expense" in html, (
            "Expected descriptive text like 'Add expense' near the /expenses/add link"
        )
