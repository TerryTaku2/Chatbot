"""Serve the School Financial Management System at /school inside the chatbot.

The school system is a self-contained Flask app ("School Financial Management
System/"). It runs in this same process, mounted at /school with
werkzeug's DispatcherMiddleware (see app.py), so it ships with every chatbot
deploy and shares the chatbot's domain and database server.

Isolation from the chatbot:
* Its package is called `app`, which clashes with the chatbot's app.py, so it
  is loaded under the name `school_app` (and its config as `school_config`).
* Its tables live in their own Postgres schema, `school`, the same way the
  accommodation blueprint uses `ttech`, because names such as "user",
  "payment" and "setting" would otherwise collide.
* It uses its own session/remember cookies scoped to /school, so logging in
  here never disturbs the chatbot's admin session and vice versa.
"""
import hashlib
import hmac
import importlib.util
import os
import sys

SCHOOL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "School Financial Management System")
MOUNT_PATH = "/school"
SCHEMA = "school"

# The running school Flask app once create_school_app() has built it; the
# chatbot's school_client calls it in-process through this, so the link
# never depends on BASE_URL, a domain name or ngrok.
mounted_app = None


def derive_key(secret, purpose):
    """Stable per-purpose key from FLASK_SECRET_KEY, so no extra secrets are needed."""
    return hmac.new(secret.encode(), f"school:{purpose}".encode(), hashlib.sha256).hexdigest()


def _load(name, path):
    """Import a module or package from a file path under a chosen module name."""
    if os.path.isdir(path):
        spec = importlib.util.spec_from_file_location(
            name, os.path.join(path, "__init__.py"), submodule_search_locations=[path])
    else:
        spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _sqlalchemy_url(url):
    # Some hosts still hand out the pre-2.0 "postgres://" scheme SQLAlchemy rejects.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


def _ensure_schema(database_url):
    import psycopg2
    conn = psycopg2.connect(database_url)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    finally:
        conn.close()


def _ensure_admin(app, school_app, username, password):
    """Create the first administrator from env vars when the school has none."""
    from school_app.models import User
    with app.app_context():
        if User.query.filter_by(role="admin", active=True).first():
            return
        if not password:
            print("[SCHOOL] No administrator yet — set SCHOOL_ADMIN_PASSWORD "
                  "(and optionally SCHOOL_ADMIN_USERNAME) to create one on next start.")
            return
        user = User.query.filter_by(username=username).first()
        if user is None:
            user = User(username=username, full_name="School Administrator", role="admin")
            school_app.db.session.add(user)
        user.role, user.active = "admin", True
        user.set_password(password)
        school_app.db.session.commit()
        print(f"[SCHOOL] Administrator '{username}' created.")


def create_school_app(database_url, secret_key, base_url, notify_callback=None):
    """Build the school Flask app configured to live under MOUNT_PATH.

    notify_callback(event_dict) receives school events (e.g. payment_recorded)
    directly, instead of over HTTP.
    """
    global mounted_app
    is_postgres = database_url.startswith(("postgres://", "postgresql://"))
    if is_postgres:
        _ensure_schema(database_url)

    school_config = _load("school_config", os.path.join(SCHOOL_DIR, "config.py"))
    school_app = _load("school_app", os.path.join(SCHOOL_DIR, "app"))

    class MountedConfig(school_config.Config):
        SECRET_KEY = derive_key(secret_key, "session")
        SQLALCHEMY_DATABASE_URI = _sqlalchemy_url(database_url)
        SQLALCHEMY_ENGINE_OPTIONS = {
            # Neon and similar hosts drop idle connections; check before use.
            "pool_pre_ping": True,
            "pool_recycle": 280,
            **({"connect_args": {"options": f"-c search_path={SCHEMA}"}} if is_postgres else {}),
        }
        SESSION_COOKIE_NAME = "school_session"
        SESSION_COOKIE_PATH = MOUNT_PATH
        SESSION_COOKIE_SECURE = base_url.startswith("https://")
        REMEMBER_COOKIE_NAME = "school_remember_token"
        REMEMBER_COOKIE_PATH = MOUNT_PATH
        REMEMBER_COOKIE_SECURE = base_url.startswith("https://")
        CHATBOT_API_KEY = os.getenv("SCHOOL_API_KEY") or derive_key(secret_key, "api")
        CHATBOT_WEBHOOK_URL = ""
        CHATBOT_NOTIFY_CALLBACK = staticmethod(notify_callback) if notify_callback else None

    app = school_app.create_app(MountedConfig)
    _ensure_admin(app, school_app,
                  (os.getenv("SCHOOL_ADMIN_USERNAME") or "admin").strip().lower(),
                  os.getenv("SCHOOL_ADMIN_PASSWORD", ""))
    mounted_app = app
    return app
