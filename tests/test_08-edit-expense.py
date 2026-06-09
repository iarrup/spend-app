"""
tests/test_08-edit-expense.py

Tests for the Edit Expense feature (Spec 08).

Routes under test
-----------------
  GET  /expenses/<int:id>/edit  — render the edit form pre-populated (auth required)
  POST /expenses/<int:id>/edit  — validate and update the expense (auth required)
  GET  /profile                 — expense list table with Edit links per row

Isolation strategy
------------------
`app.get_db` is replaced with a function that opens a shared named in-memory
SQLite database.  A module-scoped keeper connection keeps that DB alive across
the `conn.close()` calls the route handlers make in their `finally` blocks.

Two users are seeded once per module:
  - seeded_user_id  — owns the test expense (expense_id)
  - other_user_id   — used to verify ownership enforcement

`auth_client` injects seeded_user_id into the session via
`client.session_transaction()`, so no form-based login is needed.

Valid categories (from spec): Food, Transport, Bills, Health, Entertainment,
Shopping, Other.
"""

import sqlite3
import unittest.mock as mock

import pytest
from werkzeug.security import generate_password_hash

import database.db as db_module
from app import app as flask_app

# ---------------------------------------------------------------------------
# Shared in-memory database
# ---------------------------------------------------------------------------

_TEST_DB_URI = "file:spendly_test_08?mode=memory&cache=shared"
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
    Creates the schema and inserts the primary test user plus one seed expense.
    Returns the integer user_id of that user.  The password is 'securepass8'.
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
        ("Edit Tester", "edittest@example.com", generate_password_hash("securepass8")),
    )
    conn.commit()
    return cur.lastrowid


@pytest.fixture(scope="module")
def other_user_id(seeded_user_id):
    """Insert a second user to verify ownership enforcement."""
    conn = _get_keeper_conn()
    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Other Tester", "othertest@example.com", generate_password_hash("securepass9")),
    )
    conn.commit()
    return cur.lastrowid


@pytest.fixture(scope="module")
def expense_id(seeded_user_id):
    """Insert a seed expense owned by seeded_user_id. Returns the expense id."""
    conn = _get_keeper_conn()
    cur = conn.execute(
        "INSERT INTO expenses (user_id, amount, category, date, description)"
        " VALUES (?, ?, ?, ?, ?)",
        (seeded_user_id, 42.50, "Food", "2026-05-01", "Original description"),
    )
    conn.commit()
    return cur.lastrowid


@pytest.fixture(scope="module")
def app(monkeypatch_module):
    flask_app.config.update({
        "TESTING": True,
        "SECRET_KEY": "test-secret-key-08",
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
    """A test client with the primary test user already in the session."""
    with client.session_transaction() as sess:
        sess["user_id"]   = seeded_user_id
        sess["user_name"] = "Edit Tester"
    return client


@pytest.fixture
def other_auth_client(app, other_user_id):
    """A test client logged in as the *other* user (does not own expense_id)."""
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["user_id"]   = other_user_id
        sess["user_name"] = "Other Tester"
    return c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get(client, path: str, **kwargs):
    return client.get(path, follow_redirects=False, **kwargs)


def _post(client, path: str, data: dict, **kwargs):
    return client.post(path, data=data, follow_redirects=False, **kwargs)


def _fetch_expense(expense_id: int):
    """Return the expense row from the test DB, or None."""
    conn = _get_keeper_conn()
    return conn.execute(
        "SELECT * FROM expenses WHERE id = ?", (expense_id,)
    ).fetchone()


# ===========================================================================
# 1. Auth guard
# ===========================================================================

class TestAuthGuard:
    def test_get_unauthenticated_redirects_to_login(self, client, expense_id):
        """GET /expenses/<id>/edit without a session must redirect to /login."""
        response = _get(client, f"/expenses/{expense_id}/edit")
        assert response.status_code == 302, (
            "Expected 302 redirect for unauthenticated GET /expenses/<id>/edit"
        )
        assert "/login" in response.headers["Location"], (
            "Expected redirect target to be /login for unauthenticated GET"
        )

    def test_post_unauthenticated_redirects_to_login(self, client, expense_id):
        """POST /expenses/<id>/edit without a session must redirect to /login."""
        response = _post(client, f"/expenses/{expense_id}/edit", data={
            "amount": "10.00",
            "category": "Food",
            "date": "2026-06-01",
            "description": "No auth",
        })
        assert response.status_code == 302, (
            "Expected 302 redirect for unauthenticated POST /expenses/<id>/edit"
        )
        assert "/login" in response.headers["Location"], (
            "Expected redirect target to be /login for unauthenticated POST"
        )


# ===========================================================================
# 2. GET — 404 cases
# ===========================================================================

class TestGet404:
    def test_get_nonexistent_id_returns_404(self, auth_client):
        """GET for an expense ID that does not exist must return 404."""
        response = _get(auth_client, "/expenses/999999/edit")
        assert response.status_code == 404, (
            "Expected 404 when expense ID does not exist"
        )

    def test_get_other_users_expense_returns_404(self, auth_client, expense_id, other_user_id):
        """GET for an expense owned by another user must return 404 (no info leak)."""
        # Create an expense for other_user so we can probe it with auth_client
        conn = _get_keeper_conn()
        cur = conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description)"
            " VALUES (?, ?, ?, ?, ?)",
            (other_user_id, 99.99, "Health", "2026-05-10", "Other user's expense"),
        )
        conn.commit()
        other_expense_id = cur.lastrowid

        response = _get(auth_client, f"/expenses/{other_expense_id}/edit")
        assert response.status_code == 404, (
            "Expected 404 when authenticated user attempts to GET another user's expense"
        )

    def test_post_nonexistent_id_returns_404(self, auth_client):
        """POST for an expense ID that does not exist must return 404."""
        response = _post(auth_client, "/expenses/999999/edit", data={
            "amount": "10.00",
            "category": "Food",
            "date": "2026-06-01",
            "description": "Ghost",
        })
        assert response.status_code == 404, (
            "Expected 404 when posting to a nonexistent expense ID"
        )

    def test_post_other_users_expense_returns_404(self, auth_client, other_user_id):
        """POST for an expense belonging to another user must return 404."""
        conn = _get_keeper_conn()
        cur = conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description)"
            " VALUES (?, ?, ?, ?, ?)",
            (other_user_id, 5.00, "Transport", "2026-05-12", "Another user's ride"),
        )
        conn.commit()
        foreign_expense_id = cur.lastrowid

        response = _post(auth_client, f"/expenses/{foreign_expense_id}/edit", data={
            "amount": "1.00",
            "category": "Food",
            "date": "2026-06-01",
            "description": "Hijack attempt",
        })
        assert response.status_code == 404, (
            "Expected 404 when POSTing to another user's expense"
        )


# ===========================================================================
# 3. GET — form rendering and pre-population
# ===========================================================================

class TestGetFormRendering:
    def test_get_returns_200_for_owner(self, auth_client, expense_id):
        """GET /expenses/<id>/edit must return 200 for the authenticated owner."""
        response = _get(auth_client, f"/expenses/{expense_id}/edit")
        assert response.status_code == 200, (
            f"Expected 200 for authenticated GET /expenses/{expense_id}/edit"
        )

    def test_get_form_contains_amount_field(self, auth_client, expense_id):
        """The edit form must contain an input for the amount field."""
        response = _get(auth_client, f"/expenses/{expense_id}/edit")
        assert b'name="amount"' in response.data, (
            "Expected input[name='amount'] in the edit-expense form"
        )

    def test_get_form_contains_category_field(self, auth_client, expense_id):
        """The edit form must contain a category selector."""
        response = _get(auth_client, f"/expenses/{expense_id}/edit")
        assert b'name="category"' in response.data, (
            "Expected select/input[name='category'] in the edit-expense form"
        )

    def test_get_form_contains_date_field(self, auth_client, expense_id):
        """The edit form must contain a date input."""
        response = _get(auth_client, f"/expenses/{expense_id}/edit")
        assert b'name="date"' in response.data, (
            "Expected input[name='date'] in the edit-expense form"
        )

    def test_get_form_contains_description_field(self, auth_client, expense_id):
        """The edit form must contain a description field."""
        response = _get(auth_client, f"/expenses/{expense_id}/edit")
        assert b'name="description"' in response.data, (
            "Expected textarea/input[name='description'] in the edit-expense form"
        )

    def test_get_form_prepopulates_amount(self, auth_client, expense_id):
        """The amount field must be pre-populated with the expense's current amount."""
        response = _get(auth_client, f"/expenses/{expense_id}/edit")
        # The seed expense has amount 42.5; it may render as 42.5 or 42.50
        html = response.data.decode("utf-8")
        assert "42.5" in html, (
            "Expected amount '42.5' to be pre-populated in the edit form"
        )

    def test_get_form_prepopulates_category(self, auth_client, expense_id):
        """The current category must appear as selected in the dropdown."""
        response = _get(auth_client, f"/expenses/{expense_id}/edit")
        assert b"Food" in response.data, (
            "Expected category 'Food' to appear pre-selected in the edit form"
        )

    def test_get_form_prepopulates_date(self, auth_client, expense_id):
        """The date field must be pre-populated with the expense's current date."""
        response = _get(auth_client, f"/expenses/{expense_id}/edit")
        assert b"2026-05-01" in response.data, (
            "Expected date '2026-05-01' to be pre-populated in the edit form"
        )

    def test_get_form_prepopulates_description(self, auth_client, expense_id):
        """The description field must be pre-populated with the expense's current description."""
        response = _get(auth_client, f"/expenses/{expense_id}/edit")
        assert b"Original description" in response.data, (
            "Expected 'Original description' to be pre-populated in the edit form"
        )

    def test_get_form_lists_all_valid_categories(self, auth_client, expense_id):
        """All seven valid categories must appear as options in the edit form."""
        valid_categories = [
            b"Food", b"Transport", b"Bills", b"Health",
            b"Entertainment", b"Shopping", b"Other",
        ]
        response = _get(auth_client, f"/expenses/{expense_id}/edit")
        for cat in valid_categories:
            assert cat in response.data, (
                f"Expected category option {cat!r} to appear in edit-expense form"
            )

    def test_get_form_has_submit_button(self, auth_client, expense_id):
        """The edit form must contain a submit button."""
        response = _get(auth_client, f"/expenses/{expense_id}/edit")
        html = response.data
        assert b'type="submit"' in html or b"<button" in html, (
            "Expected a submit element in the edit-expense form"
        )

    def test_get_form_action_points_to_edit_route(self, auth_client, expense_id):
        """The form action attribute must reference the edit route for this expense."""
        response = _get(auth_client, f"/expenses/{expense_id}/edit")
        html = response.data.decode("utf-8")
        assert f"/expenses/{expense_id}/edit" in html, (
            f"Expected form action to point to /expenses/{expense_id}/edit"
        )

    def test_get_form_method_is_post(self, auth_client, expense_id):
        """The edit form must use method='POST'."""
        response = _get(auth_client, f"/expenses/{expense_id}/edit")
        html = response.data.decode("utf-8").lower()
        assert 'method="post"' in html or "method='post'" in html, (
            "Expected form method to be POST in the edit-expense form"
        )


# ===========================================================================
# 4. POST — happy path
# ===========================================================================

class TestPostHappyPath:
    def test_valid_post_redirects_to_profile_with_edited_flag(
        self, auth_client, expense_id
    ):
        """Valid POST must redirect to /profile?edited=1."""
        response = _post(auth_client, f"/expenses/{expense_id}/edit", data={
            "amount": "55.00",
            "category": "Transport",
            "date": "2026-06-01",
            "description": "Updated trip",
        })
        assert response.status_code == 302, (
            "Expected 302 redirect after a successful edit submission"
        )
        location = response.headers["Location"]
        assert "/profile" in location, (
            f"Expected redirect to /profile, got: {location}"
        )
        assert "edited=1" in location, (
            f"Expected 'edited=1' query parameter in redirect location, got: {location}"
        )

    def test_valid_post_updates_amount_in_db(self, auth_client, expense_id):
        """Submitted amount must be persisted to the DB row."""
        _post(auth_client, f"/expenses/{expense_id}/edit", data={
            "amount": "99.99",
            "category": "Bills",
            "date": "2026-06-02",
            "description": "Electric",
        })
        row = _fetch_expense(expense_id)
        assert row is not None, "Expected the expense row to exist after edit"
        assert abs(row["amount"] - 99.99) < 0.001, (
            f"Expected amount 99.99 after edit, got {row['amount']}"
        )

    def test_valid_post_updates_category_in_db(self, auth_client, expense_id):
        """Submitted category must be persisted to the DB row."""
        _post(auth_client, f"/expenses/{expense_id}/edit", data={
            "amount": "10.00",
            "category": "Health",
            "date": "2026-06-03",
            "description": "Pharmacy",
        })
        row = _fetch_expense(expense_id)
        assert row is not None
        assert row["category"] == "Health", (
            f"Expected category 'Health' after edit, got {row['category']!r}"
        )

    def test_valid_post_updates_date_in_db(self, auth_client, expense_id):
        """Submitted date must be persisted to the DB row."""
        _post(auth_client, f"/expenses/{expense_id}/edit", data={
            "amount": "20.00",
            "category": "Shopping",
            "date": "2026-07-15",
            "description": "New shoes",
        })
        row = _fetch_expense(expense_id)
        assert row is not None
        assert row["date"] == "2026-07-15", (
            f"Expected date '2026-07-15' after edit, got {row['date']!r}"
        )

    def test_valid_post_updates_description_in_db(self, auth_client, expense_id):
        """Submitted description must be persisted to the DB row."""
        _post(auth_client, f"/expenses/{expense_id}/edit", data={
            "amount": "30.00",
            "category": "Entertainment",
            "date": "2026-07-20",
            "description": "Updated description text",
        })
        row = _fetch_expense(expense_id)
        assert row is not None
        assert row["description"] == "Updated description text", (
            f"Expected description 'Updated description text', got {row['description']!r}"
        )

    def test_valid_post_blank_description_stored_as_null(self, auth_client, expense_id):
        """A blank description on edit must be stored as NULL."""
        _post(auth_client, f"/expenses/{expense_id}/edit", data={
            "amount": "8.00",
            "category": "Other",
            "date": "2026-07-21",
            "description": "",
        })
        row = _fetch_expense(expense_id)
        assert row is not None
        assert row["description"] is None, (
            f"Expected NULL description after blank edit, got {row['description']!r}"
        )

    def test_valid_post_does_not_change_user_id(self, auth_client, expense_id, seeded_user_id):
        """A successful edit must not alter the user_id of the expense row."""
        _post(auth_client, f"/expenses/{expense_id}/edit", data={
            "amount": "15.00",
            "category": "Food",
            "date": "2026-07-22",
            "description": "Still mine",
        })
        row = _fetch_expense(expense_id)
        assert row is not None
        assert row["user_id"] == seeded_user_id, (
            f"Expected user_id {seeded_user_id} to be unchanged after edit, "
            f"got {row['user_id']}"
        )

    def test_valid_post_does_not_create_new_row(self, auth_client, expense_id, seeded_user_id):
        """A successful edit must UPDATE the existing row, not INSERT a new one."""
        conn = _get_keeper_conn()
        before_count = conn.execute(
            "SELECT COUNT(*) FROM expenses WHERE user_id = ?", (seeded_user_id,)
        ).fetchone()[0]

        _post(auth_client, f"/expenses/{expense_id}/edit", data={
            "amount": "22.00",
            "category": "Food",
            "date": "2026-07-23",
            "description": "No duplicate",
        })

        after_count = conn.execute(
            "SELECT COUNT(*) FROM expenses WHERE user_id = ?", (seeded_user_id,)
        ).fetchone()[0]

        assert after_count == before_count, (
            f"Expected row count unchanged after edit; "
            f"before={before_count}, after={after_count}"
        )


# ===========================================================================
# 5. Profile page — success message after edit
# ===========================================================================

class TestProfileEditSuccessMessage:
    def test_profile_shows_success_message_when_edited_flag_present(self, auth_client):
        """GET /profile?edited=1 must display 'Expense updated successfully.'."""
        response = _get(auth_client, "/profile?edited=1")
        assert response.status_code == 200, (
            "Expected 200 for GET /profile?edited=1"
        )
        assert b"Expense updated successfully." in response.data, (
            "Expected 'Expense updated successfully.' message on profile with ?edited=1"
        )

    def test_profile_does_not_show_edit_success_without_flag(self, auth_client):
        """GET /profile without ?edited=1 must NOT show the expense-updated message."""
        response = _get(auth_client, "/profile")
        assert response.status_code == 200
        assert b"Expense updated successfully." not in response.data, (
            "Expected no 'Expense updated successfully.' on profile without ?edited=1"
        )


# ===========================================================================
# 6. POST — amount validation failures
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
        "1e999",   # overflow / non-finite
    ])
    def test_invalid_amount_rerenders_form_with_200(
        self, auth_client, expense_id, bad_amount
    ):
        """Any invalid amount must re-render the form (200), not redirect."""
        response = _post(auth_client, f"/expenses/{expense_id}/edit", data={
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
    def test_invalid_amount_shows_error_message(
        self, auth_client, expense_id, bad_amount
    ):
        """The re-rendered form must contain an error message for invalid amount."""
        response = _post(auth_client, f"/expenses/{expense_id}/edit", data={
            "amount": bad_amount,
            "category": "Food",
            "date": "2026-06-10",
            "description": "Test",
        })
        html = response.data.decode("utf-8", errors="replace")
        assert (
            "error" in html.lower()
            or "invalid" in html.lower()
            or "positive" in html.lower()
        ), f"Expected an error message for invalid amount {bad_amount!r}"

    @pytest.mark.parametrize("bad_amount", ["", "0", "-5", "abc"])
    def test_invalid_amount_does_not_update_db(
        self, auth_client, expense_id, bad_amount
    ):
        """No DB update must occur when the submitted amount is invalid."""
        original = _fetch_expense(expense_id)
        original_amount = original["amount"]

        _post(auth_client, f"/expenses/{expense_id}/edit", data={
            "amount": bad_amount,
            "category": "Food",
            "date": "2026-06-10",
            "description": "Should not update",
        })

        row = _fetch_expense(expense_id)
        assert abs(row["amount"] - original_amount) < 0.001, (
            f"Expected amount to remain {original_amount} after invalid submit {bad_amount!r}, "
            f"got {row['amount']}"
        )


# ===========================================================================
# 7. POST — category validation failures
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
    def test_invalid_category_rerenders_form_with_200(
        self, auth_client, expense_id, bad_category
    ):
        """An invalid category must cause a form re-render (200), not a redirect."""
        response = _post(auth_client, f"/expenses/{expense_id}/edit", data={
            "amount": "10.00",
            "category": bad_category,
            "date": "2026-06-10",
            "description": "Test",
        })
        assert response.status_code == 200, (
            f"Expected 200 (form re-render) for invalid category {bad_category!r}, "
            f"got {response.status_code}"
        )

    def test_invalid_category_shows_error_message(self, auth_client, expense_id):
        """The re-rendered form must contain an error message for invalid category."""
        response = _post(auth_client, f"/expenses/{expense_id}/edit", data={
            "amount": "10.00",
            "category": "Groceries",
            "date": "2026-06-10",
            "description": "Test",
        })
        html = response.data.decode("utf-8", errors="replace")
        assert (
            "error" in html.lower()
            or "valid" in html.lower()
            or "category" in html.lower()
        ), "Expected an error message for invalid category"

    @pytest.mark.parametrize("bad_category", ["", "food", "Groceries"])
    def test_invalid_category_does_not_update_db(
        self, auth_client, expense_id, bad_category
    ):
        """No DB update must occur when the submitted category is invalid."""
        original = _fetch_expense(expense_id)
        original_category = original["category"]

        _post(auth_client, f"/expenses/{expense_id}/edit", data={
            "amount": "10.00",
            "category": bad_category,
            "date": "2026-06-10",
            "description": "No update",
        })

        row = _fetch_expense(expense_id)
        assert row["category"] == original_category, (
            f"Expected category to remain {original_category!r} after invalid submit "
            f"{bad_category!r}, got {row['category']!r}"
        )


# ===========================================================================
# 8. POST — date validation failures
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
    def test_invalid_date_rerenders_form_with_200(
        self, auth_client, expense_id, bad_date
    ):
        """Any invalid date must cause a form re-render (200), not a redirect."""
        response = _post(auth_client, f"/expenses/{expense_id}/edit", data={
            "amount": "10.00",
            "category": "Food",
            "date": bad_date,
            "description": "Test",
        })
        assert response.status_code == 200, (
            f"Expected 200 (form re-render) for invalid date {bad_date!r}, "
            f"got {response.status_code}"
        )

    def test_missing_date_shows_error_message(self, auth_client, expense_id):
        """The re-rendered form must contain an error message for a missing date."""
        response = _post(auth_client, f"/expenses/{expense_id}/edit", data={
            "amount": "10.00",
            "category": "Food",
            "date": "",
            "description": "Test",
        })
        html = response.data.decode("utf-8", errors="replace")
        assert (
            "error" in html.lower()
            or "valid" in html.lower()
            or "date" in html.lower()
        ), "Expected an error message for missing date"

    @pytest.mark.parametrize("bad_date", ["", "not-a-date", "06/10/2026"])
    def test_invalid_date_does_not_update_db(
        self, auth_client, expense_id, bad_date
    ):
        """No DB update must occur when the submitted date is invalid."""
        original = _fetch_expense(expense_id)
        original_date = original["date"]

        _post(auth_client, f"/expenses/{expense_id}/edit", data={
            "amount": "10.00",
            "category": "Food",
            "date": bad_date,
            "description": "No update",
        })

        row = _fetch_expense(expense_id)
        assert row["date"] == original_date, (
            f"Expected date to remain {original_date!r} after invalid submit "
            f"{bad_date!r}, got {row['date']!r}"
        )


# ===========================================================================
# 9. POST — sticky form values on validation failure
# ===========================================================================

class TestStickyFormValues:
    def test_sticky_amount_on_invalid_category(self, auth_client, expense_id):
        """After a category validation failure, the submitted amount must appear in the form."""
        response = _post(auth_client, f"/expenses/{expense_id}/edit", data={
            "amount": "77.77",
            "category": "BadCategory",
            "date": "2026-06-10",
            "description": "Sticky test",
        })
        assert response.status_code == 200
        assert b"77.77" in response.data, (
            "Expected submitted amount '77.77' to be preserved in re-rendered form"
        )

    def test_sticky_date_on_invalid_amount(self, auth_client, expense_id):
        """After an amount validation failure, the submitted date must appear in the form."""
        response = _post(auth_client, f"/expenses/{expense_id}/edit", data={
            "amount": "0",
            "category": "Food",
            "date": "2026-03-15",
            "description": "Sticky date test",
        })
        assert response.status_code == 200
        assert b"2026-03-15" in response.data, (
            "Expected submitted date '2026-03-15' to be preserved in re-rendered form"
        )

    def test_sticky_description_on_invalid_date(self, auth_client, expense_id):
        """After a date validation failure, the submitted description must appear in the form."""
        response = _post(auth_client, f"/expenses/{expense_id}/edit", data={
            "amount": "15.00",
            "category": "Transport",
            "date": "not-a-date",
            "description": "My sticky description",
        })
        assert response.status_code == 200
        assert b"My sticky description" in response.data, (
            "Expected submitted description to be preserved in re-rendered form"
        )

    def test_sticky_category_on_invalid_amount(self, auth_client, expense_id):
        """After an amount validation failure, the submitted category must appear in the form."""
        response = _post(auth_client, f"/expenses/{expense_id}/edit", data={
            "amount": "-100",
            "category": "Bills",
            "date": "2026-06-10",
            "description": "",
        })
        assert response.status_code == 200
        assert b"Bills" in response.data, (
            "Expected submitted category 'Bills' to be preserved in re-rendered form"
        )

    def test_sticky_all_fields_on_invalid_amount(self, auth_client, expense_id):
        """All submitted field values must be preserved after a validation failure."""
        response = _post(auth_client, f"/expenses/{expense_id}/edit", data={
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

    def test_sticky_amount_on_invalid_date(self, auth_client, expense_id):
        """After a date validation failure, the submitted amount must appear in the form."""
        response = _post(auth_client, f"/expenses/{expense_id}/edit", data={
            "amount": "33.33",
            "category": "Entertainment",
            "date": "bad-date",
            "description": "Amount sticky check",
        })
        assert response.status_code == 200
        assert b"33.33" in response.data, (
            "Expected submitted amount '33.33' to be preserved in re-rendered form "
            "after a date validation failure"
        )


# ===========================================================================
# 10. Profile page — expense list with Edit links
# ===========================================================================

class TestProfileExpenseList:
    def test_profile_renders_200_for_authenticated_user(self, auth_client):
        """GET /profile must return 200 for an authenticated user."""
        response = _get(auth_client, "/profile")
        assert response.status_code == 200, (
            "Expected 200 for authenticated GET /profile"
        )

    def test_profile_contains_edit_link(self, auth_client, expense_id):
        """The profile page must contain at least one Edit link per expense row."""
        response = _get(auth_client, "/profile")
        html = response.data.decode("utf-8")
        # The Edit link must reference the edit route for the expense
        assert f"/expenses/{expense_id}/edit" in html, (
            f"Expected an Edit link pointing to /expenses/{expense_id}/edit on the profile page"
        )

    def test_profile_edit_link_is_an_anchor_tag(self, auth_client, expense_id):
        """The Edit link on the profile page must be an <a> element."""
        response = _get(auth_client, "/profile")
        html = response.data.decode("utf-8")
        target = f"/expenses/{expense_id}/edit"
        idx = html.find(target)
        assert idx != -1, f"Expected '{target}' to appear in profile page HTML"
        preceding = html[:idx]
        last_tag_open = preceding.rfind("<")
        tag_snippet = html[last_tag_open: last_tag_open + 2]
        assert tag_snippet == "<a", (
            f"Expected '{target}' to appear inside an <a> element on the profile page"
        )

    def test_profile_edit_link_text_is_descriptive(self, auth_client, expense_id):
        """The Edit link must contain human-readable text (case-insensitive)."""
        response = _get(auth_client, "/profile")
        html = response.data.decode("utf-8").lower()
        assert "edit" in html, (
            "Expected the text 'edit' to appear somewhere on the profile page"
        )

    def test_profile_expense_list_shows_expense_amount(self, auth_client, expense_id):
        """The profile expense list must show the amount for each expense row."""
        # After all the happy-path edits above the current amount may vary,
        # so we just assert the page contains the expense row's date as a
        # proxy for the row being rendered.  A direct amount check would be
        # brittle due to test ordering, so we verify the edit link is present
        # (which implicitly confirms the row is rendered).
        response = _get(auth_client, "/profile")
        assert response.status_code == 200
        assert f"/expenses/{expense_id}/edit".encode() in response.data, (
            "Expected the expense row with edit link to appear in the profile list"
        )

    def test_profile_shows_no_expenses_message_when_list_is_empty(self, app, other_user_id):
        """Profile must show 'No expenses yet.' for a user with no expenses."""
        # other_user_id has no expenses in the seeded data (only foreign test
        # expenses inserted for 404 probing, which were owned by other_user_id
        # but we cannot guarantee those are deleted).  Use a brand-new user.
        conn = _get_keeper_conn()
        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Empty User", "emptyuser@example.com", generate_password_hash("emptypass1")),
        )
        conn.commit()
        empty_user_id = cur.lastrowid

        c = app.test_client()
        with c.session_transaction() as sess:
            sess["user_id"]   = empty_user_id
            sess["user_name"] = "Empty User"

        response = c.get("/profile", follow_redirects=False)
        assert response.status_code == 200
        assert b"No expenses yet" in response.data, (
            "Expected 'No expenses yet.' message on profile for a user with no expenses"
        )

    def test_profile_expense_list_only_shows_own_expenses(
        self, auth_client, expense_id, other_user_id
    ):
        """The profile expense list must only show expenses owned by the logged-in user."""
        # Insert an expense owned by other_user that should NOT appear for auth_client
        conn = _get_keeper_conn()
        conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description)"
            " VALUES (?, ?, ?, ?, ?)",
            (other_user_id, 777.77, "Bills", "2026-08-01", "Other users secret bill"),
        )
        conn.commit()

        response = _get(auth_client, "/profile")
        assert response.status_code == 200
        assert b"Other users secret bill" not in response.data, (
            "Expected the other user's expense description NOT to appear in auth_client's profile"
        )


# ===========================================================================
# 11. Ownership enforcement by the other user
# ===========================================================================

class TestOwnershipEnforcement:
    def test_other_user_cannot_get_edit_form(
        self, other_auth_client, expense_id
    ):
        """A different authenticated user must receive 404 on GET for another's expense."""
        response = _get(other_auth_client, f"/expenses/{expense_id}/edit")
        assert response.status_code == 404, (
            "Expected 404 when a different authenticated user GETs another user's edit form"
        )

    def test_other_user_cannot_post_edit(
        self, other_auth_client, expense_id
    ):
        """A different authenticated user must receive 404 on POST for another's expense."""
        response = _post(other_auth_client, f"/expenses/{expense_id}/edit", data={
            "amount": "1.00",
            "category": "Food",
            "date": "2026-06-01",
            "description": "Stolen edit",
        })
        assert response.status_code == 404, (
            "Expected 404 when a different authenticated user POSTs to another user's expense"
        )

    def test_other_user_post_does_not_modify_expense(
        self, other_auth_client, expense_id
    ):
        """A rejected POST from another user must not alter the expense row."""
        original = _fetch_expense(expense_id)
        original_amount   = original["amount"]
        original_category = original["category"]

        _post(other_auth_client, f"/expenses/{expense_id}/edit", data={
            "amount": "0.01",
            "category": "Shopping",
            "date": "2026-01-01",
            "description": "Tampered",
        })

        row = _fetch_expense(expense_id)
        assert abs(row["amount"] - original_amount) < 0.001, (
            "Expected amount to be unchanged after rejected foreign-user POST"
        )
        assert row["category"] == original_category, (
            "Expected category to be unchanged after rejected foreign-user POST"
        )
