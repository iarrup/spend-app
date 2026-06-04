import sqlite3
import math
import re
from datetime import datetime, date, timedelta
from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
from database.db import get_db, init_db, seed_db

app = Flask(__name__)
app.secret_key = "dev-secret-change-in-prod"

with app.app_context():
    init_db()
    seed_db()

VALID_CATEGORIES = ["Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other"]


def _preset_ranges():
    today            = date.today()
    first_of_month   = today.replace(day=1)
    last_month_end   = first_of_month - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    return {
        "This month":    (first_of_month.isoformat(), today.isoformat()),
        "Last month":    (last_month_start.isoformat(), last_month_end.isoformat()),
        "Last 3 months": ((today - timedelta(days=90)).isoformat(), today.isoformat()),
        "All time":      ("", ""),
    }


def _parse_date(s):
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    name     = request.form.get("name", "").strip()
    email    = request.form.get("email", "").strip()
    password = request.form.get("password", "")

    if not name or not email or not password:
        return render_template("register.html", error="All fields are required.")
    if len(password) < 8:
        return render_template("register.html", error="Password must be at least 8 characters.")

    password_hash = generate_password_hash(password)

    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, password_hash),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        return render_template("register.html", error="An account with that email already exists.")
    finally:
        conn.close()

    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    email    = request.form.get("email", "").strip()
    password = request.form.get("password", "")

    if not email or not password:
        return render_template("login.html", error="All fields are required.")

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, name, password_hash FROM users WHERE email = ?",
            (email,),
        ).fetchone()
    finally:
        conn.close()

    if row is None or not check_password_hash(row["password_hash"], password):
        return render_template("login.html", error="Invalid email or password.")

    session["user_id"]   = row["id"]
    session["user_name"] = row["name"]
    return redirect(url_for("profile"))


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))


@app.route("/profile")
def profile():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    from_d    = _parse_date(request.args.get("from_date", "").strip())
    to_d      = _parse_date(request.args.get("to_date", "").strip())
    from_date = from_d.isoformat() if from_d else ""
    to_date   = to_d.isoformat()   if to_d   else ""

    clauses = ["user_id = ?"]
    params  = [session["user_id"]]
    if from_d and to_d:
        clauses.append("date BETWEEN ? AND ?")
        params += [from_date, to_date]
    elif from_d:
        clauses.append("date >= ?")
        params.append(from_date)
    elif to_d:
        clauses.append("date <= ?")
        params.append(to_date)
    where = " WHERE " + " AND ".join(clauses)

    conn = get_db()
    try:
        user = conn.execute(
            "SELECT id, name, email, created_at FROM users WHERE id = ?",
            (session["user_id"],),
        ).fetchone()

        stats = conn.execute(
            "SELECT COUNT(*) AS total_count, COALESCE(SUM(amount), 0) AS total_spent"
            " FROM expenses" + where,
            params,
        ).fetchone()

        top_cat_row = conn.execute(
            "SELECT category FROM expenses" + where +
            " GROUP BY category ORDER BY COUNT(*) DESC LIMIT 1",
            params,
        ).fetchone()
    finally:
        conn.close()

    member_since = datetime.strptime(
        user["created_at"], "%Y-%m-%d %H:%M:%S"
    ).strftime("%-d %B %Y")

    if request.args.get("updated"):
        success = "Profile updated successfully."
    elif request.args.get("added"):
        success = "Expense added successfully."
    else:
        success = None

    return render_template(
        "profile.html",
        user=user,
        member_since=member_since,
        total_count=stats["total_count"],
        total_spent=stats["total_spent"],
        top_category=top_cat_row["category"] if top_cat_row else None,
        success=success,
        from_date=from_date,
        to_date=to_date,
        preset_ranges=_preset_ranges(),
    )


@app.route("/profile", methods=["POST"])
def update_profile():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    name             = request.form.get("name", "").strip()
    email            = request.form.get("email", "").strip()
    current_password = request.form.get("current_password", "")
    new_password     = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")

    def render_error(msg):
        conn = get_db()
        try:
            user = conn.execute(
                "SELECT id, name, email, created_at FROM users WHERE id = ?",
                (session["user_id"],),
            ).fetchone()
            stats = conn.execute(
                "SELECT COUNT(*) AS total_count, COALESCE(SUM(amount), 0) AS total_spent"
                " FROM expenses WHERE user_id = ?",
                (session["user_id"],),
            ).fetchone()
            top_cat_row = conn.execute(
                "SELECT category FROM expenses WHERE user_id = ?"
                " GROUP BY category ORDER BY COUNT(*) DESC LIMIT 1",
                (session["user_id"],),
            ).fetchone()
        finally:
            conn.close()
        member_since = datetime.strptime(
            user["created_at"], "%Y-%m-%d %H:%M:%S"
        ).strftime("%-d %B %Y")
        return render_template(
            "profile.html",
            user=user,
            member_since=member_since,
            total_count=stats["total_count"],
            total_spent=stats["total_spent"],
            top_category=top_cat_row["category"] if top_cat_row else None,
            error=msg,
            from_date="",
            to_date="",
            preset_ranges=_preset_ranges(),
        )

    if not name or not email:
        return render_error("Name and email are required.")

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id = ?",
            (session["user_id"],),
        ).fetchone()
    finally:
        conn.close()

    if not check_password_hash(row["password_hash"], current_password):
        return render_error("Current password is incorrect.")

    if new_password:
        if len(new_password) < 8:
            return render_error("New password must be at least 8 characters.")
        if new_password != confirm_password:
            return render_error("New passwords do not match.")
        new_hash = generate_password_hash(new_password)
    else:
        new_hash = row["password_hash"]

    conn = get_db()
    try:
        conn.execute(
            "UPDATE users SET name = ?, email = ?, password_hash = ? WHERE id = ?",
            (name, email, new_hash, session["user_id"]),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        return render_error("That email is already in use by another account.")
    finally:
        conn.close()

    session["user_name"] = name
    return redirect(url_for("profile", updated=1))


@app.route("/profile/delete", methods=["POST"])
def delete_profile():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    password = request.form.get("password", "")
    user_id  = session["user_id"]

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    finally:
        conn.close()

    if not row or not check_password_hash(row["password_hash"], password):
        conn = get_db()
        try:
            user = conn.execute(
                "SELECT id, name, email, created_at FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            stats = conn.execute(
                "SELECT COUNT(*) AS total_count, COALESCE(SUM(amount), 0) AS total_spent"
                " FROM expenses WHERE user_id = ?", (user_id,),
            ).fetchone()
            top_cat_row = conn.execute(
                "SELECT category FROM expenses WHERE user_id = ?"
                " GROUP BY category ORDER BY COUNT(*) DESC LIMIT 1", (user_id,),
            ).fetchone()
        finally:
            conn.close()
        member_since = datetime.strptime(
            user["created_at"], "%Y-%m-%d %H:%M:%S"
        ).strftime("%-d %B %Y")
        return render_template(
            "profile.html",
            user=user,
            member_since=member_since,
            total_count=stats["total_count"],
            total_spent=stats["total_spent"],
            top_category=top_cat_row["category"] if top_cat_row else None,
            delete_error="Incorrect password. Account not deleted.",
            from_date="",
            to_date="",
            preset_ranges=_preset_ranges(),
        )

    conn = get_db()
    try:
        conn.execute("DELETE FROM expenses WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()

    session.clear()
    return redirect(url_for("landing"))


@app.route("/expenses/add", methods=["GET", "POST"])
def add_expense():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    if request.method == "GET":
        return render_template("add_expense.html", categories=VALID_CATEGORIES, today=date.today().isoformat())

    amount_str  = request.form.get("amount", "").strip()
    category    = request.form.get("category", "").strip()
    date_str    = request.form.get("date", "").strip()
    description = request.form.get("description", "").strip() or None

    def render_error(msg):
        return render_template(
            "add_expense.html",
            error=msg,
            categories=VALID_CATEGORIES,
            amount=amount_str,
            category=category,
            date=date_str,
            description=description or "",
            today=date.today().isoformat(),
        )

    try:
        amount = float(amount_str)
        if not math.isfinite(amount) or amount <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return render_error("Amount must be a positive number.")

    if category not in VALID_CATEGORIES:
        return render_error("Please select a valid category.")

    if description and len(description) > 500:
        return render_error("Description must be 500 characters or fewer.")

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
        return render_error("Please enter a valid date.")
    try:
        date.fromisoformat(date_str)
    except ValueError:
        return render_error("Please enter a valid date.")

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
            (session["user_id"], amount, category, date_str, description),
        )
        conn.commit()
    finally:
        conn.close()

    return redirect(url_for("profile", added=1))


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
