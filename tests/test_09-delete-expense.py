"""
tests/test_09-delete-expense.py

Tests for the Delete Expense feature (Spec 09).

Routes under test
-----------------
  POST /expenses/<int:id>/delete  — permanently remove a single expense (auth required)
  GET  /profile                   — success banner when ?deleted=1 is present

Isolation strategy
------------------
`app.get_db` is replaced with a function that opens a shared named in-memory
SQLite database.  A module-scoped keeper connection keeps that DB alive across
the `conn.close()` calls the route handlers make in their `finally` blocks.

Two users are seeded once per module:
  - seeded_user_id  — owns the expenses created by the `expense_id` fixture
  - other_user_id   — used to verify ownership enforcement (cannot delete
                      seeded_user_id's expenses, and their own expenses are
                      unaffected by deletes targeting seeded_user_id's rows)

`auth_client` injects seeded_user_id into the session via
`client.session_transaction()`, so no form-based login is needed.
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

_TEST_DB_URI = "file:spendly_test_09?mode=memory&cache=shared"
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
    Creates the schema and inserts the primary test user.
    Returns the integer user_id of that user.
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
            category    TEXT    NOT NULL,
            amount      REAL    NOT NULL,
            date        TEXT    NOT NULL,
            description TEXT,
            created_at  TEXT    DEFAULT (datetime('now'))
        )
    """)
    conn.commit()

    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Delete Tester", "deletetest@example.com", generate_password_hash("securepass9")),
    )
    conn.commit()
    return cur.lastrowid


@pytest.fixture(scope="module")
def other_user_id(seeded_user_id):
    """Insert a second user to verify ownership enforcement."""
    conn = _get_keeper_conn()
    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Other Deleter", "otherdeleter@example.com", generate_password_hash("otherpass9")),
    )
    conn.commit()
    return cur.lastrowid


@pytest.fixture(scope="module")
def app(monkeypatch_module):
    flask_app.config.update({
        "TESTING": True,
        "SECRET_KEY": "test-secret-key-09",
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
        sess["user_id"] = seeded_user_id
        sess["user_name"] = "Delete Tester"
    return client


@pytest.fixture
def other_auth_client(app, other_user_id):
    """A test client logged in as the *other* user (does not own the main test expense)."""
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["user_id"] = other_user_id
        sess["user_name"] = "Other Deleter"
    return c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _post(client, path: str, **kwargs):
    return client.post(path, follow_redirects=False, **kwargs)


def _get(client, path: str, **kwargs):
    return client.get(path, follow_redirects=False, **kwargs)


def _insert_expense(user_id: int, amount: float = 25.00, category: str = "Food",
                    date: str = "2026-06-01", description: str = "Test expense") -> int:
    """Insert an expense owned by user_id and return its id."""
    conn = _get_keeper_conn()
    cur = conn.execute(
        "INSERT INTO expenses (user_id, amount, category, date, description)"
        " VALUES (?, ?, ?, ?, ?)",
        (user_id, amount, category, date, description),
    )
    conn.commit()
    return cur.lastrowid


def _fetch_expense(expense_id: int):
    """Return the expense row from the test DB, or None if it does not exist."""
    conn = _get_keeper_conn()
    return conn.execute(
        "SELECT * FROM expenses WHERE id = ?", (expense_id,)
    ).fetchone()


def _count_expenses(user_id: int) -> int:
    """Return the number of expenses owned by user_id in the test DB."""
    conn = _get_keeper_conn()
    return conn.execute(
        "SELECT COUNT(*) FROM expenses WHERE user_id = ?", (user_id,)
    ).fetchone()[0]


# ===========================================================================
# 1. Auth guard
# ===========================================================================


class TestAuthGuard:
    def test_post_unauthenticated_redirects_to_login(self, client, seeded_user_id):
        """POST /expenses/<id>/delete without a session must redirect to /login."""
        expense_id = _insert_expense(seeded_user_id, description="Auth guard test")
        response = _post(client, f"/expenses/{expense_id}/delete")
        assert response.status_code == 302, (
            "Expected 302 redirect for unauthenticated POST /expenses/<id>/delete"
        )
        assert "/login" in response.headers["Location"], (
            "Expected redirect target to be /login for unauthenticated POST"
        )

    def test_post_unauthenticated_does_not_delete_expense(self, client, seeded_user_id):
        """An unauthenticated POST must not remove any expense from the DB."""
        expense_id = _insert_expense(seeded_user_id, description="Should survive unauthenticated attempt")
        _post(client, f"/expenses/{expense_id}/delete")
        row = _fetch_expense(expense_id)
        assert row is not None, (
            "Expected the expense to still exist after an unauthenticated delete attempt"
        )


# ===========================================================================
# 2. Method guard
# ===========================================================================


class TestMethodGuard:
    def test_get_returns_405(self, auth_client, seeded_user_id):
        """GET /expenses/<id>/delete must return 405 — route is POST only."""
        expense_id = _insert_expense(seeded_user_id, description="Method guard test")
        response = _get(auth_client, f"/expenses/{expense_id}/delete")
        assert response.status_code == 405, (
            "Expected 405 Method Not Allowed for GET /expenses/<id>/delete "
            "(route must be POST only to prevent accidental deletion via link/bookmark)"
        )


# ===========================================================================
# 3. Happy path
# ===========================================================================


class TestHappyPath:
    def test_valid_post_redirects_to_profile_with_deleted_flag(self, auth_client, seeded_user_id):
        """Valid POST by the owner must redirect to /profile?deleted=1."""
        expense_id = _insert_expense(seeded_user_id, description="Redirect check expense")
        response = _post(auth_client, f"/expenses/{expense_id}/delete")
        assert response.status_code == 302, (
            "Expected 302 redirect after a successful delete"
        )
        location = response.headers["Location"]
        assert "/profile" in location, (
            f"Expected redirect to /profile after delete, got: {location}"
        )
        assert "deleted=1" in location, (
            f"Expected 'deleted=1' query parameter in redirect location, got: {location}"
        )

    def test_valid_post_removes_expense_from_db(self, auth_client, seeded_user_id):
        """After a successful delete the expense row must no longer exist in the DB."""
        expense_id = _insert_expense(seeded_user_id, description="Row removal check")
        _post(auth_client, f"/expenses/{expense_id}/delete")
        row = _fetch_expense(expense_id)
        assert row is None, (
            f"Expected expense id={expense_id} to be absent from the DB after deletion"
        )

    def test_valid_post_only_removes_targeted_expense(self, auth_client, seeded_user_id):
        """Deleting one expense must leave all other expenses for the same user intact."""
        keep_id = _insert_expense(seeded_user_id, amount=10.00, description="Keep me")
        delete_id = _insert_expense(seeded_user_id, amount=20.00, description="Delete me")

        _post(auth_client, f"/expenses/{delete_id}/delete")

        assert _fetch_expense(delete_id) is None, (
            f"Expected deleted expense id={delete_id} to be absent from the DB"
        )
        assert _fetch_expense(keep_id) is not None, (
            f"Expected sibling expense id={keep_id} to still exist after deleting id={delete_id}"
        )

    def test_valid_post_does_not_affect_other_users_expenses(
        self, auth_client, seeded_user_id, other_user_id
    ):
        """Deleting an expense must not remove any expense belonging to another user."""
        other_expense_id = _insert_expense(other_user_id, amount=99.00,
                                           description="Other user untouched")
        own_expense_id = _insert_expense(seeded_user_id, amount=15.00,
                                         description="My expense to delete")

        _post(auth_client, f"/expenses/{own_expense_id}/delete")

        assert _fetch_expense(other_expense_id) is not None, (
            "Expected the other user's expense to remain untouched after deleting "
            "a different user's expense"
        )


# ===========================================================================
# 4. Profile page — success banner after deletion
# ===========================================================================


class TestProfileDeleteSuccessMessage:
    def test_profile_shows_success_message_when_deleted_flag_present(self, auth_client):
        """GET /profile?deleted=1 must display 'Expense deleted successfully.'."""
        response = _get(auth_client, "/profile?deleted=1")
        assert response.status_code == 200, (
            "Expected 200 for GET /profile?deleted=1"
        )
        assert b"Expense deleted successfully." in response.data, (
            "Expected 'Expense deleted successfully.' banner on profile with ?deleted=1"
        )

    def test_profile_does_not_show_delete_success_without_flag(self, auth_client):
        """GET /profile without ?deleted=1 must NOT show the expense-deleted message."""
        response = _get(auth_client, "/profile")
        assert response.status_code == 200, (
            "Expected 200 for GET /profile"
        )
        assert b"Expense deleted successfully." not in response.data, (
            "Expected no 'Expense deleted successfully.' message on plain /profile"
        )


# ===========================================================================
# 5. Ownership enforcement — 404 on another user's expense
# ===========================================================================


class TestOwnershipEnforcement:
    def test_post_other_users_expense_returns_404(self, auth_client, other_user_id):
        """POST targeting an expense owned by a different user must return 404."""
        foreign_expense_id = _insert_expense(other_user_id, amount=50.00,
                                             description="Belongs to other user")
        response = _post(auth_client, f"/expenses/{foreign_expense_id}/delete")
        assert response.status_code == 404, (
            "Expected 404 when an authenticated user attempts to delete another user's expense"
        )

    def test_post_other_users_expense_does_not_delete_it(self, auth_client, other_user_id):
        """A rejected ownership POST must not remove the targeted row from the DB."""
        foreign_expense_id = _insert_expense(other_user_id, amount=60.00,
                                             description="Must survive rejected delete")
        _post(auth_client, f"/expenses/{foreign_expense_id}/delete")
        row = _fetch_expense(foreign_expense_id)
        assert row is not None, (
            f"Expected foreign expense id={foreign_expense_id} to still exist "
            "after a rejected ownership delete attempt"
        )

    def test_other_user_cannot_delete_primary_users_expense(
        self, other_auth_client, seeded_user_id
    ):
        """The other authenticated user must receive 404 when targeting seeded_user's expense."""
        expense_id = _insert_expense(seeded_user_id, amount=35.00,
                                     description="Owner protection check")
        response = _post(other_auth_client, f"/expenses/{expense_id}/delete")
        assert response.status_code == 404, (
            "Expected 404 when other_auth_client tries to delete seeded_user's expense"
        )

    def test_other_user_post_does_not_modify_seeded_users_expense_count(
        self, other_auth_client, seeded_user_id
    ):
        """A rejected delete by a foreign user must not reduce seeded_user's expense count."""
        expense_id = _insert_expense(seeded_user_id, amount=40.00,
                                     description="Count preservation check")
        before_count = _count_expenses(seeded_user_id)

        _post(other_auth_client, f"/expenses/{expense_id}/delete")

        after_count = _count_expenses(seeded_user_id)
        assert after_count == before_count, (
            f"Expected seeded_user expense count to remain {before_count} after a "
            f"rejected foreign-user delete; got {after_count}"
        )


# ===========================================================================
# 6. Not-found — 404 on a non-existent expense id
# ===========================================================================


class TestNotFound:
    def test_post_nonexistent_id_returns_404(self, auth_client):
        """POST to a non-existent expense id must return 404."""
        response = _post(auth_client, "/expenses/999999/delete")
        assert response.status_code == 404, (
            "Expected 404 when POSTing to a non-existent expense id"
        )

    def test_post_zero_id_returns_404(self, auth_client):
        """POST to id=0 (never a valid AUTOINCREMENT id) must return 404."""
        # Flask's int converter rejects 0 on some versions; either 404 or 404 via abort is correct.
        response = _post(auth_client, "/expenses/0/delete")
        assert response.status_code in (404, 405), (
            "Expected 404 (or 405 if the router rejects it) for expense id=0"
        )


# ===========================================================================
# 7. DB side effects — row count integrity
# ===========================================================================


class TestDbSideEffects:
    def test_delete_decrements_expense_count_by_exactly_one(self, auth_client, seeded_user_id):
        """After deleting one expense the total count for that user decreases by exactly 1."""
        # Insert two fresh expenses so the count is predictable regardless of test order.
        _insert_expense(seeded_user_id, description="Count base A")
        expense_to_delete = _insert_expense(seeded_user_id, description="Count base B — to delete")

        before_count = _count_expenses(seeded_user_id)
        _post(auth_client, f"/expenses/{expense_to_delete}/delete")
        after_count = _count_expenses(seeded_user_id)

        assert after_count == before_count - 1, (
            f"Expected expense count to decrease by 1 after deletion; "
            f"before={before_count}, after={after_count}"
        )

    def test_deleted_expense_data_is_gone_from_db(self, auth_client, seeded_user_id):
        """The exact row that was deleted must not be retrievable by id after deletion."""
        expense_id = _insert_expense(seeded_user_id, amount=77.77, category="Bills",
                                     date="2026-09-01", description="Unique data check")
        _post(auth_client, f"/expenses/{expense_id}/delete")

        row = _fetch_expense(expense_id)
        assert row is None, (
            f"Expected no row with id={expense_id} after deletion, but SELECT returned a row"
        )
