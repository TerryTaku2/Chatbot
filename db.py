import sqlite3
import os
import re
import uuid
import json
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "ttech.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sellers (
            phone         TEXT PRIMARY KEY,
            name          TEXT NOT NULL,
            business_name TEXT NOT NULL,
            location      TEXT DEFAULT '',
            status        TEXT NOT NULL DEFAULT 'pending',
            registered_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            name             TEXT NOT NULL,
            category         TEXT NOT NULL,
            price            REAL NOT NULL,
            commission       REAL NOT NULL DEFAULT 0,
            stock_qty        INTEGER NOT NULL DEFAULT 0,
            description      TEXT,
            image_path       TEXT,
            listed_by        TEXT,
            status           TEXT NOT NULL DEFAULT 'pending',
            rejection_reason TEXT,
            created_at       DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Migrate existing products table if it lacks new columns
    for col, definition in [
        ("commission",       "REAL NOT NULL DEFAULT 0"),
        ("status",           "TEXT NOT NULL DEFAULT 'pending'"),
        ("rejection_reason", "TEXT"),
    ]:
        try:
            cursor.execute(f"ALTER TABLE products ADD COLUMN {col} {definition}")
        except Exception:
            pass

    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS products_fts
        USING fts5(
            name,
            category,
            description,
            content='products',
            content_rowid='id'
        )
    """)

    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS products_ai
        AFTER INSERT ON products BEGIN
            INSERT INTO products_fts(rowid, name, category, description)
            VALUES (new.id, new.name, new.category, new.description);
        END
    """)

    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS products_ad
        AFTER DELETE ON products BEGIN
            INSERT INTO products_fts(products_fts, rowid, name, category, description)
            VALUES ('delete', old.id, old.name, old.category, old.description);
        END
    """)

    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS products_au
        AFTER UPDATE ON products BEGIN
            INSERT INTO products_fts(products_fts, rowid, name, category, description)
            VALUES ('delete', old.id, old.name, old.category, old.description);
            INSERT INTO products_fts(rowid, name, category, description)
            VALUES (new.id, new.name, new.category, new.description);
        END
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vendor_tokens (
            token      TEXT PRIMARY KEY,
            phone      TEXT NOT NULL,
            expires_at DATETIME NOT NULL,
            used       INTEGER NOT NULL DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            phone      TEXT PRIMARY KEY,
            state      TEXT NOT NULL,
            data       TEXT DEFAULT '{}',
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS message_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            phone       TEXT NOT NULL,
            message     TEXT NOT NULL,
            received_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS waitlist (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            phone      TEXT NOT NULL,
            product_id INTEGER NOT NULL,
            added_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(phone, product_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            reference        TEXT UNIQUE,
            buyer_phone      TEXT NOT NULL,
            product_id       INTEGER NOT NULL,
            quantity         INTEGER NOT NULL DEFAULT 1,
            unit_price       REAL NOT NULL,
            total_price      REAL NOT NULL,
            status           TEXT NOT NULL DEFAULT 'pending',
            delivery_type    TEXT NOT NULL DEFAULT 'self_collect',
            delivery_address TEXT DEFAULT '',
            created_at       DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS property_enquiries (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            phone          TEXT NOT NULL,
            name           TEXT NOT NULL,
            property_id    INTEGER NOT NULL,
            property_title TEXT NOT NULL,
            property_city  TEXT DEFAULT '',
            price_per_month REAL DEFAULT 0,
            status         TEXT NOT NULL DEFAULT 'new',
            created_at     DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Cart ──────────────────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cart (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            phone      TEXT NOT NULL,
            product_id INTEGER NOT NULL,
            quantity   INTEGER NOT NULL DEFAULT 1,
            added_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(phone, product_id)
        )
    """)

    # ── Disputes ──────────────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS disputes (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            reference    TEXT NOT NULL,
            order_id     INTEGER,
            buyer_phone  TEXT NOT NULL,
            seller_phone TEXT DEFAULT '',
            issue_type   TEXT NOT NULL,
            description  TEXT DEFAULT '',
            status       TEXT NOT NULL DEFAULT 'open',
            resolution   TEXT DEFAULT '',
            created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Newsletter subscribers ─────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS newsletter_subs (
            phone        TEXT PRIMARY KEY,
            subscribed_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Social media post log ─────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS social_posts (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            service_id INTEGER,
            platform   TEXT NOT NULL,
            post_id    TEXT DEFAULT '',
            status     TEXT NOT NULL DEFAULT 'sent',
            posted_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Product reviews ───────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS product_reviews (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id     INTEGER NOT NULL,
            reviewer_phone TEXT NOT NULL,
            order_id       INTEGER,
            rating         INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
            comment        TEXT DEFAULT '',
            created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(product_id, reviewer_phone)
        )
    """)

    # Add KYC columns to sellers if missing
    for col in [
        "kyc_link TEXT DEFAULT ''",
        "id_photo TEXT DEFAULT ''",
        "selfie_photo TEXT DEFAULT ''",
    ]:
        try:
            cursor.execute(f"ALTER TABLE sellers ADD COLUMN {col}")
        except Exception:
            pass

    # Migrate sellers table if location column missing
    try:
        cursor.execute("ALTER TABLE sellers ADD COLUMN location TEXT DEFAULT ''")
    except Exception:
        pass

    # Migrate orders table if delivery columns missing
    for col, definition in [
        ("delivery_type",    "TEXT NOT NULL DEFAULT 'self_collect'"),
        ("delivery_address", "TEXT DEFAULT ''"),
    ]:
        try:
            cursor.execute(f"ALTER TABLE orders ADD COLUMN {col} {definition}")
        except Exception:
            pass

    # ── Delivery personnel ────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS delivery_personnel (
            phone         TEXT PRIMARY KEY,
            name          TEXT NOT NULL,
            vehicle_type  TEXT DEFAULT '',
            service_area  TEXT DEFAULT '',
            status        TEXT NOT NULL DEFAULT 'pending',
            registered_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Settings ──────────────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Seed defaults (only if not already set)
    cursor.execute("""
        INSERT OR IGNORE INTO settings (key, value) VALUES
        ('commission_rate', '10'),
        ('service_commission_rate', '10'),
        ('accommodation_commission_rate', '5'),
        ('contact_phone', '+263 77 412 8219'),
        ('contact_email', 'terrencemuromba@gmail.com'),
        ('contact_website', 'https://t-techsolutions.co.zw'),
        ('contact_location', 'Harare, Zimbabwe'),
        ('auto_post_facebook', '0'),
        ('newsletter_enabled', '1'),
        ('paynow_enabled', '0'),
        ('whatsapp_business_number', '263774128219')
    """)

    # ── Audit log ─────────────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_phone TEXT NOT NULL,
            action      TEXT NOT NULL,
            target_type TEXT DEFAULT '',
            target_id   TEXT DEFAULT '',
            detail      TEXT DEFAULT '',
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Rate limiting (persistent) ─────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rate_limit (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            phone      TEXT NOT NULL,
            hit_at     DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Message send log (for failure tracking) ────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS send_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            to_phone    TEXT NOT NULL,
            message     TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'sent',
            error       TEXT DEFAULT '',
            sent_at     DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── Services tables ───────────────────────────────────────────────────────

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS services (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            title             TEXT NOT NULL,
            category          TEXT NOT NULL,
            description       TEXT,
            price_type        TEXT NOT NULL DEFAULT 'quoted',
            price             REAL DEFAULT 0,
            currency          TEXT DEFAULT 'USD',
            service_area      TEXT DEFAULT '',
            provider_phone    TEXT NOT NULL,
            provider_name     TEXT,
            provider_business TEXT,
            status            TEXT NOT NULL DEFAULT 'pending',
            rejection_reason  TEXT,
            created_at        DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS service_reviews (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            service_id     INTEGER NOT NULL,
            reviewer_phone TEXT NOT NULL,
            rating         INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
            comment        TEXT DEFAULT '',
            created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(service_id, reviewer_phone)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS service_enquiries (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            service_id     INTEGER NOT NULL,
            customer_phone TEXT NOT NULL,
            customer_name  TEXT NOT NULL,
            details        TEXT DEFAULT '',
            status         TEXT NOT NULL DEFAULT 'new',
            created_at     DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Migrate orders table if reference column missing
    # (SQLite cannot add a UNIQUE column via ALTER TABLE, so add plain then index)
    try:
        cursor.execute("ALTER TABLE orders ADD COLUMN reference TEXT")
    except Exception:
        pass
    try:
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_reference "
            "ON orders(reference) WHERE reference IS NOT NULL"
        )
    except Exception:
        pass

    conn.commit()
    conn.close()
    print("Database initialised at", DB_PATH)


# ── Sellers ───────────────────────────────────────────────────────────────────

def register_seller(phone, name, business_name, location="",
                    id_photo="", selfie_photo=""):
    conn = get_connection()
    conn.execute("""
        INSERT INTO sellers (phone, name, business_name, location, status, id_photo, selfie_photo)
        VALUES (?, ?, ?, ?, 'pending', ?, ?)
        ON CONFLICT(phone) DO UPDATE SET
            name          = excluded.name,
            business_name = excluded.business_name,
            location      = excluded.location,
            id_photo      = excluded.id_photo,
            selfie_photo  = excluded.selfie_photo,
            status        = 'pending'
    """, (phone, name, business_name, location, id_photo, selfie_photo))
    conn.commit()
    conn.close()


def get_seller(phone):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sellers WHERE phone = ?", (phone,))
    row = cursor.fetchone()
    conn.close()
    return row


def set_seller_status(phone, status):
    conn = get_connection()
    conn.execute("UPDATE sellers SET status = ? WHERE phone = ?", (status, phone))
    conn.commit()
    conn.close()


def get_pending_sellers():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sellers WHERE status = 'pending' ORDER BY registered_at")
    rows = cursor.fetchall()
    conn.close()
    return rows


# ── Products ──────────────────────────────────────────────────────────────────

def sanitize_fts_query(query):
    return re.sub(r'[\"()*:^~]', '', query).strip()


def add_product(name, category, price, stock_qty, description, image_path=None, listed_by=None):
    rate       = float(get_setting("commission_rate", "10")) / 100
    commission = round(price * rate, 2)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO products
            (name, category, price, commission, stock_qty, description, image_path, listed_by, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
    """, (name, category, price, commission, stock_qty, description, image_path, listed_by))
    conn.commit()
    product_id = cursor.lastrowid
    conn.close()
    return product_id, commission


def search_products(query):
    safe_query = sanitize_fts_query(query)
    if not safe_query:
        return []
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT p.id, p.name, p.category, p.price, p.stock_qty, p.description, p.image_path
            FROM products p
            JOIN products_fts f ON p.id = f.rowid
            WHERE products_fts MATCH ?
              AND p.status = 'approved'
            ORDER BY rank
            LIMIT 5
        """, (safe_query,))
        results = cursor.fetchall()
    except Exception:
        results = []
    conn.close()
    return results


def get_product_by_id(product_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    product = cursor.fetchone()
    conn.close()
    return product


def get_pending_products():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.*, s.name AS seller_name, s.business_name
        FROM products p
        LEFT JOIN sellers s ON p.listed_by = s.phone
        WHERE p.status = 'pending'
        ORDER BY p.created_at
    """)
    rows = cursor.fetchall()
    conn.close()
    return rows


def set_product_status(product_id, status, rejection_reason=None):
    conn = get_connection()
    conn.execute("""
        UPDATE products
        SET status = ?, rejection_reason = ?
        WHERE id = ?
    """, (status, rejection_reason, product_id))
    conn.commit()
    conn.close()


def update_stock(product_id, new_qty):
    conn = get_connection()
    conn.execute("UPDATE products SET stock_qty = ? WHERE id = ?", (new_qty, product_id))
    conn.commit()
    conn.close()


def get_all_products():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, category, price, stock_qty, status
        FROM products ORDER BY created_at DESC
    """)
    products = cursor.fetchall()
    conn.close()
    return products


def get_products_by_category(category):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, price, stock_qty, description, image_path
        FROM products
        WHERE LOWER(category) = LOWER(?) AND status = 'approved'
        ORDER BY name
    """, (category,))
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_seller_products(phone):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, price, stock_qty, status, created_at
        FROM products WHERE listed_by = ?
        ORDER BY created_at DESC
    """, (phone,))
    rows = cursor.fetchall()
    conn.close()
    return rows


# ── Orders ────────────────────────────────────────────────────────────────────

def create_order(buyer_phone, product_id, quantity, unit_price,
                 delivery_type="self_collect", delivery_address=""):
    total = round(unit_price * quantity, 2)
    ref   = f"TTC-{uuid.uuid4().hex[:6].upper()}"
    conn  = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO orders
            (buyer_phone, product_id, quantity, unit_price, total_price, reference,
             delivery_type, delivery_address)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (buyer_phone, product_id, quantity, unit_price, total, ref,
          delivery_type, delivery_address))
    conn.commit()
    order_id = cursor.lastrowid
    conn.close()
    return order_id, ref, total


def get_order(order_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
    row = cursor.fetchone()
    conn.close()
    return row


def get_buyer_orders(phone):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT o.id, o.reference, p.name, o.quantity, o.total_price, o.status, o.created_at
        FROM orders o
        JOIN products p ON o.product_id = p.id
        WHERE o.buyer_phone = ?
        ORDER BY o.created_at DESC
        LIMIT 10
    """, (phone,))
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_seller_orders(seller_phone):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT o.id, o.reference, p.name, o.quantity, o.total_price,
               o.buyer_phone, o.status, o.created_at
        FROM orders o
        JOIN products p ON o.product_id = p.id
        WHERE p.listed_by = ?
        ORDER BY o.created_at DESC
        LIMIT 10
    """, (seller_phone,))
    rows = cursor.fetchall()
    conn.close()
    return rows


def update_order_status(order_id, status):
    conn = get_connection()
    conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
    conn.commit()
    conn.close()


# ── Vendor tokens ─────────────────────────────────────────────────────────────

def create_vendor_token(phone):
    conn = get_connection()
    token = str(uuid.uuid4())
    expires_at = datetime.utcnow() + timedelta(minutes=30)
    conn.execute(
        "INSERT INTO vendor_tokens (token, phone, expires_at) VALUES (?, ?, ?)",
        (token, phone, expires_at.isoformat())
    )
    conn.commit()
    conn.close()
    return token


def validate_token(token):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vendor_tokens WHERE token = ? AND used = 0", (token,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    if datetime.utcnow() > datetime.fromisoformat(row["expires_at"]):
        return None
    return row


def mark_token_used(token):
    conn = get_connection()
    conn.execute("UPDATE vendor_tokens SET used = 1 WHERE token = ?", (token,))
    conn.commit()
    conn.close()


# ── Sessions ──────────────────────────────────────────────────────────────────

def get_session(phone):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sessions WHERE phone = ?", (phone,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    # Auto-expire sessions idle for more than 30 minutes
    updated_at = datetime.fromisoformat(row["updated_at"])
    if datetime.utcnow() - updated_at > timedelta(minutes=30):
        clear_session(phone)
        return None
    return row


def set_session(phone, state, data=None):
    payload = json.dumps(data or {})
    conn = get_connection()
    conn.execute("""
        INSERT INTO sessions (phone, state, data, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(phone) DO UPDATE SET
            state      = excluded.state,
            data       = excluded.data,
            updated_at = CURRENT_TIMESTAMP
    """, (phone, state, payload))
    conn.commit()
    conn.close()


def clear_session(phone):
    conn = get_connection()
    conn.execute("DELETE FROM sessions WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()


# ── Message log ───────────────────────────────────────────────────────────────

def log_message(phone, message):
    conn = get_connection()
    conn.execute("INSERT INTO message_log (phone, message) VALUES (?, ?)", (phone, message))
    conn.commit()
    conn.close()


# ── Waitlist ──────────────────────────────────────────────────────────────────

def add_to_waitlist(phone, product_id):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO waitlist (phone, product_id) VALUES (?, ?)",
            (phone, product_id)
        )
        conn.commit()
    except Exception:
        pass
    conn.close()


def get_waitlist_for_product(product_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT phone FROM waitlist WHERE product_id = ?", (product_id,))
    rows = cursor.fetchall()
    conn.close()
    return [r["phone"] for r in rows]


def clear_waitlist_for_product(product_id):
    conn = get_connection()
    conn.execute("DELETE FROM waitlist WHERE product_id = ?", (product_id,))
    conn.commit()
    conn.close()


# ── Property enquiries ────────────────────────────────────────────────────────

def log_property_enquiry(phone, name, property_id, property_title, property_city="", price_per_month=0):
    conn = get_connection()
    conn.execute("""
        INSERT INTO property_enquiries
            (phone, name, property_id, property_title, property_city, price_per_month)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (phone, name, property_id, property_title, property_city, price_per_month))
    conn.commit()
    conn.close()


def get_property_enquiries(status=None, limit=10):
    conn = get_connection()
    cursor = conn.cursor()
    if status:
        cursor.execute(
            "SELECT * FROM property_enquiries WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, limit)
        )
    else:
        cursor.execute(
            "SELECT * FROM property_enquiries ORDER BY created_at DESC LIMIT ?",
            (limit,)
        )
    rows = cursor.fetchall()
    conn.close()
    return rows


def update_enquiry_status(enquiry_id, status):
    conn = get_connection()
    conn.execute("UPDATE property_enquiries SET status = ? WHERE id = ?", (status, enquiry_id))
    conn.commit()
    conn.close()


# ── Settings ──────────────────────────────────────────────────────────────────

def get_setting(key, default=""):
    conn = get_connection()
    row  = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = get_connection()
    conn.execute("""
        INSERT INTO settings (key, value, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = CURRENT_TIMESTAMP
    """, (key, str(value)))
    conn.commit()
    conn.close()


# ── Admin analytics ───────────────────────────────────────────────────────────

def get_admin_stats():
    conn = get_connection()
    c    = conn.cursor()
    stats = {
        "pending_sellers":   c.execute("SELECT COUNT(*) FROM sellers WHERE status='pending'").fetchone()[0],
        "approved_sellers":  c.execute("SELECT COUNT(*) FROM sellers WHERE status='approved'").fetchone()[0],
        "pending_products":  c.execute("SELECT COUNT(*) FROM products WHERE status='pending'").fetchone()[0],
        "approved_products": c.execute("SELECT COUNT(*) FROM products WHERE status='approved'").fetchone()[0],
        "total_orders":      c.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
        "total_revenue":     c.execute("SELECT COALESCE(SUM(total_price),0) FROM orders").fetchone()[0],
        "new_enquiries":     c.execute("SELECT COUNT(*) FROM property_enquiries WHERE status='new'").fetchone()[0],
        "total_messages":    c.execute("SELECT COUNT(*) FROM message_log").fetchone()[0],
        "unique_users":      c.execute("SELECT COUNT(DISTINCT phone) FROM message_log").fetchone()[0],
    }
    conn.close()
    return stats


def get_all_sellers_admin(status=None):
    conn = get_connection()
    cursor = conn.cursor()
    if status:
        cursor.execute(
            "SELECT * FROM sellers WHERE status = ? ORDER BY registered_at DESC",
            (status,)
        )
    else:
        cursor.execute("SELECT * FROM sellers ORDER BY registered_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_all_products_admin(status=None, limit=10):
    conn = get_connection()
    cursor = conn.cursor()
    if status:
        cursor.execute("""
            SELECT p.*, s.name AS seller_name, s.business_name
            FROM products p LEFT JOIN sellers s ON p.listed_by = s.phone
            WHERE p.status = ?
            ORDER BY p.created_at DESC LIMIT ?
        """, (status, limit))
    else:
        cursor.execute("""
            SELECT p.*, s.name AS seller_name, s.business_name
            FROM products p LEFT JOIN sellers s ON p.listed_by = s.phone
            ORDER BY p.created_at DESC LIMIT ?
        """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_recent_orders_admin(limit=10):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT o.*, p.name AS product_name, p.listed_by AS seller_phone
        FROM orders o
        JOIN products p ON o.product_id = p.id
        ORDER BY o.created_at DESC LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_all_user_phones():
    """Return all unique phone numbers that have ever messaged the bot."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT phone FROM message_log")
    rows = cursor.fetchall()
    conn.close()
    return [r["phone"] for r in rows]


def get_seller_phone_list():
    """Return phones of all approved sellers."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT phone FROM sellers WHERE status = 'approved'")
    rows = cursor.fetchall()
    conn.close()
    return [r["phone"] for r in rows]


# ── Services ──────────────────────────────────────────────────────────────────

def add_service(title, category, description, price_type, price,
                service_area, provider_phone, provider_name="", provider_business=""):
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO services
            (title, category, description, price_type, price,
             service_area, provider_phone, provider_name, provider_business)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (title, category, description, price_type, price,
          service_area, provider_phone, provider_name, provider_business))
    conn.commit()
    service_id = cursor.lastrowid
    conn.close()
    return service_id


def get_service(service_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM services WHERE id = ?", (service_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_services_by_category(category, limit=5):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT s.*,
               ROUND(COALESCE(AVG(r.rating), 0), 1) AS avg_rating,
               COUNT(r.id) AS review_count
        FROM services s
        LEFT JOIN service_reviews r ON r.service_id = s.id
        WHERE LOWER(s.category) = LOWER(?) AND s.status = 'approved'
        GROUP BY s.id
        ORDER BY avg_rating DESC, s.created_at DESC
        LIMIT ?
    """, (category, limit))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def search_services(query, limit=5):
    import re as _re
    safe = _re.sub(r'[\"()*:^~]', '', query).strip()
    if not safe:
        return []
    conn = get_connection()
    cursor = conn.cursor()
    like = f"%{safe}%"
    cursor.execute("""
        SELECT s.*,
               ROUND(COALESCE(AVG(r.rating), 0), 1) AS avg_rating,
               COUNT(r.id) AS review_count
        FROM services s
        LEFT JOIN service_reviews r ON r.service_id = s.id
        WHERE s.status = 'approved'
          AND (s.title LIKE ? OR s.category LIKE ? OR s.description LIKE ? OR s.service_area LIKE ?)
        GROUP BY s.id
        ORDER BY avg_rating DESC
        LIMIT ?
    """, (like, like, like, like, limit))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_pending_services():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM services WHERE status = 'pending'
        ORDER BY created_at ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_provider_services(phone):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT s.*,
               ROUND(COALESCE(AVG(r.rating), 0), 1) AS avg_rating,
               COUNT(r.id) AS review_count
        FROM services s
        LEFT JOIN service_reviews r ON r.service_id = s.id
        WHERE s.provider_phone = ?
        GROUP BY s.id
        ORDER BY s.created_at DESC
    """, (phone,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_service_status(service_id, status, reason=None):
    conn = get_connection()
    conn.execute(
        "UPDATE services SET status = ?, rejection_reason = ? WHERE id = ?",
        (status, reason, service_id)
    )
    conn.commit()
    conn.close()


# ── Service reviews ───────────────────────────────────────────────────────────

def add_service_review(service_id, reviewer_phone, rating, comment=""):
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO service_reviews (service_id, reviewer_phone, rating, comment)
            VALUES (?, ?, ?, ?)
        """, (service_id, reviewer_phone, rating, comment))
        conn.commit()
        success = True
    except Exception:
        success = False  # duplicate review
    conn.close()
    return success


def get_service_reviews(service_id, limit=3):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM service_reviews
        WHERE service_id = ?
        ORDER BY created_at DESC
        LIMIT ?
    """, (service_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Product reviews ───────────────────────────────────────────────────────────

def add_product_review(product_id, reviewer_phone, rating, comment="", order_id=None):
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO product_reviews (product_id, reviewer_phone, rating, comment, order_id)
            VALUES (?, ?, ?, ?, ?)
        """, (product_id, reviewer_phone, rating, comment, order_id))
        conn.commit()
        # Update FTS index average — not needed, ratings shown dynamically
        success = True
    except Exception:
        success = False   # duplicate review
    conn.close()
    return success


def get_product_reviews(product_id, limit=3):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM product_reviews WHERE product_id = ?
        ORDER BY created_at DESC LIMIT ?
    """, (product_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_product_avg_rating(product_id):
    conn = get_connection()
    row  = conn.execute("""
        SELECT ROUND(COALESCE(AVG(rating), 0), 1) AS avg, COUNT(*) AS cnt
        FROM product_reviews WHERE product_id = ?
    """, (product_id,)).fetchone()
    conn.close()
    return (row["avg"], row["cnt"]) if row else (0, 0)


def get_fulfilled_orders_for_buyer(phone, limit=5):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT o.*, p.name AS product_name, p.id AS prod_id
        FROM orders o JOIN products p ON o.product_id = p.id
        WHERE o.buyer_phone = ? AND o.status = 'fulfilled'
        ORDER BY o.created_at DESC LIMIT ?
    """, (phone, limit))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Service enquiries ─────────────────────────────────────────────────────────

def log_service_enquiry(service_id, customer_phone, customer_name, details=""):
    conn = get_connection()
    conn.execute("""
        INSERT INTO service_enquiries (service_id, customer_phone, customer_name, details)
        VALUES (?, ?, ?, ?)
    """, (service_id, customer_phone, customer_name, details))
    conn.commit()
    conn.close()


def get_service_enquiries(status=None, limit=10):
    conn = get_connection()
    cursor = conn.cursor()
    if status:
        cursor.execute("""
            SELECT e.*, s.title AS service_title, s.category
            FROM service_enquiries e
            JOIN services s ON e.service_id = s.id
            WHERE e.status = ?
            ORDER BY e.created_at DESC LIMIT ?
        """, (status, limit))
    else:
        cursor.execute("""
            SELECT e.*, s.title AS service_title, s.category
            FROM service_enquiries e
            JOIN services s ON e.service_id = s.id
            ORDER BY e.created_at DESC LIMIT ?
        """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Audit log ─────────────────────────────────────────────────────────────────

def log_admin_action(admin_phone, action, target_type="", target_id="", detail=""):
    conn = get_connection()
    conn.execute("""
        INSERT INTO audit_log (admin_phone, action, target_type, target_id, detail)
        VALUES (?, ?, ?, ?, ?)
    """, (admin_phone, action, target_type, str(target_id), detail[:500]))
    conn.commit()
    conn.close()


def get_audit_log(limit=20):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ?", (limit,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Persistent rate limiting ──────────────────────────────────────────────────

def check_and_record_hit(phone, window_secs=60, max_hits=20):
    """Returns True if rate limit exceeded, False if OK. Records the hit."""
    conn   = get_connection()
    cursor = conn.cursor()
    # Count recent hits within window
    cursor.execute("""
        SELECT COUNT(*) FROM rate_limit
        WHERE phone = ?
          AND hit_at > datetime('now', ? || ' seconds')
    """, (phone, f"-{window_secs}"))
    count = cursor.fetchone()[0]
    if count >= max_hits:
        conn.close()
        return True   # rate limited
    conn.execute("INSERT INTO rate_limit (phone) VALUES (?)", (phone,))
    # Purge old entries older than 2x window to keep table small
    conn.execute("""
        DELETE FROM rate_limit
        WHERE hit_at < datetime('now', ? || ' seconds')
    """, (f"-{window_secs * 2}",))
    conn.commit()
    conn.close()
    return False


# ── Send log (failure tracking) ───────────────────────────────────────────────

def log_send(to_phone, message, status="sent", error=""):
    conn = get_connection()
    conn.execute("""
        INSERT INTO send_log (to_phone, message, status, error)
        VALUES (?, ?, ?, ?)
    """, (to_phone, message[:300], status, error[:300]))
    conn.commit()
    conn.close()


# ── Session maintenance ───────────────────────────────────────────────────────

def cleanup_expired_sessions(max_age_minutes=60):
    """Delete sessions that have been idle longer than max_age_minutes."""
    conn = get_connection()
    conn.execute("""
        DELETE FROM sessions
        WHERE updated_at < datetime('now', ? || ' minutes')
    """, (f"-{max_age_minutes}",))
    deleted = conn.execute("SELECT changes()").fetchone()[0]
    conn.commit()
    conn.close()
    return deleted


# ── Cart ──────────────────────────────────────────────────────────────────────

def add_to_cart(phone, product_id, quantity=1):
    conn = get_connection()
    conn.execute("""
        INSERT INTO cart (phone, product_id, quantity)
        VALUES (?, ?, ?)
        ON CONFLICT(phone, product_id) DO UPDATE SET
            quantity = quantity + excluded.quantity,
            added_at = CURRENT_TIMESTAMP
    """, (phone, product_id, quantity))
    conn.commit()
    conn.close()


def remove_from_cart(phone, product_id):
    conn = get_connection()
    conn.execute("DELETE FROM cart WHERE phone = ? AND product_id = ?", (phone, product_id))
    conn.commit()
    conn.close()


def get_cart(phone):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.product_id, c.quantity,
               p.name, p.price, p.stock_qty, p.category, p.listed_by
        FROM cart c
        JOIN products p ON c.product_id = p.id
        WHERE c.phone = ? AND p.status = 'approved'
        ORDER BY c.added_at ASC
    """, (phone,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_cart_total(phone):
    items = get_cart(phone)
    return round(sum(i["price"] * i["quantity"] for i in items), 2)


def clear_cart(phone):
    conn = get_connection()
    conn.execute("DELETE FROM cart WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()


def update_cart_qty(phone, product_id, quantity):
    if quantity <= 0:
        remove_from_cart(phone, product_id)
        return
    conn = get_connection()
    conn.execute(
        "UPDATE cart SET quantity = ? WHERE phone = ? AND product_id = ?",
        (quantity, phone, product_id)
    )
    conn.commit()
    conn.close()


# ── Disputes ──────────────────────────────────────────────────────────────────

def create_dispute(buyer_phone, issue_type, description, order_id=None, seller_phone=""):
    conn   = get_connection()
    ref    = f"DIS-{uuid.uuid4().hex[:6].upper()}"
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO disputes
            (reference, order_id, buyer_phone, seller_phone, issue_type, description)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (ref, order_id, buyer_phone, seller_phone, issue_type, description))
    conn.commit()
    dispute_id = cursor.lastrowid
    conn.close()
    return dispute_id, ref


def get_disputes(status=None, limit=10):
    conn = get_connection()
    cursor = conn.cursor()
    if status:
        cursor.execute(
            "SELECT * FROM disputes WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, limit)
        )
    else:
        cursor.execute("SELECT * FROM disputes ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_dispute(dispute_id, status, resolution=""):
    conn = get_connection()
    conn.execute("""
        UPDATE disputes SET status = ?, resolution = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (status, resolution, dispute_id))
    conn.commit()
    conn.close()


def get_buyer_disputes(phone):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM disputes WHERE buyer_phone = ? ORDER BY created_at DESC LIMIT 10",
        (phone,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Newsletter ────────────────────────────────────────────────────────────────

def newsletter_subscribe(phone):
    conn = get_connection()
    conn.execute("INSERT OR IGNORE INTO newsletter_subs (phone) VALUES (?)", (phone,))
    conn.commit()
    conn.close()


def newsletter_unsubscribe(phone):
    conn = get_connection()
    conn.execute("DELETE FROM newsletter_subs WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()


def is_subscribed(phone):
    conn = get_connection()
    row  = conn.execute("SELECT 1 FROM newsletter_subs WHERE phone = ?", (phone,)).fetchone()
    conn.close()
    return row is not None


def get_newsletter_phones():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT phone FROM newsletter_subs")
    rows = cursor.fetchall()
    conn.close()
    return [r["phone"] for r in rows]


# ── Social post log ───────────────────────────────────────────────────────────

def log_social_post(platform, post_id, product_id=None, service_id=None, status="sent"):
    conn = get_connection()
    conn.execute("""
        INSERT INTO social_posts (product_id, service_id, platform, post_id, status)
        VALUES (?, ?, ?, ?, ?)
    """, (product_id, service_id, platform, post_id or "", status))
    conn.commit()
    conn.close()


# ── Analytics ─────────────────────────────────────────────────────────────────

def get_analytics_summary(days=7):
    conn = get_connection()
    c    = conn.cursor()
    since = f"-{days} days"
    stats = {
        "total_revenue":    c.execute("SELECT COALESCE(SUM(total_price),0) FROM orders WHERE created_at > datetime('now', ?)", (since,)).fetchone()[0],
        "total_orders":     c.execute("SELECT COUNT(*) FROM orders WHERE created_at > datetime('now', ?)", (since,)).fetchone()[0],
        "new_users":        c.execute("SELECT COUNT(DISTINCT phone) FROM message_log WHERE received_at > datetime('now', ?)", (since,)).fetchone()[0],
        "new_listings":     c.execute("SELECT COUNT(*) FROM products WHERE created_at > datetime('now', ?) AND status='approved'", (since,)).fetchone()[0],
        "new_services":     c.execute("SELECT COUNT(*) FROM services WHERE created_at > datetime('now', ?) AND status='approved'", (since,)).fetchone()[0],
        "open_disputes":    c.execute("SELECT COUNT(*) FROM disputes WHERE status='open'", ()).fetchone()[0],
        "newsletter_count": c.execute("SELECT COUNT(*) FROM newsletter_subs", ()).fetchone()[0],
    }
    # Top 5 products by order count
    top_products = c.execute("""
        SELECT p.name, COUNT(*) as cnt, SUM(o.total_price) as revenue
        FROM orders o JOIN products p ON o.product_id = p.id
        WHERE o.created_at > datetime('now', ?)
        GROUP BY o.product_id ORDER BY cnt DESC LIMIT 5
    """, (since,)).fetchall()
    stats["top_products"] = [dict(r) for r in top_products]

    # Revenue by day
    revenue_by_day = c.execute("""
        SELECT DATE(created_at) as day, SUM(total_price) as revenue, COUNT(*) as orders
        FROM orders WHERE created_at > datetime('now', ?)
        GROUP BY day ORDER BY day
    """, (since,)).fetchall()
    stats["revenue_by_day"] = [dict(r) for r in revenue_by_day]

    # Peak hours
    peak_hours = c.execute("""
        SELECT CAST(strftime('%H', received_at) AS INTEGER) as hour, COUNT(*) as hits
        FROM message_log WHERE received_at > datetime('now', ?)
        GROUP BY hour ORDER BY hits DESC LIMIT 3
    """, (since,)).fetchall()
    stats["peak_hours"] = [dict(r) for r in peak_hours]

    # Top service categories
    top_services = c.execute("""
        SELECT category, COUNT(*) as enquiries
        FROM service_enquiries e
        JOIN services s ON e.service_id = s.id
        WHERE e.created_at > datetime('now', ?)
        GROUP BY category ORDER BY enquiries DESC LIMIT 5
    """, (since,)).fetchall()
    stats["top_service_cats"] = [dict(r) for r in top_services]

    conn.close()
    return stats


# ── Delivery personnel ────────────────────────────────────────────────────────

def register_delivery_person(phone, name, vehicle_type, service_area):
    conn = get_connection()
    conn.execute("""
        INSERT INTO delivery_personnel (phone, name, vehicle_type, service_area, status)
        VALUES (?, ?, ?, ?, 'pending')
        ON CONFLICT(phone) DO UPDATE SET
            name         = excluded.name,
            vehicle_type = excluded.vehicle_type,
            service_area = excluded.service_area,
            status       = 'pending'
    """, (phone, name, vehicle_type, service_area))
    conn.commit()
    conn.close()


def get_delivery_person(phone):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM delivery_personnel WHERE phone = ?", (phone,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_pending_delivery_personnel():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM delivery_personnel WHERE status = 'pending' ORDER BY registered_at"
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_approved_delivery_personnel():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM delivery_personnel WHERE status = 'approved' ORDER BY registered_at"
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_delivery_person_status(phone, status):
    conn = get_connection()
    conn.execute(
        "UPDATE delivery_personnel SET status = ? WHERE phone = ?", (status, phone)
    )
    conn.commit()
    conn.close()


def get_delivery_orders(service_area, limit=10):
    """Return pending delivery orders that match a service area keyword."""
    conn = get_connection()
    cursor = conn.cursor()
    like = f"%{service_area.lower()}%"
    cursor.execute("""
        SELECT o.id, o.reference, o.delivery_address, o.total_price,
               o.buyer_phone, p.name AS product_name
        FROM orders o
        JOIN products p ON o.product_id = p.id
        WHERE o.delivery_type = 'delivery'
          AND o.status = 'pending'
          AND LOWER(o.delivery_address) LIKE ?
        ORDER BY o.created_at DESC
        LIMIT ?
    """, (like, limit))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_seller_trust_score(phone):
    """Calculate a 0-100 trust score for a seller based on reviews, orders, disputes."""
    conn = get_connection()
    c    = conn.cursor()

    avg_rating = c.execute("""
        SELECT COALESCE(AVG(r.rating), 0)
        FROM service_reviews r
        JOIN services s ON r.service_id = s.id
        WHERE s.provider_phone = ?
    """, (phone,)).fetchone()[0]

    fulfilled = c.execute("""
        SELECT COUNT(*) FROM orders o
        JOIN products p ON o.product_id = p.id
        WHERE p.listed_by = ? AND o.status = 'fulfilled'
    """, (phone,)).fetchone()[0]

    total_orders = c.execute("""
        SELECT COUNT(*) FROM orders o
        JOIN products p ON o.product_id = p.id
        WHERE p.listed_by = ?
    """, (phone,)).fetchone()[0]

    disputes = c.execute(
        "SELECT COUNT(*) FROM disputes WHERE seller_phone = ? AND status != 'resolved'",
        (phone,)
    ).fetchone()[0]

    fulfillment_rate = (fulfilled / total_orders * 100) if total_orders > 0 else 50
    rating_score     = (avg_rating / 5) * 40   # 40 points max from rating
    order_score      = min(fulfillment_rate * 0.4, 40)  # 40 points max
    dispute_penalty  = min(disputes * 10, 20)            # -10 per open dispute, max -20
    score = max(0, min(100, rating_score + order_score - dispute_penalty + 20))  # 20 base

    conn.close()
    return round(score)
