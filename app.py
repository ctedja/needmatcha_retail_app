from __future__ import annotations

import os
import secrets
import threading
import uuid
import atexit
import time
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from flask import Flask, g, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from psycopg_pool import ConnectionPool, PoolTimeout
from psycopg.rows import dict_row
from werkzeug.exceptions import HTTPException


BASE_DIR = Path(__file__).resolve().parent
load_dotenv()


DATABASE_URL = (
    os.getenv("SUPABASE_DB_POOLER_URL")
    or os.getenv("SUPABASE_DB_URL")
    or os.getenv("DATABASE_URL", "")
)
DB_ADMIN_PASSWORD = os.getenv("DB_ADMIN_PASSWORD", "")
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-insecure-key-change-me")
DB_CONNECT_TIMEOUT = int(os.getenv("DB_CONNECT_TIMEOUT_SECONDS", "10"))
DB_STATEMENT_TIMEOUT_MS = int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "12000"))
DB_IDLE_TX_TIMEOUT_MS = int(os.getenv("DB_IDLE_IN_TX_TIMEOUT_MS", "15000"))
DB_POOL_MIN_SIZE = int(os.getenv("DB_POOL_MIN_SIZE", "1"))
DB_POOL_MAX_SIZE = int(os.getenv("DB_POOL_MAX_SIZE", "10"))
DB_POOL_ACQUIRE_TIMEOUT = float(os.getenv("DB_POOL_ACQUIRE_TIMEOUT_SECONDS", "3"))
DB_WRITE_RETRIES = int(os.getenv("DB_WRITE_RETRIES", "2"))
DB_WRITE_RETRY_DELAY_MS = int(os.getenv("DB_WRITE_RETRY_DELAY_MS", "250"))
SCHEMA_INIT_RETRY_INTERVAL_SECONDS = int(os.getenv("SCHEMA_INIT_RETRY_INTERVAL_SECONDS", "60"))


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
    {
        "key": "cookie",
        "name": "Cookie",
        "price_cents": 800,
        "image": "cookie.jpg",
    },
    {
        "key": "freecookie",
        "name": "FREE Cookie",
        "price_cents": 0,
        "image": "cookie.jpg",
    },
    {
        "key": "freebasic",
        "name": "FREE Basic",
        "price_cents": 0,
        "image": "product_basicbae.png",
    },
]

MENU_LOOKUP = {item["key"]: item for item in MENU_ITEMS}

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY
db_pool: ConnectionPool | None = None
schema_initialized = False
schema_lock = threading.Lock()
schema_init_last_attempt_monotonic = 0.0


def close_db_pool() -> None:
    global db_pool
    if db_pool is not None:
        db_pool.close()
        db_pool = None


def reset_request_db_conn(close: bool = False) -> None:
    db = g.pop("db", None)
    if db is None:
        return
    if db_pool is not None:
        db_pool.putconn(db, close=close)
    else:
        db.close()


def is_transient_db_error(error: Exception) -> bool:
    if isinstance(error, PoolTimeout):
        return False
    if isinstance(error, psycopg.OperationalError):
        message = str(error).lower()
        transient_signals = (
            "bad record mac",
            "decryption failed",
            "connection reset",
            "connection refused",
            "server closed the connection",
            "terminating connection",
            "timeout",
            "couldn't get a connection",
            "network",
        )
        return any(signal in message for signal in transient_signals)
    return False


def is_api_request() -> bool:
    return request.path.startswith("/api/")


def get_db_connect_kwargs() -> dict[str, str | int]:
    kwargs: dict[str, str | int] = {"connect_timeout": DB_CONNECT_TIMEOUT}
    kwargs["options"] = (
        f"-c statement_timeout={DB_STATEMENT_TIMEOUT_MS} "
        f"-c idle_in_transaction_session_timeout={DB_IDLE_TX_TIMEOUT_MS}"
    )

    sslmode_override = os.getenv("DB_SSLMODE", "").strip()
    if sslmode_override:
        kwargs["sslmode"] = sslmode_override
    elif "sslmode=" not in DATABASE_URL:
        kwargs["sslmode"] = "require"

    sslrootcert_override = os.getenv("DB_SSLROOTCERT", "").strip()
    if sslrootcert_override:
        kwargs["sslrootcert"] = sslrootcert_override
    elif os.name == "nt" and kwargs.get("sslmode") in {"require", "verify-ca", "verify-full"}:
        kwargs["sslrootcert"] = "system"

    return kwargs


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
        if db_pool is None:
            raise RuntimeError("Database pool is not initialized.")
        conn = db_pool.getconn(timeout=DB_POOL_ACQUIRE_TIMEOUT)
        conn.row_factory = dict_row
        conn.prepare_threshold = None
        g.db = conn
    return g.db


@app.teardown_appcontext
def close_db(_: object) -> None:
    reset_request_db_conn(close=False)


@app.errorhandler(psycopg.Error)
def handle_db_error(error: psycopg.Error):
    app.logger.exception("Database error on %s", request.path, exc_info=error)
    if is_api_request():
        return jsonify({"error": "Database operation failed."}), 500
    return "Database operation failed.", 500


@app.errorhandler(PoolTimeout)
def handle_pool_timeout(error: PoolTimeout):
    app.logger.warning("DB pool timeout on %s: %s", request.path, error)
    if is_api_request():
        return jsonify({"error": "Database temporarily unavailable. Please retry."}), 503
    return "Database temporarily unavailable. Please retry.", 503


@app.errorhandler(Exception)
def handle_unexpected_error(error: Exception):
    if isinstance(error, HTTPException):
        return error
    app.logger.exception("Unhandled error on %s", request.path, exc_info=error)
    if is_api_request():
        return jsonify({"error": "Server error."}), 500
    return "Server error.", 500


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
                ordered_at TIMESTAMPTZ NOT NULL,
                idempotency_key UUID
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_order_items_ordered_at ON order_items(ordered_at DESC)"
        )
        cur.execute("ALTER TABLE order_items ADD COLUMN IF NOT EXISTS idempotency_key UUID")
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_order_items_idempotency_key ON order_items(idempotency_key)"
            " WHERE idempotency_key IS NOT NULL"
        )


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_schema_initialized() -> None:
    global schema_initialized
    global schema_init_last_attempt_monotonic
    if schema_initialized:
        return
    now_monotonic = time.monotonic()
    if now_monotonic - schema_init_last_attempt_monotonic < SCHEMA_INIT_RETRY_INTERVAL_SECONDS:
        return
    with schema_lock:
        if schema_initialized:
            return
        now_monotonic = time.monotonic()
        if now_monotonic - schema_init_last_attempt_monotonic < SCHEMA_INIT_RETRY_INTERVAL_SECONDS:
            return
        schema_init_last_attempt_monotonic = now_monotonic
        try:
            init_db()
            schema_initialized = True
        except psycopg.Error:
            app.logger.warning(
                "Schema initialization attempt failed; will retry in %s seconds.",
                SCHEMA_INIT_RETRY_INTERVAL_SECONDS,
            )


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
    ensure_schema_initialized()
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
    ensure_schema_initialized()
    payload = request.get_json(silent=True) or {}
    item_keys = payload.get("items", [])
    if not isinstance(item_keys, list) or not item_keys:
        return jsonify({"error": "Provide at least one item key."}), 400

    idem_header = (request.headers.get("Idempotency-Key") or "").strip()
    idempotency_key: uuid.UUID | None = None
    if idem_header:
        try:
            idempotency_key = uuid.UUID(idem_header)
        except ValueError:
            return jsonify({"error": "Invalid Idempotency-Key header."}), 400

    timestamp = now_utc_iso()
    to_insert: list[tuple[str, str, int, str]] = []
    for item_key in item_keys:
        item = MENU_LOOKUP.get(item_key)
        if item is None:
            return jsonify({"error": f"Unknown item key: {item_key}"}), 400
        to_insert.append((item["key"], item["name"], item["price_cents"], timestamp))

    attempts = DB_WRITE_RETRIES + 1
    for attempt in range(1, attempts + 1):
        try:
            conn = get_db()
            with conn, conn.cursor() as cur:
                if idempotency_key is None:
                    cur.executemany(
                        """
                        INSERT INTO order_items (item_key, item_name, price_cents, ordered_at)
                        VALUES (%s, %s, %s, %s)
                        """,
                        to_insert,
                    )
                else:
                    first_item = MENU_LOOKUP[item_keys[0]]
                    cur.execute(
                        """
                        INSERT INTO order_items (item_key, item_name, price_cents, ordered_at, idempotency_key)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL DO NOTHING
                        RETURNING id
                        """,
                        (
                            first_item["key"],
                            first_item["name"],
                            first_item["price_cents"],
                            timestamp,
                            idempotency_key,
                        ),
                    )
                    inserted = cur.fetchone()
                    if inserted is None:
                        cur.execute(
                            "SELECT ordered_at FROM order_items WHERE idempotency_key = %s LIMIT 1",
                            (idempotency_key,),
                        )
                        existing = cur.fetchone()
                        return jsonify(
                            {
                                "success": True,
                                "idempotent_replay": True,
                                "item_count": len(item_keys),
                                "ordered_at": existing["ordered_at"].isoformat() if existing else None,
                            }
                        )

                    if len(item_keys) > 1:
                        tail_rows = []
                        for item_key in item_keys[1:]:
                            item = MENU_LOOKUP[item_key]
                            tail_rows.append((item["key"], item["name"], item["price_cents"], timestamp))
                        cur.executemany(
                            """
                            INSERT INTO order_items (item_key, item_name, price_cents, ordered_at)
                            VALUES (%s, %s, %s, %s)
                            """,
                            tail_rows,
                        )
            return jsonify({"success": True, "item_count": len(to_insert), "ordered_at": timestamp})
        except (psycopg.OperationalError, PoolTimeout) as error:
            reset_request_db_conn(close=True)
            if isinstance(error, PoolTimeout):
                raise
            if attempt >= attempts or not is_transient_db_error(error):
                raise
            app.logger.warning(
                "Transient DB error on /api/orders; retrying (%s/%s): %s",
                attempt,
                attempts,
                str(error),
            )
            time.sleep(DB_WRITE_RETRY_DELAY_MS / 1000.0)

    return jsonify({"error": "Database operation failed."}), 500


@app.put("/api/orders/<int:order_id>")
@require_db_admin_api
def update_order(order_id: int):
    ensure_schema_initialized()
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
    ensure_schema_initialized()
    conn = get_db()
    with conn, conn.cursor() as cur:
        cur.execute("DELETE FROM order_items WHERE id = %s", (order_id,))

    if cur.rowcount == 0:
        return jsonify({"error": "Order entry not found."}), 404

    return jsonify({"success": True})


if not DATABASE_URL:
    raise RuntimeError(
        "Missing database URL. Set SUPABASE_DB_POOLER_URL (recommended) or SUPABASE_DB_URL."
    )

db_pool = ConnectionPool(
    conninfo=DATABASE_URL,
    kwargs=get_db_connect_kwargs(),
    min_size=DB_POOL_MIN_SIZE,
    max_size=DB_POOL_MAX_SIZE,
    check=ConnectionPool.check_connection,
    open=True,
)
atexit.register(close_db_pool)

with app.app_context():
    try:
        init_db()
        schema_initialized = True
    except psycopg.Error:
        app.logger.exception("Database initialization failed during startup; will retry on requests.")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
