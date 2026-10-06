from flask import Flask, jsonify, render_template, request
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine
from werkzeug.exceptions import HTTPException

db = SQLAlchemy()
login_manager = LoginManager()


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):
    # SQLite ignores foreign keys unless asked; we rely on them for integrity.
    if dbapi_conn.__class__.__module__.startswith("sqlite3"):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


def _add_missing_columns():
    """Tiny forward-only migration: add new nullable columns to existing tables.

    create_all() creates new tables but never alters existing ones, so databases
    created by an earlier version would otherwise miss newly added columns.
    """
    from sqlalchemy import inspect, text
    insp = inspect(db.engine)
    with db.engine.begin() as conn:
        for table in db.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing or not col.nullable:
                    continue
                coltype = col.type.compile(db.engine.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {coltype}'))


def create_app(config_object="config.Config"):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)

    db.init_app(app)
    login_manager.init_app(app)

    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    @login_manager.unauthorized_handler
    def unauthorized():
        return jsonify(error="Authentication required"), 401

    from .utils import ApiError

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        db.session.rollback()
        payload = {"error": err.message}
        if err.fields:
            payload["fields"] = err.fields
        return jsonify(payload), err.status

    @app.errorhandler(HTTPException)
    def handle_http(err):
        if request.path.startswith("/api/"):
            return jsonify(error=err.description), err.code
        return err

    @app.before_request
    def csrf_guard():
        # Browsers will not attach custom headers to cross-site form posts, so
        # requiring one on every state-changing API call blocks CSRF.
        # The chatbot integration is server-to-server and authenticates with a
        # bearer key that browsers never send on their own, so CSRF can't apply.
        if request.path.startswith("/api/integration/"):
            return None
        if request.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get("X-Requested-With") != "SchoolMS":
                return jsonify(error="Missing CSRF header"), 403

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        return resp

    from .api import register_blueprints
    register_blueprints(app)

    @app.get("/")
    def index():
        return render_template("index.html", school_name=app.config["SCHOOL_NAME"])

    with app.app_context():
        db.create_all()
        _add_missing_columns()
        from .services.ledger import ensure_chart
        ensure_chart()

    from .seed import register_cli
    register_cli(app)

    return app
