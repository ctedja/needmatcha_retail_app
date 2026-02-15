from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import psycopg
from dotenv import load_dotenv
from flask import Flask, g, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from psycopg.rows import dict_row


BASE_DIR = Path(__file__).resolve().parent
load_dotenv()


def normalize_database_url(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.setdefault("sslmode", "require")
    sslmode_override = os.getenv("DB_SSLMODE", "").strip()
    if sslmode_override:
        query["sslmode"] = sslmode_override
    # Windows hosts can fail CA discovery in some environments; prefer OS trust store.
    if os.name == "nt" and query.get("sslmode") in {"require", "verify-ca", "verify-full"}:
        query.setdefault("sslrootcert", "system")
    if query.get("sslrootcert") == "system" and query.get("sslmode") == "require":
        query["sslmode"] = "verify-full"
    return urlunparse(parsed._replace(query=urlencode(query)))


RAW_DATABASE_URL = (
    os.getenv("SUPABASE_DB_POOLER_URL")
    or os.getenv("SUPABASE_DB_URL")
    or os.getenv("DATABASE_URL", "")
)
DATABASE_URL = normalize_database_url(RAW_DATABASE_URL) if RAW_DATABASE_URL else ""
DB_ADMIN_PASSWORD = os.getenv("DB_ADMIN_PASSWORD", "")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-insecure-key-change-me")


MENU_ITEMS = [
    {
        "key": "basic_bae",
        "name": "Basic Bae",
        "price_cents": 890,
        "image": "product_basicbae.png",
    },
    {
        "key": "double_bae",
        "name": "Double Bae",
        "price_cents": 1090,
        "image": "product_doublebae.png",
    },
    {
        "key": "queens_tea",
        "name": "Queen's Tea",
        "price_cents": 990,
        "image": "product_queenstea.png",
    },
    {
        "key": "cloud_coco",
        "name": "Cloud Coco",
        "price_cents": 1090,
        "image": "product_cloudcoco.png",
    },
    {
        "key": "sea_my_salt",
        "name": "Sea My Salt",
        "price_cents": 1090,
        "image": "product_seamysalt.png",
    },
    {
        "key": "berry_berry",
        "name": "Berry Berry",
        "price_cents": 1090,
        "image": "product_berryberry.png",
    },
    {
        "key": "purple_puree",
        "name": "Purple Puree",
        "price_cents": 1090,
        "image": "product_purplepuree.png",
    },
    {
        "key": "houji_heaven",
        "name": "Houji Heaven",
        "price_cents": 850,
        "image": "product_houjiheaven.png",
    },
    {
        "key": "sea_salt_houji",
        "name": "Sea Salt Houji",
        "price_cents": 850,
        "image": "product_seasalthouji.png",
    },
    {
        "key": "oat_milk",
        "name": "Oat Milk",
        "price_cents": 50,
        "image": "milk_oat.png",
    },
    {
        "key": "soy_milk",
        "name": "Soy Milk",
        "price_cents": 50,
        "image": "milk_soy.png",
    },    
    {
        "key": "almond_milk",
        "name": "Almond Milk",
        "price_cents": 50,
        "image": "milk_almond.png",
    },
    {
        "key": "sachet",
        "name": "Sachet",
        "price_cents": 3900,
        "image": "sachet.png",
    },
]

MENU_LOOKUP = {item["key"]: item for item in MENU_ITEMS}

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY


def db_admin_authenticated() -> bool:
    return session.get("db_admin_authed") is True


def require_db_admin_api(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        if not db_admin_authenticated():
            return jsonify({"error": "Unauthorized"}), 401
        return func(*args, **kwargs)

    return wrapped


def get_db() -> psycopg.Connection:
    if "db" not in g:
        if not DATABASE_URL:
            raise RuntimeError(
                "Missing database URL. Set SUPABASE_DB_POOLER_URL (recommended) or SUPABASE_DB_URL."
            )
        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        g.db = conn
    return g.db


@app.teardown_appcontext
def close_db(_: object) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    conn = get_db()
    with conn, conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS order_items (
                id BIGSERIAL PRIMARY KEY,
                item_key TEXT NOT NULL,
                item_name TEXT NOT NULL,
                price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
                ordered_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_order_items_ordered_at ON order_items(ordered_at DESC)"
        )


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.route("/")
def index():
    return render_template("index.html", menu_items=MENU_ITEMS)


@app.route("/orders")
def order_history():
    if not db_admin_authenticated():
        return redirect(url_for("orders_login"))
    return render_template("orders.html", menu_items=MENU_ITEMS)


@app.route("/orders-login", methods=["GET", "POST"])
def orders_login():
    if request.method == "GET":
        return render_template("orders_login.html", error=None)

    password = request.form.get("password", "")
    if not DB_ADMIN_PASSWORD:
        return render_template("orders_login.html", error="DB_ADMIN_PASSWORD is not configured."), 500

    if secrets.compare_digest(password, DB_ADMIN_PASSWORD):
        session["db_admin_authed"] = True
        return redirect(url_for("order_history"))

    return render_template("orders_login.html", error="Incorrect password."), 401


@app.post("/orders-logout")
def orders_logout():
    session.pop("db_admin_authed", None)
    return redirect(url_for("index"))


@app.route("/assets/<path:filename>")
def asset_file(filename: str):
    return send_from_directory(BASE_DIR / "assets", filename)


@app.get("/api/orders")
@require_db_admin_api
def get_orders():
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, item_key, item_name, price_cents, ordered_at
            FROM order_items
            ORDER BY ordered_at DESC, id DESC
            """
        )
        rows = cur.fetchall()
    for row in rows:
        ordered_at = row.get("ordered_at")
        if ordered_at is not None:
            row["ordered_at"] = ordered_at.isoformat()
    return jsonify(rows)


@app.post("/api/orders")
def create_order():
    payload = request.get_json(silent=True) or {}
    item_keys = payload.get("items", [])
    if not isinstance(item_keys, list) or not item_keys:
        return jsonify({"error": "Provide at least one item key."}), 400

    timestamp = now_utc_iso()
    to_insert: list[tuple[str, str, int, str]] = []
    for item_key in item_keys:
        item = MENU_LOOKUP.get(item_key)
        if item is None:
            return jsonify({"error": f"Unknown item key: {item_key}"}), 400
        to_insert.append((item["key"], item["name"], item["price_cents"], timestamp))

    conn = get_db()
    with conn, conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO order_items (item_key, item_name, price_cents, ordered_at)
            VALUES (%s, %s, %s, %s)
            """,
            to_insert,
        )

    return jsonify({"success": True, "item_count": len(to_insert), "ordered_at": timestamp})


@app.put("/api/orders/<int:order_id>")
@require_db_admin_api
def update_order(order_id: int):
    payload = request.get_json(silent=True) or {}
    item_key = payload.get("item_key")
    if not isinstance(item_key, str):
        return jsonify({"error": "item_key is required."}), 400

    item = MENU_LOOKUP.get(item_key)
    if item is None:
        return jsonify({"error": f"Unknown item key: {item_key}"}), 400

    conn = get_db()
    with conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE order_items
            SET item_key = %s, item_name = %s, price_cents = %s
            WHERE id = %s
            """,
            (item["key"], item["name"], item["price_cents"], order_id),
        )

    if cur.rowcount == 0:
        return jsonify({"error": "Order entry not found."}), 404

    return jsonify({"success": True})


@app.delete("/api/orders/<int:order_id>")
@require_db_admin_api
def delete_order(order_id: int):
    conn = get_db()
    with conn, conn.cursor() as cur:
        cur.execute("DELETE FROM order_items WHERE id = %s", (order_id,))

    if cur.rowcount == 0:
        return jsonify({"error": "Order entry not found."}), 404

    return jsonify({"success": True})


with app.app_context():
    init_db()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
