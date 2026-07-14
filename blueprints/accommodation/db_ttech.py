import os

from pg_compat import get_connection as _pg_get_connection

SCHEMA = "ttech"


def get_db():
    """Matches T-Tech-Connect1's original get_db() call signature (used as
    `with get_db() as conn:` throughout routes.py/sockets.py). _CompatConnection
    doesn't implement the context-manager protocol itself in pg_compat, so we
    wrap it here rather than touching the shared shim."""
    return _ConnCtx(_pg_get_connection(search_path=f"{SCHEMA},public"))


class _ConnCtx:
    """Thin context-manager wrapper so ported code's `with get_db() as conn:`
    keeps working unchanged. Commits on clean exit, always closes."""

    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._conn.commit()
        self._conn.close()
        return False


def init_db():
    conn = _pg_get_connection(search_path=f"{SCHEMA},public")
    cursor = conn.cursor()

    cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id                 SERIAL PRIMARY KEY,
            full_name          TEXT NOT NULL,
            email              TEXT UNIQUE NOT NULL,
            password_hash      TEXT NOT NULL,
            role               TEXT DEFAULT 'student',
            phone              TEXT,
            is_active          INTEGER DEFAULT 1,
            created_at         TEXT DEFAULT CURRENT_TIMESTAMP,
            last_login         TEXT,
            last_seen          TEXT,
            is_verified        INTEGER DEFAULT 0,
            is_email_verified  INTEGER DEFAULT 1,
            email_verify_token TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS login_attempts (
            id           SERIAL PRIMARY KEY,
            email        TEXT NOT NULL,
            ip_address   TEXT,
            success      INTEGER DEFAULT 0,
            attempted_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS properties (
            id               SERIAL PRIMARY KEY,
            landlord_id      INTEGER NOT NULL REFERENCES users(id),
            title            TEXT NOT NULL,
            property_type    TEXT DEFAULT 'apartment',
            description      TEXT,
            status           TEXT DEFAULT 'available',
            is_shared        INTEGER DEFAULT 0,
            total_rooms      INTEGER DEFAULT 1,
            available_rooms  INTEGER DEFAULT 1,
            bathrooms        INTEGER DEFAULT 1,
            price_per_month  DOUBLE PRECISION NOT NULL,
            currency         TEXT DEFAULT 'USD',
            address          TEXT,
            city             TEXT,
            country          TEXT DEFAULT 'Zimbabwe',
            latitude         DOUBLE PRECISION,
            longitude        DOUBLE PRECISION,
            services         TEXT DEFAULT '[]',
            contact_phone    TEXT,
            contact_email    TEXT,
            is_active        INTEGER DEFAULT 1,
            created_at       TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at       TEXT DEFAULT CURRENT_TIMESTAMP,
            nearby_landmark  TEXT DEFAULT '',
            student_friendly INTEGER DEFAULT 0,
            suburb           TEXT DEFAULT '',
            available_from   DATE
        )
    """)
    for col, definition in [
        ("nearby_landmark",  "TEXT DEFAULT ''"),
        ("student_friendly", "INTEGER DEFAULT 0"),
        ("suburb",           "TEXT DEFAULT ''"),
        ("available_from",   "DATE"),
    ]:
        cursor.execute(f"ALTER TABLE properties ADD COLUMN IF NOT EXISTS {col} {definition}")

    for col, definition in [
        ("phone",     "TEXT"),
        ("last_seen", "TEXT"),
        ("is_verified", "INTEGER DEFAULT 0"),
        ("is_email_verified", "INTEGER DEFAULT 1"),
        ("email_verify_token", "TEXT"),
        ("pass_expiry", "TEXT"),
        ("deleted_at", "TEXT"),
        ("phone_verified", "INTEGER DEFAULT 0"),
        ("is_official_account", "INTEGER DEFAULT 0"),
    ]:
        cursor.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {definition}")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS property_images (
            id          SERIAL PRIMARY KEY,
            property_id INTEGER NOT NULL REFERENCES properties(id),
            filename    TEXT NOT NULL,
            is_primary  INTEGER DEFAULT 0,
            uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id          SERIAL PRIMARY KEY,
            subject     TEXT DEFAULT 'Property Inquiry',
            property_id INTEGER REFERENCES properties(id),
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at  TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversation_members (
            conversation_id INTEGER NOT NULL REFERENCES conversations(id),
            user_id         INTEGER NOT NULL REFERENCES users(id),
            last_read_at    TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (conversation_id, user_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id              SERIAL PRIMARY KEY,
            conversation_id INTEGER NOT NULL REFERENCES conversations(id),
            sender_id       INTEGER NOT NULL REFERENCES users(id),
            content         TEXT NOT NULL,
            is_deleted      INTEGER DEFAULT 0,
            sent_at         TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id          SERIAL PRIMARY KEY,
            student_id  INTEGER NOT NULL REFERENCES users(id),
            property_id INTEGER NOT NULL REFERENCES properties(id),
            amount      DOUBLE PRECISION NOT NULL,
            currency    TEXT DEFAULT 'USD',
            reference   TEXT,
            paid_at     TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(student_id, property_id)
        )
    """)
    # Self-reported payments (cash/bank/manual reference) aren't checked
    # against any gateway, so they're recorded unverified until an admin
    # confirms them; gateway-confirmed EcoCash payments insert verified=1
    # directly. Legacy rows predate this column entirely (their pass was
    # already granted when they were inserted), so backfill only touches
    # rows that have never had a value set — new inserts always pass one
    # explicitly, so this UPDATE is a no-op after the first deploy.
    cursor.execute("ALTER TABLE payments ADD COLUMN IF NOT EXISTS verified INTEGER")
    cursor.execute("UPDATE payments SET verified=1 WHERE verified IS NULL")
    # Payments used to gate access per-property (one paid unlock per property
    # forever), so a UNIQUE(student_id, property_id) constraint prevented
    # double-charging. Access is now a time-bound pass covering every
    # property, so a tenant can legitimately buy/renew a pass more than once
    # via the same property page — drop the constraint so those renewals get
    # logged instead of silently no-op'ing.
    cursor.execute("""
        ALTER TABLE payments DROP CONSTRAINT IF EXISTS payments_student_id_property_id_key
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS payment_requests (
            id          TEXT PRIMARY KEY,
            student_id  INTEGER NOT NULL REFERENCES users(id),
            property_id INTEGER NOT NULL REFERENCES properties(id),
            amount      DOUBLE PRECISION NOT NULL,
            currency    TEXT DEFAULT 'USD',
            phone       TEXT NOT NULL,
            poll_url    TEXT,
            status      TEXT DEFAULT 'pending',
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    # Flat "Connect Fee" access pass: one payment unlocks contact details for
    # every landlord for connect_fee_duration_days, replacing the old
    # per-property percentage-of-rent commission.
    cursor.execute("""
        INSERT INTO settings (key, value) VALUES ('connect_fee_price', '10')
        ON CONFLICT (key) DO NOTHING
    """)
    cursor.execute("""
        INSERT INTO settings (key, value) VALUES ('connect_fee_duration_days', '14')
        ON CONFLICT (key) DO NOTHING
    """)
    # Deleted users are soft-deactivated first (is_active=0, deleted_at set); a
    # cron job (or the admin users page as a lazy fallback) hard-deletes them
    # once this many days have passed. 0 disables auto-purge entirely.
    cursor.execute("""
        INSERT INTO settings (key, value) VALUES ('user_purge_after_days', '30')
        ON CONFLICT (key) DO NOTHING
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id          SERIAL PRIMARY KEY,
            property_id INTEGER NOT NULL REFERENCES properties(id),
            reviewer_id INTEGER NOT NULL REFERENCES users(id),
            rating      INTEGER NOT NULL,
            comment     TEXT DEFAULT '',
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(property_id, reviewer_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS phone_otps (
            id         SERIAL PRIMARY KEY,
            user_id    INTEGER NOT NULL REFERENCES users(id),
            code       TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            attempts   INTEGER DEFAULT 0,
            used       INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS password_resets (
            id         SERIAL PRIMARY KEY,
            user_id    INTEGER NOT NULL REFERENCES users(id),
            token      TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            used       INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id               SERIAL PRIMARY KEY,
            property_id      INTEGER NOT NULL REFERENCES properties(id),
            tenant_id        INTEGER NOT NULL REFERENCES users(id),
            landlord_id      INTEGER NOT NULL REFERENCES users(id),
            message          TEXT DEFAULT '',
            status           TEXT DEFAULT 'pending',
            proposed_move_in DATE,
            landlord_notes   TEXT DEFAULT '',
            created_at       TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at       TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(property_id, tenant_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tenancies (
            id           SERIAL PRIMARY KEY,
            property_id  INTEGER NOT NULL REFERENCES properties(id),
            tenant_id    INTEGER NOT NULL REFERENCES users(id),
            landlord_id  INTEGER NOT NULL REFERENCES users(id),
            booking_id   INTEGER REFERENCES bookings(id),
            agreed_rent  DOUBLE PRECISION NOT NULL,
            currency     TEXT DEFAULT 'USD',
            unit_number  TEXT DEFAULT '',
            lease_start  DATE NOT NULL,
            lease_end    DATE,
            status       TEXT DEFAULT 'active',
            notes        TEXT DEFAULT '',
            created_at   TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at   TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id         SERIAL PRIMARY KEY,
            user_id    INTEGER NOT NULL REFERENCES users(id),
            type       TEXT NOT NULL,
            title      TEXT NOT NULL,
            body       TEXT DEFAULT '',
            link       TEXT DEFAULT '',
            is_read    INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS maintenance_requests (
            id             SERIAL PRIMARY KEY,
            property_id    INTEGER NOT NULL REFERENCES properties(id),
            tenant_id      INTEGER NOT NULL REFERENCES users(id),
            title          TEXT NOT NULL,
            description    TEXT DEFAULT '',
            priority       TEXT DEFAULT 'normal',
            status         TEXT DEFAULT 'open',
            landlord_notes TEXT DEFAULT '',
            created_at     TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at     TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS saved_properties (
            tenant_id   INTEGER NOT NULL REFERENCES users(id),
            property_id INTEGER NOT NULL REFERENCES properties(id),
            saved_at    TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (tenant_id, property_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS enquiries (
            id          SERIAL PRIMARY KEY,
            property_id INTEGER NOT NULL REFERENCES properties(id),
            name        TEXT NOT NULL,
            email       TEXT NOT NULL,
            phone       TEXT DEFAULT '',
            message     TEXT DEFAULT '',
            source      TEXT DEFAULT 'chatbot',
            created_at  TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS viewings (
            id             SERIAL PRIMARY KEY,
            property_id    INTEGER NOT NULL REFERENCES properties(id),
            name           TEXT NOT NULL,
            email          TEXT NOT NULL,
            phone          TEXT DEFAULT '',
            preferred_date DATE,
            preferred_time TEXT DEFAULT '',
            notes          TEXT DEFAULT '',
            status         TEXT DEFAULT 'pending',
            source         TEXT DEFAULT 'chatbot',
            created_at     TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS appointments (
            id               SERIAL PRIMARY KEY,
            property_id      INTEGER NOT NULL REFERENCES properties(id),
            name             TEXT NOT NULL,
            email            TEXT NOT NULL,
            phone            TEXT DEFAULT '',
            appointment_date DATE NOT NULL,
            appointment_time TEXT DEFAULT '',
            type             TEXT DEFAULT 'viewing',
            notes            TEXT DEFAULT '',
            status           TEXT DEFAULT 'pending',
            source           TEXT DEFAULT 'chatbot',
            created_at       TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()

    # ── Seed default accounts + one sample property (idempotent) ──────────────
    from werkzeug.security import generate_password_hash
    import json as _json

    seeds = [
        (os.environ.get("ADMIN_NAME", "Admin User"),
         os.environ.get("ADMIN_EMAIL", "admin@ttech.ac.zw"),
         os.environ.get("ADMIN_PASSWORD", "Admin@1234"), "admin"),
        ("John Student",   "student@ttech.ac.zw",  "Student@1234",  "student"),
        ("Grace Landlord", "landlord@ttech.ac.zw", "Landlord@1234", "landlord"),
    ]
    for name, email, pwd, role in seeds:
        if not cursor.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
            cursor.execute(
                "INSERT INTO users (full_name, email, password_hash, role, is_email_verified) VALUES (?,?,?,?,1)",
                (name, email, generate_password_hash(pwd), role)
            )

    official_email = os.environ.get("ADMIN_EMAIL", "admin@ttech.ac.zw")
    cursor.execute(
        "UPDATE users SET is_official_account = 1 WHERE email = ? AND is_official_account IS DISTINCT FROM 1",
        (official_email,)
    )

    landlord = cursor.execute("SELECT id FROM users WHERE email = 'landlord@ttech.ac.zw'").fetchone()
    if landlord:
        if not cursor.execute("SELECT id FROM properties WHERE landlord_id = ?", (landlord["id"],)).fetchone():
            cursor.execute("""
                INSERT INTO properties
                    (landlord_id,title,property_type,description,status,is_shared,
                     total_rooms,available_rooms,bathrooms,price_per_month,currency,
                     address,city,country,latitude,longitude,services,contact_phone,contact_email)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                landlord["id"], "Sunshine Student Lodge", "apartment",
                "A well-furnished, secure student accommodation close to T-Tech campus.",
                "available", 0, 12, 4, 4, 120.00, "USD",
                "45 Borrowdale Road, Harare", "Harare", "Zimbabwe",
                -17.7833, 31.0500,
                _json.dumps(["wifi", "water", "electricity", "security", "parking"]),
                "+263 77 123 4567", "landlord@ttech.ac.zw"
            ))

    conn.commit()
    conn.close()
    print("Database initialised (ttech schema)")
