import os
import re
import uuid
import json
from datetime import datetime, timedelta

from pg_compat import NOW_SQL, get_connection as _pg_get_connection


def get_connection():
    return _pg_get_connection()


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS sellers (
            phone         TEXT PRIMARY KEY,
            name          TEXT NOT NULL,
            business_name TEXT NOT NULL,
            location      TEXT DEFAULT '',
            status        TEXT NOT NULL DEFAULT 'pending',
            registered_at TEXT DEFAULT {NOW_SQL}
        )
    """)

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS products (
            id               SERIAL PRIMARY KEY,
            name             TEXT NOT NULL,
            category         TEXT NOT NULL,
            price            DOUBLE PRECISION NOT NULL,
            commission       DOUBLE PRECISION NOT NULL DEFAULT 0,
            stock_qty        INTEGER NOT NULL DEFAULT 0,
            description      TEXT,
            image_path       TEXT,
            listed_by        TEXT,
            status           TEXT NOT NULL DEFAULT 'pending',
            rejection_reason TEXT,
            created_at       TEXT DEFAULT {NOW_SQL}
        )
    """)

    # Migrate existing products table if it lacks new columns
    for col, definition in [
        ("commission",        "DOUBLE PRECISION NOT NULL DEFAULT 0"),
        ("status",            "TEXT NOT NULL DEFAULT 'pending'"),
        ("rejection_reason",  "TEXT"),
        ("product_type",      "TEXT NOT NULL DEFAULT 'physical'"),
        ("product_file_path", "TEXT"),
        ("stock_unit",        "TEXT NOT NULL DEFAULT 'pcs'"),
        ("seller_location",   "TEXT DEFAULT ''"),
        ("offers_delivery",   "INTEGER DEFAULT 0"),
        ("delivery_info",     "TEXT DEFAULT ''"),
        ("extra_services",    "TEXT DEFAULT ''"),
        ("payment_methods",   "TEXT DEFAULT ''"),
        ("currency",          "TEXT DEFAULT 'USD'"),
        ("cost_price",        "DOUBLE PRECISION NOT NULL DEFAULT 0"),
        ("featured",          "INTEGER DEFAULT 0"),
        ("is_official",       "INTEGER NOT NULL DEFAULT 0"),
    ]:
        cursor.execute(f"ALTER TABLE products ADD COLUMN IF NOT EXISTS {col} {definition}")

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS vendor_tokens (
            token      TEXT PRIMARY KEY,
            phone      TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used       INTEGER NOT NULL DEFAULT 0
        )
    """)

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS sessions (
            phone      TEXT PRIMARY KEY,
            state      TEXT NOT NULL,
            data       TEXT DEFAULT '{{}}',
            updated_at TEXT DEFAULT {NOW_SQL}
        )
    """)

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS message_log (
            id          SERIAL PRIMARY KEY,
            phone       TEXT NOT NULL,
            message     TEXT NOT NULL,
            received_at TEXT DEFAULT {NOW_SQL}
        )
    """)

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS waitlist (
            id         SERIAL PRIMARY KEY,
            phone      TEXT NOT NULL,
            product_id INTEGER NOT NULL,
            added_at   TEXT DEFAULT {NOW_SQL},
            UNIQUE(phone, product_id)
        )
    """)

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS orders (
            id               SERIAL PRIMARY KEY,
            reference        TEXT UNIQUE,
            buyer_phone      TEXT NOT NULL,
            product_id       INTEGER NOT NULL,
            quantity         INTEGER NOT NULL DEFAULT 1,
            unit_price       DOUBLE PRECISION NOT NULL,
            total_price      DOUBLE PRECISION NOT NULL,
            status           TEXT NOT NULL DEFAULT 'pending',
            delivery_type    TEXT NOT NULL DEFAULT 'self_collect',
            delivery_address TEXT DEFAULT '',
            created_at       TEXT DEFAULT {NOW_SQL}
        )
    """)

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS property_enquiries (
            id             SERIAL PRIMARY KEY,
            phone          TEXT NOT NULL,
            name           TEXT NOT NULL,
            property_id    INTEGER NOT NULL,
            property_title TEXT NOT NULL,
            property_city  TEXT DEFAULT '',
            price_per_month DOUBLE PRECISION DEFAULT 0,
            status         TEXT NOT NULL DEFAULT 'new',
            created_at     TEXT DEFAULT {NOW_SQL}
        )
    """)

    # ── Cart ──────────────────────────────────────────────────────────────────
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS cart (
            id         SERIAL PRIMARY KEY,
            phone      TEXT NOT NULL,
            product_id INTEGER NOT NULL,
            quantity   INTEGER NOT NULL DEFAULT 1,
            added_at   TEXT DEFAULT {NOW_SQL},
            UNIQUE(phone, product_id)
        )
    """)

    # ── Disputes ──────────────────────────────────────────────────────────────
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS disputes (
            id           SERIAL PRIMARY KEY,
            reference    TEXT NOT NULL,
            order_id     INTEGER,
            buyer_phone  TEXT NOT NULL,
            seller_phone TEXT DEFAULT '',
            issue_type   TEXT NOT NULL,
            description  TEXT DEFAULT '',
            status       TEXT NOT NULL DEFAULT 'open',
            resolution   TEXT DEFAULT '',
            created_at   TEXT DEFAULT {NOW_SQL},
            updated_at   TEXT DEFAULT {NOW_SQL}
        )
    """)

    # ── Newsletter subscribers ─────────────────────────────────────────────────
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS newsletter_subs (
            phone        TEXT PRIMARY KEY,
            subscribed_at TEXT DEFAULT {NOW_SQL}
        )
    """)

    # ── Social media post log ─────────────────────────────────────────────────
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS social_posts (
            id         SERIAL PRIMARY KEY,
            product_id INTEGER,
            service_id INTEGER,
            platform   TEXT NOT NULL,
            post_id    TEXT DEFAULT '',
            status     TEXT NOT NULL DEFAULT 'sent',
            posted_at  TEXT DEFAULT {NOW_SQL}
        )
    """)

    # ── Product reviews ───────────────────────────────────────────────────────
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS product_reviews (
            id             SERIAL PRIMARY KEY,
            product_id     INTEGER NOT NULL,
            reviewer_phone TEXT NOT NULL,
            order_id       INTEGER,
            rating         INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
            comment        TEXT DEFAULT '',
            created_at     TEXT DEFAULT {NOW_SQL},
            UNIQUE(product_id, reviewer_phone)
        )
    """)

    # Add KYC columns to sellers if missing
    for col in [
        "kyc_link TEXT DEFAULT ''",
        "id_photo TEXT DEFAULT ''",
        "selfie_photo TEXT DEFAULT ''",
        "location TEXT DEFAULT ''",
        "is_official INTEGER NOT NULL DEFAULT 0",
    ]:
        cursor.execute(f"ALTER TABLE sellers ADD COLUMN IF NOT EXISTS {col}")

    # Migrate orders table if delivery columns missing
    for col, definition in [
        ("delivery_type",    "TEXT NOT NULL DEFAULT 'self_collect'"),
        ("delivery_address", "TEXT DEFAULT ''"),
        ("reference",        "TEXT"),
    ]:
        cursor.execute(f"ALTER TABLE orders ADD COLUMN IF NOT EXISTS {col} {definition}")

    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_reference "
        "ON orders(reference) WHERE reference IS NOT NULL"
    )

    # ── Delivery personnel ────────────────────────────────────────────────────
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS delivery_personnel (
            phone         TEXT PRIMARY KEY,
            name          TEXT NOT NULL,
            vehicle_type  TEXT DEFAULT '',
            service_area  TEXT DEFAULT '',
            status        TEXT NOT NULL DEFAULT 'pending',
            registered_at TEXT DEFAULT {NOW_SQL}
        )
    """)

    # ── Settings ──────────────────────────────────────────────────────────────
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS settings (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            updated_at TEXT DEFAULT {NOW_SQL}
        )
    """)
    # Seed defaults (only if not already set)
    cursor.execute("""
        INSERT INTO settings (key, value) VALUES
        ('commission_rate', '10'),
        ('service_commission_rate', '10'),
        ('accommodation_commission_rate', '5'),
        ('contact_phone', '+263 77 412 8219'),
        ('contact_email', 'terrencemuromba@gmail.com'),
        ('contact_website', 'https://t-techsolutions.co.zw'),
        ('contact_location', 'Harare, Zimbabwe'),
        ('auto_post_facebook', '0'),
        ('newsletter_enabled', '1'),
        ('whatsapp_business_number', '263774128219'),
        ('bank_details', 'FBC Bank | Account: 1234567890 | Branch: Harare CBD | Reference: your order ref'),
        ('welcome_banner_url', '')
        ON CONFLICT (key) DO NOTHING
    """)

    # ── Audit log ─────────────────────────────────────────────────────────────
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS audit_log (
            id          SERIAL PRIMARY KEY,
            admin_phone TEXT NOT NULL,
            action      TEXT NOT NULL,
            target_type TEXT DEFAULT '',
            target_id   TEXT DEFAULT '',
            detail      TEXT DEFAULT '',
            created_at  TEXT DEFAULT {NOW_SQL}
        )
    """)

    # ── Rate limiting (persistent) ─────────────────────────────────────────────
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS rate_limit (
            id         SERIAL PRIMARY KEY,
            phone      TEXT NOT NULL,
            hit_at     TEXT DEFAULT {NOW_SQL}
        )
    """)

    # ── Message send log (for failure tracking) ────────────────────────────────
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS send_log (
            id          SERIAL PRIMARY KEY,
            to_phone    TEXT NOT NULL,
            message     TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'sent',
            error       TEXT DEFAULT '',
            sent_at     TEXT DEFAULT {NOW_SQL}
        )
    """)

    # ── Services tables ───────────────────────────────────────────────────────

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS services (
            id                SERIAL PRIMARY KEY,
            title             TEXT NOT NULL,
            category          TEXT NOT NULL,
            description       TEXT,
            price_type        TEXT NOT NULL DEFAULT 'quoted',
            price             DOUBLE PRECISION DEFAULT 0,
            currency          TEXT DEFAULT 'USD',
            service_area      TEXT DEFAULT '',
            provider_phone    TEXT NOT NULL,
            provider_name     TEXT,
            provider_business TEXT,
            status            TEXT NOT NULL DEFAULT 'pending',
            rejection_reason  TEXT,
            created_at        TEXT DEFAULT {NOW_SQL}
        )
    """)

    for col, definition in [
        ("seller_location", "TEXT DEFAULT ''"),
        ("offers_delivery", "INTEGER DEFAULT 0"),
        ("delivery_info",   "TEXT DEFAULT ''"),
        ("extra_services",  "TEXT DEFAULT ''"),
        ("is_official",     "INTEGER NOT NULL DEFAULT 0"),
    ]:
        cursor.execute(f"ALTER TABLE services ADD COLUMN IF NOT EXISTS {col} {definition}")

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS service_reviews (
            id             SERIAL PRIMARY KEY,
            service_id     INTEGER NOT NULL,
            reviewer_phone TEXT NOT NULL,
            rating         INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
            comment        TEXT DEFAULT '',
            created_at     TEXT DEFAULT {NOW_SQL},
            UNIQUE(service_id, reviewer_phone)
        )
    """)

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS service_enquiries (
            id             SERIAL PRIMARY KEY,
            service_id     INTEGER NOT NULL,
            customer_phone TEXT NOT NULL,
            customer_name  TEXT NOT NULL,
            details        TEXT DEFAULT '',
            status         TEXT NOT NULL DEFAULT 'new',
            created_at     TEXT DEFAULT {NOW_SQL}
        )
    """)

    # ── Quotations ────────────────────────────────────────────────────────────
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS quotations (
            id             SERIAL PRIMARY KEY,
            reference      TEXT UNIQUE NOT NULL,
            buyer_phone    TEXT NOT NULL,
            buyer_name     TEXT DEFAULT '',
            item_type      TEXT NOT NULL DEFAULT 'product',
            category       TEXT DEFAULT '',
            description    TEXT NOT NULL,
            quantity       TEXT DEFAULT '',
            budget         TEXT DEFAULT '',
            product_id     INTEGER,
            service_id     INTEGER,
            seller_phone   TEXT DEFAULT '',
            seller_name    TEXT DEFAULT '',
            status         TEXT NOT NULL DEFAULT 'open',
            quoted_price   DOUBLE PRECISION,
            seller_message TEXT DEFAULT '',
            created_at     TEXT DEFAULT {NOW_SQL},
            updated_at     TEXT DEFAULT {NOW_SQL}
        )
    """)

    # ── Property shortlist ────────────────────────────────────────────────────
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS property_shortlist (
            id          SERIAL PRIMARY KEY,
            phone       TEXT NOT NULL,
            property_id INTEGER NOT NULL,
            prop_data   TEXT NOT NULL DEFAULT '{{}}',
            added_at    TEXT DEFAULT {NOW_SQL},
            UNIQUE(phone, property_id)
        )
    """)

    # ── Viewing appointments ───────────────────────────────────────────────────
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS viewing_appointments (
            id             SERIAL PRIMARY KEY,
            phone          TEXT NOT NULL,
            tenant_name    TEXT NOT NULL,
            property_id    INTEGER NOT NULL,
            property_title TEXT DEFAULT '',
            landlord_phone TEXT DEFAULT '',
            preferred_date TEXT NOT NULL,
            preferred_time TEXT NOT NULL DEFAULT 'Morning',
            status         TEXT NOT NULL DEFAULT 'pending',
            created_at     TEXT DEFAULT {NOW_SQL}
        )
    """)

    # ── Property viewings (fee-gated access) ─────────────────────────────────
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS property_viewings (
            id             SERIAL PRIMARY KEY,
            phone          TEXT NOT NULL,
            property_id    INTEGER NOT NULL,
            property_title TEXT DEFAULT '',
            fee_amount     DOUBLE PRECISION NOT NULL,
            payment_method TEXT DEFAULT '',
            status         TEXT NOT NULL DEFAULT 'pending',
            created_at     TEXT DEFAULT {NOW_SQL},
            UNIQUE(phone, property_id)
        )
    """)

    # ── Seller-paid marketing campaigns ───────────────────────────────────────
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS marketing_campaigns (
            id             SERIAL PRIMARY KEY,
            seller_phone   TEXT NOT NULL,
            product_id     INTEGER,
            plan_type      TEXT NOT NULL,
            platforms      TEXT NOT NULL,
            fee_amount     DOUBLE PRECISION NOT NULL,
            status         TEXT NOT NULL DEFAULT 'pending_payment',
            payment_method TEXT DEFAULT '',
            starts_at      TEXT,
            expires_at     TEXT,
            last_posted_at TEXT,
            created_at     TEXT DEFAULT {NOW_SQL}
        )
    """)

    cursor.execute("ALTER TABLE social_posts ADD COLUMN IF NOT EXISTS campaign_id INTEGER")

    # ── Promo / discount codes ────────────────────────────────────────────────
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS promo_codes (
            id         SERIAL PRIMARY KEY,
            code       TEXT UNIQUE NOT NULL,
            type       TEXT NOT NULL DEFAULT 'percent',
            value      DOUBLE PRECISION NOT NULL,
            min_order  DOUBLE PRECISION DEFAULT 0,
            max_uses   INTEGER DEFAULT 0,
            used_count INTEGER DEFAULT 0,
            active     INTEGER DEFAULT 1,
            expires_at TEXT,
            created_at TEXT DEFAULT {NOW_SQL}
        )
    """)

    # ── Refund requests ───────────────────────────────────────────────────────
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS refund_requests (
            id          SERIAL PRIMARY KEY,
            reference   TEXT UNIQUE NOT NULL,
            order_ref   TEXT NOT NULL,
            buyer_phone TEXT NOT NULL,
            reason      TEXT NOT NULL,
            amount      DOUBLE PRECISION NOT NULL,
            status      TEXT NOT NULL DEFAULT 'pending',
            resolution  TEXT DEFAULT '',
            created_at  TEXT DEFAULT {NOW_SQL},
            updated_at  TEXT DEFAULT {NOW_SQL}
        )
    """)

    # ── Product variants (size, colour, etc.) ─────────────────────────────────
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS product_variants (
            id         SERIAL PRIMARY KEY,
            product_id INTEGER NOT NULL,
            label      TEXT NOT NULL,
            price_adj  DOUBLE PRECISION DEFAULT 0,
            stock_qty  INTEGER DEFAULT 0,
            created_at TEXT DEFAULT {NOW_SQL}
        )
    """)

    # ── Seller payouts ────────────────────────────────────────────────────────
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS seller_payouts (
            id           SERIAL PRIMARY KEY,
            seller_phone TEXT NOT NULL,
            amount       DOUBLE PRECISION NOT NULL,
            period       TEXT NOT NULL,
            order_count  INTEGER DEFAULT 0,
            status       TEXT NOT NULL DEFAULT 'pending',
            paid_via     TEXT DEFAULT '',
            paid_at      TEXT,
            notes        TEXT DEFAULT '',
            created_at   TEXT DEFAULT {NOW_SQL}
        )
    """)

    # ── Exchange rates (USD ↔ ZiG) ────────────────────────────────────────────
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS exchange_rates (
            id         SERIAL PRIMARY KEY,
            from_cur   TEXT NOT NULL,
            to_cur     TEXT NOT NULL,
            rate       DOUBLE PRECISION NOT NULL,
            updated_at TEXT DEFAULT {NOW_SQL},
            UNIQUE(from_cur, to_cur)
        )
    """)
    cursor.execute("""
        INSERT INTO exchange_rates (from_cur, to_cur, rate)
        VALUES ('USD', 'ZiG', 26.0)
        ON CONFLICT (from_cur, to_cur) DO NOTHING
    """)

    # ── Cancellation log ──────────────────────────────────────────────────────
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS order_cancellations (
            id          SERIAL PRIMARY KEY,
            order_ref   TEXT NOT NULL,
            buyer_phone TEXT NOT NULL,
            reason      TEXT DEFAULT '',
            cancelled_at TEXT DEFAULT {NOW_SQL}
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS seller_otps (
            phone      TEXT PRIMARY KEY,
            code       TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            attempts   INTEGER DEFAULT 0
        )
    """)
    cursor.execute("ALTER TABLE seller_otps ADD COLUMN IF NOT EXISTS attempts INTEGER DEFAULT 0")

    # Durable record of a cart snapshot at EcoCash-checkout time, keyed by the
    # same reference Paynow echoes back on /paynow/result. Without this, order
    # creation depended entirely on the buyer replying "paid" in a WhatsApp
    # session that expires after 30 minutes — a real, gateway-confirmed
    # payment could otherwise leave no order at all. Whichever of the two
    # paths (buyer's "paid" reply, or the Paynow webhook) gets there first
    # claims the row via the status flip below; the other becomes a no-op.
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS pending_cart_payments (
            reference        TEXT PRIMARY KEY,
            buyer_phone      TEXT NOT NULL,
            cart_id          TEXT NOT NULL,
            cart_json        TEXT NOT NULL,
            total            DOUBLE PRECISION NOT NULL,
            delivery_type    TEXT DEFAULT 'self_collect',
            delivery_address TEXT DEFAULT '',
            payment_method   TEXT DEFAULT 'EcoCash',
            poll_url         TEXT,
            status           TEXT DEFAULT 'pending',
            created_at       TEXT DEFAULT {NOW_SQL}
        )
    """)
    # cart_id is the key the cart was actually stored under — the buyer's own
    # phone for the WhatsApp flow, but a synthetic per-browser-session id for
    # anonymous web checkout, where it can differ from buyer_phone. Needed so
    # the pending-payment fallback path clears the right cart row.
    cursor.execute("ALTER TABLE pending_cart_payments ADD COLUMN IF NOT EXISTS cart_id TEXT")
    cursor.execute("UPDATE pending_cart_payments SET cart_id = buyer_phone WHERE cart_id IS NULL")
    cursor.execute("ALTER TABLE pending_cart_payments ADD COLUMN IF NOT EXISTS poll_url TEXT")

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS seller_expenses (
            id          SERIAL PRIMARY KEY,
            seller_phone TEXT NOT NULL,
            amount      DOUBLE PRECISION NOT NULL,
            category    TEXT NOT NULL DEFAULT 'Other',
            description TEXT DEFAULT '',
            expense_date DATE NOT NULL DEFAULT CURRENT_DATE,
            created_at  TEXT DEFAULT {NOW_SQL}
        )
    """)

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS stock_movements (
            id         SERIAL PRIMARY KEY,
            product_id INTEGER NOT NULL,
            seller_phone TEXT NOT NULL,
            change_qty INTEGER NOT NULL,
            reason     TEXT NOT NULL DEFAULT 'adjustment',
            note       TEXT DEFAULT '',
            created_at TEXT DEFAULT {NOW_SQL}
        )
    """)

    # ── Referrals ─────────────────────────────────────────────────────────────
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS referrals (
            id             SERIAL PRIMARY KEY,
            referrer_phone TEXT NOT NULL,
            referred_phone TEXT NOT NULL,
            status         TEXT NOT NULL DEFAULT 'pending',
            reward_code    TEXT DEFAULT '',
            created_at     TEXT DEFAULT {NOW_SQL},
            UNIQUE(referred_phone)
        )
    """)

    # ── Buyer profiles ────────────────────────────────────────────────────────
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS buyer_profiles (
            phone      TEXT PRIMARY KEY,
            name       TEXT DEFAULT '',
            address    TEXT DEFAULT '',
            updated_at TEXT DEFAULT {NOW_SQL}
        )
    """)

    conn.commit()
    conn.close()
    print("Database initialised (Postgres)")


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


def set_seller_official(phone, is_official):
    conn = get_connection()
    conn.execute("UPDATE sellers SET is_official = ? WHERE phone = ?", (int(bool(is_official)), phone))
    conn.commit()
    conn.close()


def get_pending_sellers():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sellers WHERE status = 'pending' ORDER BY registered_at")
    rows = cursor.fetchall()
    conn.close()
    return rows


# ── Seller OTP (portal login) ─────────────────────────────────────────────────

SELLER_OTP_MAX_ATTEMPTS = 5


def create_seller_otp(phone):
    """Generate a 6-digit OTP valid for 10 minutes. Returns the code."""
    import secrets
    code    = "".join(secrets.choice("0123456789") for _ in range(6))
    expires = (datetime.utcnow() + timedelta(minutes=10)).isoformat()
    conn    = get_connection()
    conn.execute(
        "INSERT INTO seller_otps(phone, code, expires_at, attempts) VALUES(?,?,?,0) "
        "ON CONFLICT(phone) DO UPDATE SET code=excluded.code, expires_at=excluded.expires_at, attempts=0",
        (phone, code, expires)
    )
    conn.commit()
    conn.close()
    return code


def verify_seller_otp(phone, code):
    """Return True if code matches and has not expired and the attempt cap
    hasn't been hit, then delete it. Every wrong guess counts against the
    cap so the code can't be brute-forced."""
    conn = get_connection()
    row  = conn.execute(
        "SELECT code, expires_at, attempts FROM seller_otps WHERE phone=?", (phone,)
    ).fetchone()
    if not row:
        conn.close()
        return False
    if row["attempts"] >= SELLER_OTP_MAX_ATTEMPTS or datetime.utcnow() > datetime.fromisoformat(row["expires_at"]):
        conn.execute("DELETE FROM seller_otps WHERE phone=?", (phone,))
        conn.commit()
        conn.close()
        return False
    if row["code"] != code:
        conn.execute("UPDATE seller_otps SET attempts = attempts + 1 WHERE phone=?", (phone,))
        conn.commit()
        conn.close()
        return False
    conn.execute("DELETE FROM seller_otps WHERE phone=?", (phone,))
    conn.commit()
    conn.close()
    return True


def delete_product_by_seller(product_id, seller_phone):
    """Delete a product only if it belongs to this seller."""
    conn = get_connection()
    conn.execute(
        "DELETE FROM products WHERE id=? AND listed_by=?", (product_id, seller_phone)
    )
    conn.commit()
    conn.close()


def delete_service_by_seller(service_id, seller_phone):
    """Delete a service only if it belongs to this seller."""
    conn = get_connection()
    conn.execute(
        "DELETE FROM services WHERE id=? AND provider_phone=?", (service_id, seller_phone)
    )
    conn.commit()
    conn.close()


# ── Products ──────────────────────────────────────────────────────────────────

def sanitize_fts_query(query):
    return re.sub(r'[\"()*:^~]', '', query).strip()


def add_product(name, category, price, stock_qty, description,
                image_path=None, listed_by=None,
                product_type="physical", product_file_path=None,
                stock_unit="pcs", seller_location="",
                offers_delivery=0, delivery_info="", extra_services="",
                payment_methods="", currency="USD"):
    seller      = get_seller(listed_by) if listed_by else None
    is_official = bool(seller and seller.get("is_official"))
    if is_official:
        commission = 0.0
        status     = "approved"
    else:
        rate       = float(get_setting("commission_rate", "10")) / 100
        commission = round(price * stock_qty * rate, 2)
        status     = "pending"
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO products
            (name, category, price, commission, stock_qty, description,
             image_path, listed_by, status, product_type, product_file_path,
             stock_unit, seller_location, offers_delivery, delivery_info,
             extra_services, payment_methods, currency, is_official)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
    """, (name, category, price, commission, stock_qty, description,
          image_path, listed_by, status, product_type, product_file_path,
          stock_unit, seller_location, offers_delivery, delivery_info,
          extra_services, payment_methods, currency, int(is_official)))
    product_id = cursor.fetchone()["id"]
    conn.commit()
    conn.close()
    return product_id, commission


def search_products(query):
    """Simple ILIKE search across name/category/description (Postgres has no
    built-in equivalent of SQLite's FTS5 virtual tables)."""
    safe_query = sanitize_fts_query(query)
    if not safe_query:
        return []
    conn = get_connection()
    cursor = conn.cursor()
    like = f"%{safe_query}%"
    try:
        cursor.execute("""
            SELECT p.id, p.name, p.category, p.price, p.stock_qty, p.description,
                   p.image_path, p.product_type, p.stock_unit, p.seller_location,
                   p.offers_delivery, p.listed_by, p.is_official,
                   s.name AS seller_name, s.business_name, s.location AS seller_city,
                   ROUND(COALESCE(AVG(r.rating), 0)::numeric, 1) AS avg_rating,
                   COUNT(r.id) AS review_count
            FROM products p
            LEFT JOIN sellers s ON p.listed_by = s.phone
            LEFT JOIN product_reviews r ON r.product_id = p.id
            WHERE p.status = 'approved'
              AND (p.name ILIKE ? OR p.category ILIKE ? OR p.description ILIKE ?)
            GROUP BY p.id, s.name, s.business_name, s.location
            ORDER BY p.price ASC
            LIMIT 8
        """, (like, like, like))
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


def decrement_stock_if_available(product_id, quantity):
    """Atomically decrements stock only if enough is still available, guarding
    against two concurrent buyers of the last unit both passing a stale
    Python-side check. Returns the new stock_qty on success, or None if there
    wasn't enough stock left (caller should treat that as sold out)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """UPDATE products SET stock_qty = stock_qty - ?
           WHERE id = ? AND stock_qty >= ? RETURNING stock_qty""",
        (quantity, product_id, quantity)
    )
    row = cursor.fetchone()
    conn.commit()
    conn.close()
    return row["stock_qty"] if row else None


def save_pending_cart_payment(reference, buyer_phone, cart_json, total,
                               delivery_type="self_collect", delivery_address="",
                               payment_method="EcoCash", cart_id=None, poll_url=None):
    """Snapshots the cart at EcoCash-checkout time so /paynow/result can create
    the order even if the buyer never replies "paid" (or their session
    expires first). cart_id defaults to buyer_phone (how the WhatsApp cart is
    keyed); pass it explicitly for the web checkout, where the cart is keyed
    by a synthetic per-browser-session id instead."""
    conn = get_connection()
    conn.execute(
        """INSERT INTO pending_cart_payments
               (reference, buyer_phone, cart_id, cart_json, total, delivery_type,
                delivery_address, payment_method, poll_url)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT (reference) DO NOTHING""",
        (reference, buyer_phone, cart_id or buyer_phone, cart_json, total,
         delivery_type, delivery_address, payment_method, poll_url)
    )
    conn.commit()
    conn.close()


def get_pending_cart_payment(reference):
    """Read-only lookup — does not claim the row. Used to tell 'never existed'
    apart from 'already claimed by the other path' when deciding whether to
    fall back to a generic notification."""
    conn = get_connection()
    row  = conn.execute(
        "SELECT * FROM pending_cart_payments WHERE reference=?", (reference,)
    ).fetchone()
    conn.close()
    return row


def claim_pending_cart_payment(reference):
    """Atomically flips a pending cart payment to 'completed' and returns the
    row — but only the first caller to reach this wins. Whichever of the
    buyer's WhatsApp "paid" reply or the Paynow webhook gets here first
    creates the order; the other sees no row and does nothing, so the order
    is never created twice."""
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """UPDATE pending_cart_payments SET status='completed'
           WHERE reference=? AND status='pending' RETURNING *""",
        (reference,)
    )
    row = cursor.fetchone()
    conn.commit()
    conn.close()
    return row


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
        SELECT p.id, p.name, p.category, p.price, p.stock_qty, p.description,
               p.image_path, p.product_type, p.stock_unit, p.seller_location,
               p.offers_delivery, p.listed_by, p.is_official,
               s.name AS seller_name, s.business_name, s.location AS seller_city,
               ROUND(COALESCE(AVG(r.rating), 0)::numeric, 1) AS avg_rating,
               COUNT(r.id) AS review_count
        FROM products p
        LEFT JOIN sellers s ON p.listed_by = s.phone
        LEFT JOIN product_reviews r ON r.product_id = p.id
        WHERE LOWER(p.category) = LOWER(?) AND p.status = 'approved'
        GROUP BY p.id, s.name, s.business_name, s.location
        ORDER BY p.price ASC
    """, (category,))
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_seller_products(phone):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, category, price, stock_qty, status, created_at,
               description, image_path
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
        RETURNING id
    """, (buyer_phone, product_id, quantity, unit_price, total, ref,
          delivery_type, delivery_address))
    order_id = cursor.fetchone()["id"]
    conn.commit()
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
        SELECT o.id, o.reference, p.name, p.category,
               o.quantity, o.unit_price, o.total_price, o.status,
               o.delivery_type, o.created_at,
               s.business_name AS seller_name
        FROM orders o
        JOIN products p ON o.product_id = p.id
        LEFT JOIN sellers s ON p.listed_by = s.phone
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


def check_buyer_has_access(buyer_phone, product_id):
    """Return the fulfilled order row if buyer has paid for this digital product."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM orders WHERE buyer_phone=? AND product_id=? AND status='fulfilled'",
        (buyer_phone, product_id)
    ).fetchone()
    conn.close()
    return row


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
    now = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
    conn = get_connection()
    conn.execute("""
        INSERT INTO sessions (phone, state, data, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(phone) DO UPDATE SET
            state      = excluded.state,
            data       = excluded.data,
            updated_at = excluded.updated_at
    """, (phone, state, payload, now))
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
            "INSERT INTO waitlist (phone, product_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
            (phone, product_id)
        )
        conn.commit()
    except Exception:
        conn.rollback()
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
    now = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
    conn = get_connection()
    conn.execute("""
        INSERT INTO settings (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
    """, (key, str(value), now))
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
                service_area, provider_phone, provider_name="", provider_business="",
                seller_location="", offers_delivery=0, delivery_info="", extra_services=""):
    seller      = get_seller(provider_phone) if provider_phone else None
    is_official = bool(seller and seller.get("is_official"))
    status      = "approved" if is_official else "pending"
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO services
            (title, category, description, price_type, price,
             service_area, provider_phone, provider_name, provider_business,
             seller_location, offers_delivery, delivery_info, extra_services,
             status, is_official)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
    """, (title, category, description, price_type, price,
          service_area, provider_phone, provider_name, provider_business,
          seller_location, offers_delivery, delivery_info, extra_services,
          status, int(is_official)))
    service_id = cursor.fetchone()["id"]
    conn.commit()
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
               ROUND(COALESCE(AVG(r.rating), 0)::numeric, 1) AS avg_rating,
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
               ROUND(COALESCE(AVG(r.rating), 0)::numeric, 1) AS avg_rating,
               COUNT(r.id) AS review_count
        FROM services s
        LEFT JOIN service_reviews r ON r.service_id = s.id
        WHERE s.status = 'approved'
          AND (s.title ILIKE ? OR s.category ILIKE ? OR s.description ILIKE ? OR s.service_area ILIKE ?)
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
               ROUND(COALESCE(AVG(r.rating), 0)::numeric, 1) AS avg_rating,
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
        conn.rollback()
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
        success = True
    except Exception:
        conn.rollback()
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
        SELECT ROUND(COALESCE(AVG(rating), 0)::numeric, 1) AS avg, COUNT(*) AS cnt
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
          AND hit_at::timestamp > (NOW() AT TIME ZONE 'UTC' + (? || ' seconds')::interval)
    """, (phone, f"-{window_secs}"))
    count = cursor.fetchone()[0]
    if count >= max_hits:
        conn.close()
        return True   # rate limited
    conn.execute("INSERT INTO rate_limit (phone) VALUES (?)", (phone,))
    # Purge old entries older than 2x window to keep table small
    conn.execute("""
        DELETE FROM rate_limit
        WHERE hit_at::timestamp < (NOW() AT TIME ZONE 'UTC' + (? || ' seconds')::interval)
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
    cur = conn.execute("""
        DELETE FROM sessions
        WHERE updated_at::timestamp < (NOW() AT TIME ZONE 'UTC' + (? || ' minutes')::interval)
    """, (f"-{max_age_minutes}",))
    deleted = cur.rowcount
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
            quantity = cart.quantity + excluded.quantity,
            added_at = excluded.added_at
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
               p.name, p.price, p.stock_qty, p.category, p.listed_by,
               p.image_path, p.product_type
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


def get_cart_by_seller(phone):
    """Return cart items grouped by seller as a list of dicts with seller info and items."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.product_id, c.quantity,
               p.name, p.price, p.stock_qty, p.category, p.listed_by,
               s.name AS seller_name, s.business_name
        FROM cart c
        JOIN products p ON c.product_id = p.id
        LEFT JOIN sellers s ON p.listed_by = s.phone
        WHERE c.phone = ? AND p.status = 'approved'
        ORDER BY p.listed_by, c.added_at ASC
    """, (phone,))
    rows = cursor.fetchall()
    conn.close()

    groups = {}
    order = []
    for row in rows:
        r = dict(row)
        seller_phone = r.get("listed_by") or "unknown"
        if seller_phone not in groups:
            groups[seller_phone] = {
                "seller_phone": seller_phone,
                "seller_name": r.get("business_name") or r.get("seller_name") or "Seller",
                "items": [],
            }
            order.append(seller_phone)
        groups[seller_phone]["items"].append(r)

    return [groups[sp] for sp in order]


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
        RETURNING id
    """, (ref, order_id, buyer_phone, seller_phone, issue_type, description))
    dispute_id = cursor.fetchone()["id"]
    conn.commit()
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
    now = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
    conn = get_connection()
    conn.execute("""
        UPDATE disputes SET status = ?, resolution = ?, updated_at = ?
        WHERE id = ?
    """, (status, resolution, now, dispute_id))
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
    conn.execute("INSERT INTO newsletter_subs (phone) VALUES (?) ON CONFLICT DO NOTHING", (phone,))
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

def log_social_post(platform, post_id, product_id=None, service_id=None, status="sent", campaign_id=None):
    conn = get_connection()
    conn.execute("""
        INSERT INTO social_posts (product_id, service_id, platform, post_id, status, campaign_id)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (product_id, service_id, platform, post_id or "", status, campaign_id))
    conn.commit()
    conn.close()


# ── Seller-paid marketing campaigns ─────────────────────────────────────────

def create_marketing_campaign(seller_phone, product_id, plan_type, platforms, fee_amount, payment_method=""):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO marketing_campaigns
            (seller_phone, product_id, plan_type, platforms, fee_amount, payment_method)
        VALUES (?, ?, ?, ?, ?, ?)
        RETURNING id
    """, (seller_phone, product_id, plan_type, platforms, fee_amount, payment_method))
    campaign_id = cursor.fetchone()["id"]
    conn.commit()
    conn.close()
    return campaign_id


def get_marketing_campaign(campaign_id):
    conn = get_connection()
    row  = conn.execute(
        "SELECT * FROM marketing_campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    conn.close()
    return row


def get_marketing_campaign_by_ref(reference):
    conn = get_connection()
    row  = conn.execute(
        "SELECT * FROM marketing_campaigns WHERE payment_method LIKE ? AND status='pending_payment' LIMIT 1",
        (f"%:{reference}",)
    ).fetchone()
    conn.close()
    return row


def activate_marketing_campaign(campaign_id, period_days=None):
    conn = get_connection()
    if period_days:
        conn.execute(f"""
            UPDATE marketing_campaigns
            SET status = 'active', starts_at = {NOW_SQL},
                expires_at = to_char((NOW() AT TIME ZONE 'UTC') + make_interval(days => ?), 'YYYY-MM-DD HH24:MI:SS')
            WHERE id = ?
        """, (int(period_days), campaign_id))
    else:
        conn.execute(f"""
            UPDATE marketing_campaigns
            SET status = 'active', starts_at = {NOW_SQL}, expires_at = NULL
            WHERE id = ?
        """, (campaign_id,))
    conn.commit()
    conn.close()


def mark_marketing_campaign_posted(campaign_id):
    conn = get_connection()
    conn.execute(f"""
        UPDATE marketing_campaigns SET last_posted_at = {NOW_SQL} WHERE id = ?
    """, (campaign_id,))
    conn.commit()
    conn.close()


def get_seller_marketing_campaigns(seller_phone):
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM marketing_campaigns WHERE seller_phone = ?
        ORDER BY created_at DESC
    """, (seller_phone,)).fetchall()
    conn.close()
    return rows


def get_all_marketing_campaigns():
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM marketing_campaigns ORDER BY created_at DESC LIMIT 200
    """).fetchall()
    conn.close()
    return rows


def get_due_subscription_campaigns(repost_interval_days):
    conn = get_connection()
    rows = conn.execute(f"""
        SELECT * FROM marketing_campaigns
        WHERE plan_type = 'subscription' AND status = 'active'
          AND (expires_at IS NULL OR expires_at > {NOW_SQL})
          AND (last_posted_at IS NULL
               OR last_posted_at < to_char((NOW() AT TIME ZONE 'UTC') - make_interval(days => ?), 'YYYY-MM-DD HH24:MI:SS'))
    """, (int(repost_interval_days),)).fetchall()
    conn.close()
    return rows


def get_expired_marketing_campaigns():
    conn = get_connection()
    rows = conn.execute(f"""
        SELECT * FROM marketing_campaigns
        WHERE status = 'active' AND expires_at IS NOT NULL AND expires_at <= {NOW_SQL}
    """).fetchall()
    conn.close()
    return rows


def expire_marketing_campaign(campaign_id):
    conn = get_connection()
    conn.execute("UPDATE marketing_campaigns SET status = 'expired' WHERE id = ?", (campaign_id,))
    conn.commit()
    conn.close()


# ── Analytics ─────────────────────────────────────────────────────────────────

def get_analytics_summary(days=7):
    conn = get_connection()
    c    = conn.cursor()
    since = f"-{days} days"
    stats = {
        "total_revenue":    c.execute("SELECT COALESCE(SUM(total_price),0) FROM orders WHERE created_at::timestamp > (NOW() AT TIME ZONE 'UTC' + (?)::interval)", (since,)).fetchone()[0],
        "total_orders":     c.execute("SELECT COUNT(*) FROM orders WHERE created_at::timestamp > (NOW() AT TIME ZONE 'UTC' + (?)::interval)", (since,)).fetchone()[0],
        "new_users":        c.execute("SELECT COUNT(DISTINCT phone) FROM message_log WHERE received_at::timestamp > (NOW() AT TIME ZONE 'UTC' + (?)::interval)", (since,)).fetchone()[0],
        "new_listings":     c.execute("SELECT COUNT(*) FROM products WHERE created_at::timestamp > (NOW() AT TIME ZONE 'UTC' + (?)::interval) AND status='approved'", (since,)).fetchone()[0],
        "new_services":     c.execute("SELECT COUNT(*) FROM services WHERE created_at::timestamp > (NOW() AT TIME ZONE 'UTC' + (?)::interval) AND status='approved'", (since,)).fetchone()[0],
        "open_disputes":    c.execute("SELECT COUNT(*) FROM disputes WHERE status='open'", ()).fetchone()[0],
        "newsletter_count": c.execute("SELECT COUNT(*) FROM newsletter_subs", ()).fetchone()[0],
    }
    # Top 5 products by order count
    top_products = c.execute("""
        SELECT p.name, COUNT(*) as cnt, SUM(o.total_price) as revenue
        FROM orders o JOIN products p ON o.product_id = p.id
        WHERE o.created_at::timestamp > (NOW() AT TIME ZONE 'UTC' + (?)::interval)
        GROUP BY o.product_id, p.name ORDER BY cnt DESC LIMIT 5
    """, (since,)).fetchall()
    stats["top_products"] = [dict(r) for r in top_products]

    # Revenue by day
    revenue_by_day = c.execute("""
        SELECT DATE(created_at::timestamp) as day, SUM(total_price) as revenue, COUNT(*) as orders
        FROM orders WHERE created_at::timestamp > (NOW() AT TIME ZONE 'UTC' + (?)::interval)
        GROUP BY day ORDER BY day
    """, (since,)).fetchall()
    stats["revenue_by_day"] = [dict(r) for r in revenue_by_day]

    # Peak hours
    peak_hours = c.execute("""
        SELECT EXTRACT(HOUR FROM received_at::timestamp)::integer as hour, COUNT(*) as hits
        FROM message_log WHERE received_at::timestamp > (NOW() AT TIME ZONE 'UTC' + (?)::interval)
        GROUP BY hour ORDER BY hits DESC LIMIT 3
    """, (since,)).fetchall()
    stats["peak_hours"] = [dict(r) for r in peak_hours]

    # Top service categories
    top_services = c.execute("""
        SELECT category, COUNT(*) as enquiries
        FROM service_enquiries e
        JOIN services s ON e.service_id = s.id
        WHERE e.created_at::timestamp > (NOW() AT TIME ZONE 'UTC' + (?)::interval)
        GROUP BY category ORDER BY enquiries DESC LIMIT 5
    """, (since,)).fetchall()
    stats["top_service_cats"] = [dict(r) for r in top_services]

    conn.close()
    return stats


def _time_filter(days, column="created_at"):
    """Build a WHERE fragment + params restricting `column` to the last `days`
    days, or an always-true fragment when days is falsy (all-time)."""
    if days:
        return f"{column}::timestamp > (NOW() AT TIME ZONE 'UTC' + (?)::interval)", (f"-{days} days",)
    return "1=1", ()


def get_ecommerce_analytics(days=30):
    """Admin 'Statistics' tab: revenue/order trends, top products & categories,
    top customers and repeat-purchase behaviour, order-status mix, service
    demand and peak activity hours. `days=None` means all-time."""
    conn = get_connection()
    c    = conn.cursor()

    where, params           = _time_filter(days, "created_at")
    where_o, params_o       = _time_filter(days, "o.created_at")
    where_e, params_e       = _time_filter(days, "e.created_at")
    where_msg, params_msg   = _time_filter(days, "received_at")

    total_revenue = c.execute(f"SELECT COALESCE(SUM(total_price),0) FROM orders WHERE {where}", params).fetchone()[0]
    total_orders  = c.execute(f"SELECT COUNT(*) FROM orders WHERE {where}", params).fetchone()[0]
    avg_order_value = (total_revenue / total_orders) if total_orders else 0

    unique_customers = c.execute(f"SELECT COUNT(DISTINCT buyer_phone) FROM orders WHERE {where}", params).fetchone()[0]

    if days:
        new_customers = c.execute("""
            SELECT COUNT(*) FROM (
                SELECT buyer_phone, MIN(created_at::timestamp) as first_order
                FROM orders GROUP BY buyer_phone
            ) f WHERE f.first_order > (NOW() AT TIME ZONE 'UTC' + (?)::interval)
        """, (f"-{days} days",)).fetchone()[0]
    else:
        new_customers = unique_customers
    returning_customers = max(unique_customers - new_customers, 0)

    repeat_row = c.execute("""
        SELECT COUNT(*) FILTER (WHERE cnt > 1) as repeat_cnt, COUNT(*) as total_cnt
        FROM (SELECT buyer_phone, COUNT(*) as cnt FROM orders GROUP BY buyer_phone) t
    """).fetchone()
    repeat_customer_rate = (repeat_row["repeat_cnt"] / repeat_row["total_cnt"] * 100) if repeat_row["total_cnt"] else 0

    top_products = c.execute(f"""
        SELECT p.name, p.category, COUNT(*) as orders, COALESCE(SUM(o.quantity),0) as qty,
               SUM(o.total_price) as revenue
        FROM orders o JOIN products p ON o.product_id = p.id
        WHERE {where_o}
        GROUP BY p.id, p.name, p.category ORDER BY revenue DESC LIMIT 10
    """, params_o).fetchall()

    category_breakdown = c.execute(f"""
        SELECT COALESCE(p.category, 'Uncategorised') as category, COUNT(*) as orders,
               SUM(o.total_price) as revenue
        FROM orders o JOIN products p ON o.product_id = p.id
        WHERE {where_o}
        GROUP BY p.category ORDER BY revenue DESC LIMIT 10
    """, params_o).fetchall()

    order_status_breakdown = c.execute(f"""
        SELECT status, COUNT(*) as cnt FROM orders WHERE {where}
        GROUP BY status ORDER BY cnt DESC
    """, params).fetchall()

    top_customers = c.execute(f"""
        SELECT o.buyer_phone as phone, COALESCE(bp.name, '') as name,
               COUNT(*) as orders, SUM(o.total_price) as spent, MAX(o.created_at) as last_order
        FROM orders o LEFT JOIN buyer_profiles bp ON o.buyer_phone = bp.phone
        WHERE {where_o}
        GROUP BY o.buyer_phone, bp.name ORDER BY spent DESC LIMIT 10
    """, params_o).fetchall()

    revenue_by_day = c.execute(f"""
        SELECT DATE(created_at::timestamp) as day, SUM(total_price) as revenue, COUNT(*) as orders
        FROM orders WHERE {where}
        GROUP BY day ORDER BY day
    """, params).fetchall()

    peak_hours = c.execute(f"""
        SELECT EXTRACT(HOUR FROM received_at::timestamp)::integer as hour, COUNT(*) as hits
        FROM message_log WHERE {where_msg}
        GROUP BY hour ORDER BY hour
    """, params_msg).fetchall()

    top_service_cats = c.execute(f"""
        SELECT s.category, COUNT(*) as enquiries
        FROM service_enquiries e JOIN services s ON e.service_id = s.id
        WHERE {where_e}
        GROUP BY s.category ORDER BY enquiries DESC LIMIT 10
    """, params_e).fetchall()

    conn.close()
    return {
        "days": days,
        "total_revenue": total_revenue,
        "total_orders": total_orders,
        "avg_order_value": avg_order_value,
        "unique_customers": unique_customers,
        "new_customers": new_customers,
        "returning_customers": returning_customers,
        "repeat_customer_rate": repeat_customer_rate,
        "top_products": [dict(r) for r in top_products],
        "category_breakdown": [dict(r) for r in category_breakdown],
        "order_status_breakdown": [dict(r) for r in order_status_breakdown],
        "top_customers": [dict(r) for r in top_customers],
        "revenue_by_day": [dict(r) for r in revenue_by_day],
        "peak_hours": [dict(r) for r in peak_hours],
        "top_service_cats": [dict(r) for r in top_service_cats],
    }


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
    rating_score     = (float(avg_rating) / 5) * 40   # 40 points max from rating
    order_score      = min(fulfillment_rate * 0.4, 40)  # 40 points max
    dispute_penalty  = min(disputes * 10, 20)            # -10 per open dispute, max -20
    score = max(0, min(100, rating_score + order_score - dispute_penalty + 20))  # 20 base

    conn.close()
    return round(score)


def get_featured_products(limit=12):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.id, p.name, p.category, p.price, p.stock_qty,
               p.image_path, p.product_type, p.stock_unit, p.is_official,
               ROUND(COALESCE(AVG(r.rating), 0)::numeric, 1) AS avg_rating,
               COUNT(r.id) AS review_count
        FROM products p
        LEFT JOIN product_reviews r ON r.product_id = p.id
        WHERE p.status = 'approved' AND (p.stock_qty > 0 OR p.product_type = 'digital')
        GROUP BY p.id
        ORDER BY avg_rating DESC, p.created_at DESC
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_distinct_categories():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT category, COUNT(*) as count
        FROM products
        WHERE status = 'approved'
        GROUP BY category
        ORDER BY count DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Quotations ────────────────────────────────────────────────────────────────

def create_quotation(buyer_phone, buyer_name, item_type, category, description,
                     quantity="", budget="", product_id=None, service_id=None,
                     seller_phone=""):
    ref  = f"QTTC-{uuid.uuid4().hex[:6].upper()}"
    conn = get_connection()
    conn.execute("""
        INSERT INTO quotations
            (reference, buyer_phone, buyer_name, item_type, category, description,
             quantity, budget, product_id, service_id, seller_phone)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (ref, buyer_phone, buyer_name, item_type, category, description,
          quantity, budget, product_id, service_id, seller_phone))
    conn.commit()
    conn.close()
    return ref


def get_quotation_by_ref(reference):
    conn = get_connection()
    row  = conn.execute(
        "SELECT * FROM quotations WHERE reference = ?", (reference,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_buyer_quotations(buyer_phone, limit=10):
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM quotations
        WHERE buyer_phone = ?
        ORDER BY created_at DESC LIMIT ?
    """, (buyer_phone, limit))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_seller_quote_requests(seller_phone, limit=10):
    """Quote requests directed at this seller, or open requests with no seller set."""
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM quotations
        WHERE (seller_phone = ? OR seller_phone = '')
          AND status = 'open'
        ORDER BY created_at DESC LIMIT ?
    """, (seller_phone, limit))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def respond_to_quotation(reference, seller_phone, seller_name, quoted_price, seller_message=""):
    now = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
    conn = get_connection()
    conn.execute("""
        UPDATE quotations
        SET status         = 'quoted',
            seller_phone   = ?,
            seller_name    = ?,
            quoted_price   = ?,
            seller_message = ?,
            updated_at     = ?
        WHERE reference = ?
    """, (seller_phone, seller_name, quoted_price, seller_message, now, reference))
    conn.commit()
    conn.close()


# ── Property viewings ─────────────────────────────────────────────────────────

def create_property_viewing(phone, property_id, property_title, fee_amount, payment_method=""):
    conn = get_connection()
    conn.execute("""
        INSERT INTO property_viewings
            (phone, property_id, property_title, fee_amount, payment_method, status)
        VALUES (?, ?, ?, ?, ?, 'pending')
        ON CONFLICT(phone, property_id) DO UPDATE SET
            fee_amount     = excluded.fee_amount,
            payment_method = excluded.payment_method,
            status         = 'pending'
    """, (phone, property_id, property_title, fee_amount, payment_method))
    conn.commit()
    conn.close()


def confirm_property_viewing(phone, property_id, payment_method):
    conn = get_connection()
    conn.execute("""
        UPDATE property_viewings
        SET status = 'paid', payment_method = ?
        WHERE phone = ? AND property_id = ?
    """, (payment_method, phone, property_id))
    conn.commit()
    conn.close()


def has_paid_viewing_fee(phone, property_id):
    conn = get_connection()
    row  = conn.execute(
        "SELECT 1 FROM property_viewings WHERE phone=? AND property_id=? AND status='paid'",
        (phone, property_id)
    ).fetchone()
    conn.close()
    return row is not None


def get_viewing_stats(limit=20):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM property_viewings ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Property shortlist ─────────────────────────────────────────────────────────

def add_to_shortlist(phone, property_id, prop_data):
    conn = get_connection()
    conn.execute("""
        INSERT INTO property_shortlist (phone, property_id, prop_data)
        VALUES (?, ?, ?)
        ON CONFLICT(phone, property_id) DO UPDATE SET
            prop_data = excluded.prop_data,
            added_at  = excluded.added_at
    """, (phone, property_id, json.dumps(prop_data)))
    conn.commit()
    conn.close()


def remove_from_shortlist(phone, property_id):
    conn = get_connection()
    conn.execute(
        "DELETE FROM property_shortlist WHERE phone=? AND property_id=?",
        (phone, property_id)
    )
    conn.commit()
    conn.close()


def get_shortlist(phone):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM property_shortlist WHERE phone=? ORDER BY added_at DESC",
        (phone,)
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        try:
            result.append(json.loads(r["prop_data"]))
        except Exception:
            pass
    return result


def shortlist_count(phone):
    conn = get_connection()
    count = conn.execute(
        "SELECT COUNT(*) FROM property_shortlist WHERE phone=?", (phone,)
    ).fetchone()[0]
    conn.close()
    return count


def in_shortlist(phone, property_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT 1 FROM property_shortlist WHERE phone=? AND property_id=?",
        (phone, property_id)
    ).fetchone()
    conn.close()
    return row is not None


# ── Viewing appointments ───────────────────────────────────────────────────────

def create_viewing_appointment(phone, tenant_name, property_id, property_title,
                                landlord_phone, preferred_date, preferred_time):
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO viewing_appointments
            (phone, tenant_name, property_id, property_title,
             landlord_phone, preferred_date, preferred_time)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        RETURNING id
    """, (phone, tenant_name, property_id, property_title,
          landlord_phone, preferred_date, preferred_time))
    appt_id = cursor.fetchone()["id"]
    conn.commit()
    conn.close()
    return appt_id


def get_viewing_appointments(phone=None, limit=10):
    conn = get_connection()
    if phone:
        rows = conn.execute(
            "SELECT * FROM viewing_appointments WHERE phone=? ORDER BY created_at DESC LIMIT ?",
            (phone, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM viewing_appointments ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Promo codes ───────────────────────────────────────────────────────────────

def create_promo_code(code, type_, value, min_order=0, max_uses=0, expires_at=None):
    conn = get_connection()
    conn.execute("""
        INSERT INTO promo_codes (code, type, value, min_order, max_uses, expires_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (code) DO NOTHING
    """, (code.upper().strip(), type_, value, min_order, max_uses, expires_at))
    conn.commit()
    conn.close()


def get_promo_code(code):
    conn = get_connection()
    row  = conn.execute(
        "SELECT * FROM promo_codes WHERE code = ? AND active = 1", (code.upper().strip(),)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def use_promo_code(code):
    conn = get_connection()
    conn.execute(
        "UPDATE promo_codes SET used_count = used_count + 1 WHERE code = ?",
        (code.upper().strip(),)
    )
    conn.commit()
    conn.close()


def get_all_promo_codes():
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM promo_codes ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def deactivate_promo_code(code):
    conn = get_connection()
    conn.execute(
        "UPDATE promo_codes SET active = 0 WHERE code = ?", (code.upper().strip(),)
    )
    conn.commit()
    conn.close()


def apply_promo_discount(code, order_total):
    """Validate and calculate discount. Returns (discount_amount, error_msg)."""
    promo = get_promo_code(code)
    if not promo:
        return 0, "Invalid or expired promo code."
    if promo["expires_at"]:
        from datetime import datetime
        if datetime.utcnow() > datetime.fromisoformat(promo["expires_at"]):
            return 0, "This promo code has expired."
    if promo["max_uses"] > 0 and promo["used_count"] >= promo["max_uses"]:
        return 0, "This promo code has reached its usage limit."
    if order_total < promo["min_order"]:
        return 0, f"Minimum order of ${promo['min_order']:.2f} required for this code."
    if promo["type"] == "percent":
        discount = round(order_total * promo["value"] / 100, 2)
    else:
        discount = min(promo["value"], order_total)
    return discount, None


# ── Refund requests ───────────────────────────────────────────────────────────

def create_refund_request(order_ref, buyer_phone, reason, amount):
    ref  = f"REF-{uuid.uuid4().hex[:6].upper()}"
    conn = get_connection()
    conn.execute("""
        INSERT INTO refund_requests (reference, order_ref, buyer_phone, reason, amount)
        VALUES (?, ?, ?, ?, ?)
    """, (ref, order_ref, buyer_phone, reason, amount))
    conn.commit()
    conn.close()
    return ref


def get_refund_requests(status=None, limit=20):
    conn   = get_connection()
    cursor = conn.cursor()
    if status:
        cursor.execute(
            "SELECT * FROM refund_requests WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, limit)
        )
    else:
        cursor.execute(
            "SELECT * FROM refund_requests ORDER BY created_at DESC LIMIT ?", (limit,)
        )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_refund_status(reference, status, resolution=""):
    now = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
    conn = get_connection()
    conn.execute("""
        UPDATE refund_requests
        SET status = ?, resolution = ?, updated_at = ?
        WHERE reference = ?
    """, (status, resolution, now, reference))
    conn.commit()
    conn.close()


def get_buyer_refunds(phone):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM refund_requests WHERE buyer_phone = ? ORDER BY created_at DESC LIMIT 10",
        (phone,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Product variants ──────────────────────────────────────────────────────────

def add_product_variant(product_id, label, price_adj=0, stock_qty=0):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO product_variants (product_id, label, price_adj, stock_qty)
        VALUES (?, ?, ?, ?)
        RETURNING id
    """, (product_id, label.strip(), price_adj, stock_qty))
    variant_id = cursor.fetchone()["id"]
    conn.commit()
    conn.close()
    return variant_id


def get_product_variants(product_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM product_variants WHERE product_id = ? ORDER BY id",
        (product_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_variant_stock(variant_id, new_qty):
    conn = get_connection()
    conn.execute(
        "UPDATE product_variants SET stock_qty = ? WHERE id = ?", (new_qty, variant_id)
    )
    conn.commit()
    conn.close()


# ── Seller payouts ────────────────────────────────────────────────────────────

def create_seller_payout(seller_phone, amount, period, order_count):
    conn = get_connection()
    conn.execute("""
        INSERT INTO seller_payouts (seller_phone, amount, period, order_count)
        VALUES (?, ?, ?, ?)
    """, (seller_phone, amount, period, order_count))
    conn.commit()
    conn.close()


def get_seller_payouts(seller_phone=None, status=None):
    conn   = get_connection()
    cursor = conn.cursor()
    if seller_phone and status:
        cursor.execute(
            "SELECT * FROM seller_payouts WHERE seller_phone=? AND status=? ORDER BY created_at DESC",
            (seller_phone, status)
        )
    elif seller_phone:
        cursor.execute(
            "SELECT * FROM seller_payouts WHERE seller_phone=? ORDER BY created_at DESC",
            (seller_phone,)
        )
    else:
        cursor.execute("SELECT * FROM seller_payouts ORDER BY created_at DESC LIMIT 50")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_payout_paid(payout_id, paid_via="EcoCash"):
    now = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
    conn = get_connection()
    conn.execute("""
        UPDATE seller_payouts
        SET status = 'paid', paid_via = ?, paid_at = ?
        WHERE id = ?
    """, (paid_via, now, payout_id))
    conn.commit()
    conn.close()


def get_seller_earnings_summary(seller_phone):
    """Total earned, pending payout, commission owed."""
    conn = get_connection()
    c    = conn.cursor()
    total_revenue = c.execute("""
        SELECT COALESCE(SUM(o.total_price), 0)
        FROM orders o JOIN products p ON o.product_id = p.id
        WHERE p.listed_by = ? AND o.status IN ('confirmed','fulfilled')
    """, (seller_phone,)).fetchone()[0]

    rate_row = conn.execute(
        "SELECT value FROM settings WHERE key='commission_rate'"
    ).fetchone()
    rate = float(rate_row["value"]) / 100 if rate_row else 0.10

    commission_owed = round(total_revenue * rate, 2)

    paid_out = c.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM seller_payouts WHERE seller_phone=? AND status='paid'",
        (seller_phone,)
    ).fetchone()[0]

    order_count = c.execute("""
        SELECT COUNT(*) FROM orders o JOIN products p ON o.product_id = p.id
        WHERE p.listed_by = ? AND o.status IN ('confirmed','fulfilled')
    """, (seller_phone,)).fetchone()[0]

    conn.close()
    return {
        "total_revenue":   round(total_revenue, 2),
        "commission_owed": commission_owed,
        "paid_out":        round(paid_out, 2),
        "balance_due":     round(commission_owed - paid_out, 2),
        "order_count":     order_count,
    }


# ── Exchange rates ────────────────────────────────────────────────────────────

def get_exchange_rate(from_cur="USD", to_cur="ZiG"):
    conn = get_connection()
    row  = conn.execute(
        "SELECT rate FROM exchange_rates WHERE from_cur=? AND to_cur=?",
        (from_cur, to_cur)
    ).fetchone()
    conn.close()
    return float(row["rate"]) if row else None


def set_exchange_rate(from_cur, to_cur, rate):
    now = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
    conn = get_connection()
    conn.execute("""
        INSERT INTO exchange_rates (from_cur, to_cur, rate, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(from_cur, to_cur) DO UPDATE SET
            rate = excluded.rate, updated_at = excluded.updated_at
    """, (from_cur, to_cur, rate, now))
    conn.commit()
    conn.close()


# ── Order cancellation helpers ────────────────────────────────────────────────

def get_order_by_reference(reference):
    conn = get_connection()
    row  = conn.execute(
        "SELECT * FROM orders WHERE reference = ?", (reference,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def log_cancellation(order_ref, buyer_phone, reason=""):
    conn = get_connection()
    conn.execute("""
        INSERT INTO order_cancellations (order_ref, buyer_phone, reason)
        VALUES (?, ?, ?)
    """, (order_ref, buyer_phone, reason))
    conn.commit()
    conn.close()


# ── Seller stats (for dashboard) ──────────────────────────────────────────────

def get_seller_dashboard_stats(seller_phone):
    conn = get_connection()
    c    = conn.cursor()

    total_orders = c.execute("""
        SELECT COUNT(*) FROM orders o JOIN products p ON o.product_id = p.id
        WHERE p.listed_by = ?
    """, (seller_phone,)).fetchone()[0]

    pending_orders = c.execute("""
        SELECT COUNT(*) FROM orders o JOIN products p ON o.product_id = p.id
        WHERE p.listed_by = ? AND o.status = 'pending'
    """, (seller_phone,)).fetchone()[0]

    fulfilled_orders = c.execute("""
        SELECT COUNT(*) FROM orders o JOIN products p ON o.product_id = p.id
        WHERE p.listed_by = ? AND o.status = 'fulfilled'
    """, (seller_phone,)).fetchone()[0]

    total_revenue = c.execute("""
        SELECT COALESCE(SUM(o.total_price), 0) FROM orders o
        JOIN products p ON o.product_id = p.id
        WHERE p.listed_by = ? AND o.status IN ('confirmed','fulfilled')
    """, (seller_phone,)).fetchone()[0]

    this_month = c.execute("""
        SELECT COALESCE(SUM(o.total_price), 0) FROM orders o
        JOIN products p ON o.product_id = p.id
        WHERE p.listed_by = ? AND o.status IN ('confirmed','fulfilled')
          AND to_char(o.created_at::timestamp, 'YYYY-MM') = to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM')
    """, (seller_phone,)).fetchone()[0]

    active_listings = c.execute(
        "SELECT COUNT(*) FROM products WHERE listed_by = ? AND status = 'approved'",
        (seller_phone,)
    ).fetchone()[0]

    pending_listings = c.execute(
        "SELECT COUNT(*) FROM products WHERE listed_by = ? AND status = 'pending'",
        (seller_phone,)
    ).fetchone()[0]

    open_disputes = c.execute(
        "SELECT COUNT(*) FROM disputes WHERE seller_phone = ? AND status = 'open'",
        (seller_phone,)
    ).fetchone()[0]

    rate_row = conn.execute(
        "SELECT value FROM settings WHERE key='commission_rate'"
    ).fetchone()
    rate = float(rate_row["value"]) / 100 if rate_row else 0.10

    conn.close()
    return {
        "total_orders":    total_orders,
        "pending_orders":  pending_orders,
        "fulfilled_orders": fulfilled_orders,
        "total_revenue":   round(float(total_revenue), 2),
        "month_revenue":   round(float(this_month), 2),
        "commission_rate": int(rate * 100),
        "commission_owed": round(float(total_revenue) * rate, 2),
        "active_listings": active_listings,
        "pending_listings": pending_listings,
        "open_disputes":   open_disputes,
    }


# ── Low-stock check ───────────────────────────────────────────────────────────

def get_low_stock_products(seller_phone, threshold=3):
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, name, stock_qty, stock_unit FROM products
        WHERE listed_by = ? AND status = 'approved'
          AND product_type = 'physical' AND stock_qty <= ? AND stock_qty > 0
        ORDER BY stock_qty ASC
    """, (seller_phone, threshold)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_out_of_stock_products(seller_phone):
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, name, stock_unit FROM products
        WHERE listed_by = ? AND status = 'approved'
          AND product_type = 'physical' AND stock_qty = 0
    """, (seller_phone,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Abandoned cart (web) ──────────────────────────────────────────────────────

def get_nonempty_carts(min_age_minutes=30, max_age_hours=48):
    """Return (phone, item_count, total) for WhatsApp carts idle between 30 min and 48 h."""
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.phone, COUNT(*) AS item_count,
               SUM(p.price * c.quantity) AS total
        FROM cart c
        JOIN products p ON c.product_id = p.id
        WHERE c.phone NOT LIKE 'web-%%'
          AND c.added_at::timestamp < (NOW() AT TIME ZONE 'UTC' + (? || ' minutes')::interval)
          AND c.added_at::timestamp > (NOW() AT TIME ZONE 'UTC' + (? || ' hours')::interval)
        GROUP BY c.phone
    """, (f"-{min_age_minutes}", f"-{max_age_hours}"))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Inventory & Profit ────────────────────────────────────────────────────────

def adjust_stock(product_id, seller_phone, change_qty, reason="adjustment", note=""):
    """Add or subtract stock and log the movement. change_qty can be negative."""
    conn = get_connection()
    conn.execute(
        "UPDATE products SET stock_qty = GREATEST(0, stock_qty + ?) WHERE id = ? AND listed_by = ?",
        (change_qty, product_id, seller_phone)
    )
    conn.execute(
        "INSERT INTO stock_movements (product_id, seller_phone, change_qty, reason, note) "
        "VALUES (?, ?, ?, ?, ?)",
        (product_id, seller_phone, change_qty, reason, note)
    )
    conn.commit()
    conn.close()


def update_product_cost(product_id, seller_phone, cost_price):
    """Set the cost price for a product (used in profit calculation)."""
    conn = get_connection()
    conn.execute(
        "UPDATE products SET cost_price = ? WHERE id = ? AND listed_by = ?",
        (max(0.0, float(cost_price)), product_id, seller_phone)
    )
    conn.commit()
    conn.close()


def get_stock_movements(product_id, seller_phone, limit=30):
    """Recent stock movement log for a product."""
    conn  = get_connection()
    rows  = conn.execute("""
        SELECT change_qty, reason, note, created_at
        FROM stock_movements
        WHERE product_id = ? AND seller_phone = ?
        ORDER BY created_at DESC LIMIT ?
    """, (product_id, seller_phone, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_seller_inventory(seller_phone):
    """Full inventory with stock, cost, revenue and profit per product."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT
            p.id,
            p.name,
            p.category,
            p.price          AS selling_price,
            p.cost_price,
            p.stock_qty,
            p.stock_unit,
            p.status,
            p.product_type,
            COALESCE(SUM(CASE WHEN o.status IN ('confirmed','fulfilled') THEN o.quantity END), 0) AS units_sold,
            COALESCE(SUM(CASE WHEN o.status IN ('confirmed','fulfilled') THEN o.total_price END), 0) AS total_revenue,
            COALESCE(SUM(CASE WHEN o.status = 'pending' THEN o.quantity END), 0) AS units_pending
        FROM products p
        LEFT JOIN orders o ON o.product_id = p.id
        WHERE p.listed_by = ?
        GROUP BY p.id
        ORDER BY p.created_at DESC
    """, (seller_phone,)).fetchall()
    conn.close()

    rate = float(get_setting("commission_rate", "10")) / 100

    result = []
    for r in rows:
        d             = dict(r)
        cost_total    = round(d["cost_price"] * d["units_sold"], 2)
        connect_fee   = round(d["total_revenue"] * rate, 2)
        gross_profit  = round(d["total_revenue"] - cost_total - connect_fee, 2)
        profit_margin = round((gross_profit / d["total_revenue"] * 100), 1) if d["total_revenue"] else 0
        stock_value   = round(d["cost_price"] * d["stock_qty"], 2)
        d.update({
            "cost_total":    cost_total,
            "connect_fee":   connect_fee,
            "gross_profit":  gross_profit,
            "profit_margin": profit_margin,
            "stock_value":   stock_value,
            "rate_pct":      round(rate * 100, 1),
        })
        result.append(d)
    return result


def get_seller_profit_summary(seller_phone):
    """Aggregate profit summary across all products, including expenses for net profit."""
    inventory = get_seller_inventory(seller_phone)
    total_revenue    = sum(p["total_revenue"]  for p in inventory)
    total_cost       = sum(p["cost_total"]     for p in inventory)
    total_fee        = sum(p["connect_fee"]    for p in inventory)
    gross_profit     = sum(p["gross_profit"]   for p in inventory)
    total_stock_val  = sum(p["stock_value"]    for p in inventory)
    total_units_sold = sum(p["units_sold"]     for p in inventory)
    expense_summary  = get_expense_summary(seller_phone)
    total_expenses   = expense_summary["all_time"]
    net_profit       = round(gross_profit - total_expenses, 2)
    gross_margin     = round(gross_profit / total_revenue * 100, 1) if total_revenue else 0
    net_margin       = round(net_profit   / total_revenue * 100, 1) if total_revenue else 0
    return {
        "total_revenue":   round(total_revenue, 2),
        "total_cost":      round(total_cost, 2),
        "total_fee":       round(total_fee, 2),
        "gross_profit":    round(gross_profit, 2),
        "gross_margin":    gross_margin,
        "total_expenses":  total_expenses,
        "net_profit":      net_profit,
        "net_margin":      net_margin,
        "profit_margin":   gross_margin,
        "stock_value":     round(total_stock_val, 2),
        "units_sold":      total_units_sold,
        "product_count":   len(inventory),
    }


# ── Seller Expenses ───────────────────────────────────────────────────────────

EXPENSE_CATEGORIES = [
    "Rent / Utilities",
    "Transport / Delivery",
    "Packaging / Materials",
    "Marketing / Advertising",
    "Supplier / Restocking",
    "Salaries / Labour",
    "Equipment / Repairs",
    "Licences / Permits",
    "Other",
]


def add_expense(seller_phone, amount, category, description="", expense_date=None):
    if expense_date is None:
        expense_date = datetime.utcnow().date().isoformat()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO seller_expenses (seller_phone, amount, category, description, expense_date) "
        "VALUES (?, ?, ?, ?, ?) RETURNING id",
        (seller_phone, round(float(amount), 2), category, description, expense_date)
    )
    expense_id = cursor.fetchone()["id"]
    conn.commit()
    conn.close()
    return expense_id


def get_seller_expenses(seller_phone, limit=100, month=None):
    """Return expenses ordered newest first. Optionally filter by 'YYYY-MM'."""
    conn   = get_connection()
    if month:
        rows = conn.execute("""
            SELECT id, amount, category, description, expense_date, created_at
            FROM seller_expenses
            WHERE seller_phone = ? AND to_char(expense_date, 'YYYY-MM') = ?
            ORDER BY expense_date DESC, created_at DESC LIMIT ?
        """, (seller_phone, month, limit)).fetchall()
    else:
        rows = conn.execute("""
            SELECT id, amount, category, description, expense_date, created_at
            FROM seller_expenses
            WHERE seller_phone = ?
            ORDER BY expense_date DESC, created_at DESC LIMIT ?
        """, (seller_phone, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_expense(expense_id, seller_phone):
    conn = get_connection()
    conn.execute(
        "DELETE FROM seller_expenses WHERE id = ? AND seller_phone = ?",
        (expense_id, seller_phone)
    )
    conn.commit()
    conn.close()


def get_expense_summary(seller_phone):
    """Total expenses and breakdown by category (all time and this month)."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT category,
               SUM(amount)  AS total,
               COUNT(*)     AS count
        FROM seller_expenses
        WHERE seller_phone = ?
        GROUP BY category
        ORDER BY total DESC
    """, (seller_phone,)).fetchall()

    this_month = conn.execute("""
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM seller_expenses
        WHERE seller_phone = ?
          AND to_char(expense_date, 'YYYY-MM') = to_char(NOW() AT TIME ZONE 'UTC', 'YYYY-MM')
    """, (seller_phone,)).fetchone()["total"]

    all_time = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM seller_expenses WHERE seller_phone = ?",
        (seller_phone,)
    ).fetchone()[0]

    conn.close()
    return {
        "all_time":   round(all_time, 2),
        "this_month": round(this_month, 2),
        "by_category": [dict(r) for r in rows],
    }


# ── Referral programme ────────────────────────────────────────────────────────

def create_referral(referrer_phone, referred_phone):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO referrals (referrer_phone, referred_phone) VALUES (?,?) ON CONFLICT DO NOTHING",
            (referrer_phone, referred_phone)
        )
        conn.commit()
    except Exception:
        conn.rollback()
    conn.close()


def get_referral_by_referred(referred_phone):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM referrals WHERE referred_phone = ?", (referred_phone,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def complete_referral(referred_phone, reward_code):
    conn = get_connection()
    conn.execute(
        "UPDATE referrals SET status='rewarded', reward_code=? WHERE referred_phone=?",
        (reward_code, referred_phone)
    )
    conn.commit()
    conn.close()


def get_referral_count(referrer_phone):
    conn = get_connection()
    row = conn.execute(
        "SELECT COUNT(*) as total, "
        "SUM(CASE WHEN status='rewarded' THEN 1 ELSE 0 END) as rewarded "
        "FROM referrals WHERE referrer_phone=?",
        (referrer_phone,)
    ).fetchone()
    conn.close()
    return (row["total"], row["rewarded"]) if row else (0, 0)


# ── Inactive users (re-engagement) ───────────────────────────────────────────

def get_inactive_users(min_days=7, max_days=30):
    """Return phones of users silent for min_days but no more than max_days."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT phone
        FROM message_log
        GROUP BY phone
        HAVING MAX(received_at)::timestamp < (NOW() AT TIME ZONE 'UTC' + (? || ' days')::interval)
           AND MAX(received_at)::timestamp > (NOW() AT TIME ZONE 'UTC' + (? || ' days')::interval)
    """, (f"-{min_days}", f"-{max_days}"))
    rows = cursor.fetchall()
    conn.close()
    return [r["phone"] for r in rows]


# ── Buyer profiles ────────────────────────────────────────────────────────────

def save_buyer_profile(phone, name="", address=""):
    now = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
    conn = get_connection()
    conn.execute("""
        INSERT INTO buyer_profiles (phone, name, address, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(phone) DO UPDATE SET
            name       = COALESCE(NULLIF(excluded.name, ''),    buyer_profiles.name),
            address    = COALESCE(NULLIF(excluded.address, ''), buyer_profiles.address),
            updated_at = excluded.updated_at
    """, (phone, name, address, now))
    conn.commit()
    conn.close()


def get_buyer_profile(phone):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM buyer_profiles WHERE phone = ?", (phone,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_message_count(phone):
    conn = get_connection()
    count = conn.execute(
        "SELECT COUNT(*) FROM message_log WHERE phone = ?", (phone,)
    ).fetchone()[0]
    conn.close()
    return count


# ── Live site stats (for landing page) ───────────────────────────────────────

def get_live_stats():
    conn = get_connection()
    c    = conn.cursor()
    stats = {
        "products": c.execute("SELECT COUNT(*) FROM products WHERE status='approved'").fetchone()[0],
        "sellers":  c.execute("SELECT COUNT(*) FROM sellers  WHERE status='approved'").fetchone()[0],
        "orders":   c.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
        "services": c.execute("SELECT COUNT(*) FROM services WHERE status='approved'").fetchone()[0],
    }
    conn.close()
    return stats


# ── Featured products (admin picks) ──────────────────────────────────────────

def set_product_featured(product_id, featured: bool):
    conn = get_connection()
    conn.execute(
        "UPDATE products SET featured = ? WHERE id = ?",
        (1 if featured else 0, product_id)
    )
    conn.commit()
    conn.close()


def get_featured_admin_picks(limit=4):
    conn = get_connection()
    rows = conn.execute("""
        SELECT p.id, p.name, p.category, p.price, p.stock_qty,
               p.image_path, p.product_type, p.stock_unit,
               ROUND(COALESCE(AVG(r.rating), 0)::numeric, 1) AS avg_rating,
               COUNT(r.id) AS review_count
        FROM products p
        LEFT JOIN product_reviews r ON r.product_id = p.id
        WHERE p.status = 'approved' AND p.featured = 1
          AND (p.stock_qty > 0 OR p.product_type = 'digital')
        GROUP BY p.id
        ORDER BY p.created_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
