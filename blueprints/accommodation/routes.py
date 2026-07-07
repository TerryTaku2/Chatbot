import os
import re
import json
import uuid
import hmac
import hashlib
import secrets
from datetime import datetime, timedelta
from functools import wraps

import requests as http_requests
from flask import (
    render_template, request, redirect, url_for, session, jsonify,
    flash, make_response, abort, current_app,
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from . import accommodation_bp, socketio, limiter
from .db_ttech import get_db

# ── Config ──────────────────────────────────────────────────────────────────

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
MAIL_FROM_EMAIL  = os.environ.get("MAIL_USERNAME", "terrencemuromba6@gmail.com")
MAIL_FROM_NAME   = "T-Tech Connect"

# Same secret the chatbot side uses to call *this* blueprint's /api/* routes
# (see app.py's TTECH_API_KEY) — one shared value now that it's one process.
CHATBOT_API_KEY      = os.environ.get("TTECH_API_KEY", "")
CHATBOT_BASE_URL     = os.environ.get("CHATBOT_BASE_URL", "").rstrip("/")
TTECH_WEBHOOK_SECRET = os.environ.get("TTECH_WEBHOOK_SECRET", "")

PAYNOW_INTEGRATION_ID  = os.environ.get("PAYNOW_INTEGRATION_ID", "")
PAYNOW_INTEGRATION_KEY = os.environ.get("PAYNOW_INTEGRATION_KEY", "")
PAYNOW_RESULT_URL      = os.environ.get("PAYNOW_RESULT_URL", "")
ECOCASH_MERCHANT       = "0774128219"


def get_paynow():
    if not PAYNOW_INTEGRATION_ID or not PAYNOW_INTEGRATION_KEY:
        return None
    try:
        from paynow import Paynow
        return Paynow(PAYNOW_INTEGRATION_ID, PAYNOW_INTEGRATION_KEY,
                      PAYNOW_RESULT_URL, "")
    except ImportError:
        return None


ALLOWED_EXT   = {"jpg", "jpeg", "png", "webp"}
DATA_DIR      = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "static"))
UPLOAD_FOLDER = os.path.join(DATA_DIR, "uploads", "properties")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ── Decorators ────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("accommodation.login"))
        return f(*args, **kwargs)
    return decorated


def landlord_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("accommodation.login"))
        if session.get("user_role") not in ("landlord", "admin"):
            flash("Access denied. Landlord account required.", "error")
            return redirect(url_for("accommodation.dashboard"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("accommodation.login"))
        if session.get("user_role") != "admin":
            flash("Admin access required.", "error")
            return redirect(url_for("accommodation.dashboard"))
        return f(*args, **kwargs)
    return decorated


def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not CHATBOT_API_KEY:
            return jsonify({"error": "API key not configured on server"}), 503
        key = request.headers.get("X-API-Key", "")
        if not key or not secrets.compare_digest(key, CHATBOT_API_KEY):
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


# ── Webhook delivery (to the chatbot side of this same process) ───────────────

def _send_webhook(event_type, payload):
    if not CHATBOT_BASE_URL or not TTECH_WEBHOOK_SECRET:
        current_app.logger.warning(f"Webhook not sent ({event_type}): CHATBOT_BASE_URL or TTECH_WEBHOOK_SECRET not set")
        return
    body = json.dumps({
        "event": event_type,
        "data": payload,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }, default=str)
    sig = hmac.new(TTECH_WEBHOOK_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
    try:
        http_requests.post(
            f"{CHATBOT_BASE_URL}/webhooks/property",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Signature": f"sha256={sig}",
            },
            timeout=5,
        )
    except Exception as e:
        current_app.logger.error(f"Webhook delivery failed ({event_type}): {e}")


# ── Session integrity: re-validate on every accommodation request ────────────

@accommodation_bp.before_request
def _refresh_session():
    uid = session.get("user_id")
    if not uid:
        return
    with get_db() as conn:
        user = conn.execute(
            "SELECT role, is_active FROM users WHERE id=?", (uid,)
        ).fetchone()
    if not user or not user["is_active"]:
        session.clear()
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            abort(401)
        flash("Your account has been deactivated. Please contact support.", "error")
        return redirect(url_for("accommodation.login"))
    if user["role"] != session.get("user_role"):
        session["user_role"] = user["role"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_valid_email(email):
    return re.match(r"^[\w\.-]+@[\w\.-]+\.\w+$", email)


def is_valid_phone(phone):
    return re.match(r"^\+?[\d\s\-]{7,15}$", phone)


def log_attempt(email, ip, success):
    with get_db() as conn:
        conn.execute("INSERT INTO login_attempts (email, ip_address, success) VALUES (?,?,?)",
                     (email, ip, 1 if success else 0))
        conn.commit()


def get_failed_attempts(email, ip):
    with get_db() as conn:
        row = conn.execute(
            """SELECT COUNT(*) as cnt FROM login_attempts
               WHERE (email=? OR ip_address=?) AND success=0
               AND attempted_at::timestamp > (NOW() AT TIME ZONE 'UTC' - INTERVAL '15 minutes')""",
            (email, ip)
        ).fetchone()
        return row["cnt"] if row else 0


def role_redirect(role):
    return {
        "landlord": url_for("accommodation.landlord_dashboard"),
        "admin":    url_for("accommodation.admin_dashboard"),
        "student":  url_for("accommodation.dashboard"),
    }.get(role, url_for("accommodation.dashboard"))


def get_unread_count(user_id):
    with get_db() as conn:
        row = conn.execute("""
            SELECT COUNT(*) as cnt FROM messages m
            JOIN conversation_members cm
                ON m.conversation_id = cm.conversation_id AND cm.user_id = ?
            WHERE m.sender_id != ?
              AND (m.sent_at > cm.last_read_at OR cm.last_read_at IS NULL)
              AND m.is_deleted = 0
        """, (user_id, user_id)).fetchone()
        return row["cnt"] if row else 0


def has_paid(student_id, property_id):
    with get_db() as conn:
        return bool(conn.execute(
            "SELECT 1 FROM payments WHERE student_id=? AND property_id=?",
            (student_id, property_id)
        ).fetchone())


def get_commission_rate():
    with get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='commission_rate'").fetchone()
    return float(row["value"]) / 100 if row else 0.05


def _notify(user_id, ntype, title, body="", link=""):
    """Insert a notification row and push it to the user via SocketIO if online."""
    with get_db() as conn:
        conn.execute(
            "INSERT INTO notifications (user_id, type, title, body, link) VALUES (?,?,?,?,?)",
            (user_id, ntype, title, body, link)
        )
        conn.commit()
    socketio.emit("notification", {"type": ntype, "title": title, "body": body, "link": link},
                  room=f"user_{user_id}")


def _get_own_property(pid):
    with get_db() as conn:
        if session.get("user_role") == "admin":
            return conn.execute(
                "SELECT * FROM properties WHERE id=? AND is_active=1", (pid,)
            ).fetchone()
        return conn.execute(
            "SELECT * FROM properties WHERE id=? AND landlord_id=? AND is_active=1",
            (pid, session["user_id"])
        ).fetchone()


def _get_images(property_id):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM property_images WHERE property_id=? ORDER BY is_primary DESC, uploaded_at ASC",
            (property_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def _save_images(property_id, files):
    """Persist uploaded image files and record them in DB. First image becomes cover if none set."""
    with get_db() as conn:
        has_cover = conn.execute(
            "SELECT 1 FROM property_images WHERE property_id=? AND is_primary=1", (property_id,)
        ).fetchone()
        count = conn.execute(
            "SELECT COUNT(*) FROM property_images WHERE property_id=?", (property_id,)
        ).fetchone()[0]

        first = True
        for f in files:
            if not f or not f.filename:
                continue
            ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
            if ext not in ALLOWED_EXT:
                continue
            if count >= 10:
                break
            filename = f"{uuid.uuid4().hex}.{ext}"
            try:
                f.save(os.path.join(UPLOAD_FOLDER, filename))
                is_primary = 1 if (first and not has_cover) else 0
                conn.execute(
                    "INSERT INTO property_images (property_id, filename, is_primary) VALUES (?,?,?)",
                    (property_id, filename, is_primary)
                )
                if first and not has_cover:
                    has_cover = True
                first = False
                count += 1
            except Exception as e:
                current_app.logger.error(f"Image save error: {e}")
        conn.commit()


def _save_property(pid):
    f = request.form
    errors = {}
    title         = f.get("title", "").strip()
    prop_type     = f.get("property_type", "apartment")
    description   = f.get("description", "").strip()
    status        = f.get("status", "available")
    is_shared     = 1 if f.get("is_shared") else 0
    total_rooms   = f.get("total_rooms", "1")
    avail_rooms   = f.get("available_rooms", "1")
    bathrooms     = f.get("bathrooms", "1")
    price         = f.get("price_per_month", "").strip()
    currency      = f.get("currency", "USD")
    address       = f.get("address", "").strip()
    city          = f.get("city", "").strip()
    country       = f.get("country", "Zimbabwe").strip()
    lat           = f.get("latitude", "").strip() or None
    lng           = f.get("longitude", "").strip() or None
    services         = json.dumps(f.getlist("services"))
    contact_phone    = f.get("contact_phone", "").strip()
    contact_email    = f.get("contact_email", "").strip()
    nearby_landmark  = f.get("nearby_landmark", "").strip()
    student_friendly = 1 if f.get("student_friendly") else 0

    try:    total_rooms = int(total_rooms)
    except: total_rooms = 1
    try:    avail_rooms = int(avail_rooms)
    except: avail_rooms = 0
    try:    bathrooms   = int(bathrooms)
    except: bathrooms   = 1

    if not title:   errors["title"]   = "Property title is required."
    if not price:   errors["price"]   = "Monthly price is required."
    else:
        try:    price = float(price)
        except: errors["price"] = "Price must be a valid number."
    if not address: errors["address"] = "Address is required."
    if avail_rooms > total_rooms:
        errors["available_rooms"] = "Available rooms cannot exceed total rooms."

    if errors:
        d = dict(f); d.update({"services": f.getlist("services"), "id": pid})
        flash("Please fix the errors below.", "error")
        return render_template("accommodation/property_form.html", prop=d, errors=errors,
                               user_name=session.get("user_name"),
                               user_role=session.get("user_role"))

    data = (
        title, prop_type, description, status, is_shared,
        total_rooms, avail_rooms, bathrooms,
        price, currency, address, city, country,
        float(lat) if lat else None, float(lng) if lng else None,
        services, contact_phone, contact_email, nearby_landmark, student_friendly
    )

    with get_db() as conn:
        if pid is None:
            cur = conn.execute("""
                INSERT INTO properties
                    (landlord_id,title,property_type,description,status,is_shared,
                     total_rooms,available_rooms,bathrooms,price_per_month,currency,
                     address,city,country,latitude,longitude,services,contact_phone,contact_email,
                     nearby_landmark,student_friendly)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                RETURNING id
            """, (session["user_id"], *data))
            property_id = cur.fetchone()["id"]
            flash("Property listed successfully!", "success")
        else:
            if session.get("user_role") == "admin":
                conn.execute("""
                    UPDATE properties SET
                        title=?,property_type=?,description=?,status=?,is_shared=?,
                        total_rooms=?,available_rooms=?,bathrooms=?,price_per_month=?,currency=?,
                        address=?,city=?,country=?,latitude=?,longitude=?,
                        services=?,contact_phone=?,contact_email=?,nearby_landmark=?,student_friendly=?,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                """, (*data, pid))
            else:
                conn.execute("""
                    UPDATE properties SET
                        title=?,property_type=?,description=?,status=?,is_shared=?,
                        total_rooms=?,available_rooms=?,bathrooms=?,price_per_month=?,currency=?,
                        address=?,city=?,country=?,latitude=?,longitude=?,
                        services=?,contact_phone=?,contact_email=?,nearby_landmark=?,student_friendly=?,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE id=? AND landlord_id=?
                """, (*data, pid, session["user_id"]))
            property_id = pid
            flash("Property updated successfully!", "success")
        conn.commit()

    uploaded = request.files.getlist("images")
    if uploaded:
        _save_images(property_id, uploaded)

    if session.get("user_role") == "admin":
        return redirect(url_for("accommodation.admin_properties"))
    return redirect(url_for("accommodation.landlord_dashboard"))


# ── Auth routes ───────────────────────────────────────────────────────────────

@accommodation_bp.route("/")
def index():
    if "user_id" in session:
        return redirect(role_redirect(session.get("user_role")))
    return redirect(url_for("accommodation.login"))


@accommodation_bp.route("/register", methods=["POST"])
@limiter.limit("5 per minute")
def register():
    if "user_id" in session:
        return jsonify({"success": False, "error": "Already logged in"}), 400

    data      = request.get_json() if request.is_json else request.form
    full_name = (data.get("full_name") or "").strip()
    email     = (data.get("email") or "").strip().lower()
    phone     = (data.get("phone") or "").strip()
    password  = data.get("password") or ""
    role      = (data.get("role") or "").strip()

    def err(msg, code=400):
        return jsonify({"success": False, "error": msg}), code

    if not full_name:
        return err("Full name is required.")
    if not email or not is_valid_email(email):
        return err("A valid email address is required.")
    if phone and not is_valid_phone(phone):
        return err("Please enter a valid phone number.")
    if role not in ("student", "landlord"):
        return err("Please select Tenant or Landlord.")
    if len(password) < 8:
        return err("Password must be at least 8 characters.")

    with get_db() as conn:
        if conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
            return err("An account with this email already exists.")
        if phone and conn.execute("SELECT id FROM users WHERE phone=?", (phone,)).fetchone():
            return err("An account with this phone number already exists.")
        verify_token = secrets.token_urlsafe(32)
        conn.execute(
            "INSERT INTO users (full_name, email, password_hash, role, phone, is_email_verified, email_verify_token) VALUES (?,?,?,?,?,0,?)",
            (full_name, email, generate_password_hash(password), role, phone or None, verify_token)
        )
        conn.commit()

    verify_url = url_for("accommodation.verify_email", token=verify_token, _external=True)
    _send_verification_email(email, full_name, role, verify_url)

    if request.is_json:
        return jsonify({"success": True, "redirect": "/accommodation/check-email?email=" + email, "role": role})
    return redirect("/accommodation/check-email?email=" + email)


@accommodation_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    if "user_id" in session:
        return redirect(role_redirect(session.get("user_role")))
    error = None
    if request.method == "POST":
        if request.is_json:
            data = request.get_json()
            identifier = (data.get("email") or data.get("identifier") or "").strip()
            password   = data.get("password", "")
            remember   = data.get("remember", False)
        else:
            identifier = request.form.get("email", "").strip()
            password   = request.form.get("password", "")
            remember   = bool(request.form.get("remember"))

        identifier_lower = identifier.lower()
        ip     = get_remote_address_local()
        failed = get_failed_attempts(identifier_lower, ip)

        login_by_phone = "@" not in identifier and is_valid_phone(identifier)
        if   failed >= 5:                    msg = "Too many failed attempts. Wait 15 minutes."
        elif not identifier or not password: msg = "Email/phone and password are required."
        elif not login_by_phone and not is_valid_email(identifier_lower): msg = "Please enter a valid email address or phone number."
        else:                                msg = None

        if msg:
            if request.is_json: return jsonify({"success": False, "error": msg}), 429 if failed >= 5 else 400
            error = msg
        else:
            with get_db() as conn:
                if login_by_phone:
                    user = conn.execute(
                        "SELECT * FROM users WHERE phone=? AND is_active=1", (identifier,)
                    ).fetchone()
                else:
                    user = conn.execute(
                        "SELECT * FROM users WHERE email=? AND is_active=1", (identifier_lower,)
                    ).fetchone()

            if user and user["password_hash"] and check_password_hash(user["password_hash"], password):
                log_attempt(identifier_lower, ip, True)
                if not user["is_email_verified"]:
                    msg = "Please verify your email address before logging in."
                    if request.is_json:
                        return jsonify({"success": False, "error": msg, "unverified": True, "email": user["email"]}), 403
                    return redirect("/accommodation/check-email?email=" + user["email"])
                session.clear()
                session["user_id"]    = user["id"]
                session["user_name"]  = user["full_name"]
                session["user_role"]  = user["role"]
                session["user_email"] = user["email"]
                if remember: session.permanent = True
                with get_db() as conn:
                    conn.execute("UPDATE users SET last_login=CURRENT_TIMESTAMP, last_seen=CURRENT_TIMESTAMP WHERE id=?", (user["id"],))
                    conn.commit()
                dest = role_redirect(user["role"])
                if request.is_json:
                    return jsonify({"success": True, "redirect": dest, "role": user["role"]})
                return redirect(dest)
            else:
                log_attempt(identifier_lower, ip, False)
                msg = "Invalid credentials. Please try again."
                if request.is_json: return jsonify({"success": False, "error": msg}), 401
                error = msg

    return render_template("accommodation/login.html", error=error)


def get_remote_address_local():
    """Same logic Flask-Limiter's get_remote_address uses, kept local so this
    module doesn't need a second import path for it."""
    return request.remote_addr or "127.0.0.1"


@accommodation_bp.route("/dashboard")
@login_required
def dashboard():
    if session.get("user_role") == "landlord":
        return redirect(url_for("accommodation.landlord_dashboard"))
    if session.get("user_role") == "admin":
        return redirect(url_for("accommodation.admin_dashboard"))

    q               = request.args.get("q", "").strip()
    prop_type       = request.args.get("type", "").strip()
    city            = request.args.get("city", "").strip()
    min_price       = request.args.get("min_price", "").strip()
    max_price       = request.args.get("max_price", "").strip()
    shared          = request.args.get("shared", "").strip()
    student_friendly= request.args.get("student_friendly", "").strip()
    available_only  = request.args.get("available_only", "").strip()

    filters = ["p.is_active=1"]
    params  = []
    if q:
        like = f"%{q}%"
        filters.append("(p.title LIKE ? OR p.nearby_landmark LIKE ? OR p.city LIKE ? OR p.description LIKE ?)")
        params += [like, like, like, like]
    if prop_type:
        filters.append("p.property_type=?");  params.append(prop_type)
    if city:
        filters.append("p.city=?");           params.append(city)
    if min_price:
        try:    filters.append("p.price_per_month>=?"); params.append(float(min_price))
        except ValueError: pass
    if max_price:
        try:    filters.append("p.price_per_month<=?"); params.append(float(max_price))
        except ValueError: pass
    if shared == "1":   filters.append("p.is_shared=1")
    elif shared == "0": filters.append("p.is_shared=0")
    if student_friendly == "1": filters.append("p.student_friendly=1")
    if available_only   == "1": filters.append("p.status='available'")

    where = " AND ".join(filters)
    with get_db() as conn:
        stats = conn.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN status='available' THEN 1 ELSE 0 END) as available,
                   SUM(CASE WHEN available_rooms > 0 THEN available_rooms ELSE 0 END) as rooms_available
            FROM properties WHERE is_active=1
        """).fetchone()

        props = conn.execute(f"""
            SELECT p.*, u.full_name as landlord_name, u.is_verified as landlord_verified,
                   COALESCE(AVG(r.rating), 0) as avg_rating, COUNT(r.id) as review_count
            FROM properties p JOIN users u ON p.landlord_id=u.id
            LEFT JOIN reviews r ON r.property_id=p.id
            WHERE {where}
            GROUP BY p.id, u.full_name, u.is_verified
            ORDER BY p.created_at DESC
        """, params).fetchall()

    prop_list = []
    for p in props:
        d = {**dict(p), "services": json.loads(p["services"] or "[]")}
        with get_db() as conn:
            cover = conn.execute(
                "SELECT filename FROM property_images WHERE property_id=? AND is_primary=1 LIMIT 1",
                (p["id"],)
            ).fetchone()
        d["cover_image"] = cover["filename"] if cover else None
        prop_list.append(d)

    unread = get_unread_count(session["user_id"])
    return render_template("accommodation/dashboard.html",
                           user_name=session.get("user_name"),
                           user_role=session.get("user_role"),
                           user_email=session.get("user_email"),
                           properties=prop_list,
                           stats=stats,
                           cities=_get_cities(),
                           q=q, prop_type=prop_type, city=city,
                           min_price=min_price, max_price=max_price,
                           shared=shared, student_friendly=student_friendly,
                           available_only=available_only,
                           unread_count=unread,
                           commission_rate=round(get_commission_rate() * 100, 2))


def _get_cities():
    with get_db() as conn:
        rows = conn.execute("""
            SELECT city, COUNT(*) as cnt
            FROM properties
            WHERE is_active=1 AND city IS NOT NULL AND city != ''
            GROUP BY city ORDER BY cnt DESC
        """).fetchall()
    return [dict(r) for r in rows]


@accommodation_bp.route("/browse")
def browse():
    q         = request.args.get("q", "").strip()
    prop_type = request.args.get("type", "").strip()
    max_price = request.args.get("max_price", "").strip()
    city      = request.args.get("city", "").strip()

    filters = ["p.is_active=1"]
    params  = []
    if q:
        like = f"%{q}%"
        filters.append("(p.title LIKE ? OR p.nearby_landmark LIKE ? OR p.city LIKE ? OR p.description LIKE ?)")
        params += [like, like, like, like]
    if prop_type:
        filters.append("p.property_type=?")
        params.append(prop_type)
    if max_price:
        try:
            filters.append("p.price_per_month<=?")
            params.append(float(max_price))
        except ValueError:
            pass
    if city:
        filters.append("p.city=?")
        params.append(city)

    where = " AND ".join(filters)
    with get_db() as conn:
        stats = conn.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN status='available' THEN 1 ELSE 0 END) as available,
                   SUM(CASE WHEN available_rooms > 0 THEN available_rooms ELSE 0 END) as rooms_available
            FROM properties WHERE is_active=1
        """).fetchone()

        props = conn.execute(f"""
            SELECT p.*, u.full_name as landlord_name, u.is_verified as landlord_verified,
                   COALESCE(AVG(r.rating), 0) as avg_rating, COUNT(r.id) as review_count
            FROM properties p JOIN users u ON p.landlord_id=u.id
            LEFT JOIN reviews r ON r.property_id=p.id
            WHERE {where}
            GROUP BY p.id, u.full_name, u.is_verified
            ORDER BY p.created_at DESC
        """, params).fetchall()

    prop_list = []
    for p in props:
        d = {**dict(p), "services": json.loads(p["services"] or "[]")}
        with get_db() as conn:
            cover = conn.execute(
                "SELECT filename FROM property_images WHERE property_id=? AND is_primary=1 LIMIT 1",
                (p["id"],)
            ).fetchone()
        d["cover_image"] = cover["filename"] if cover else None
        prop_list.append(d)

    return render_template("accommodation/browse.html",
                           properties=prop_list,
                           stats=stats,
                           cities=_get_cities(),
                           q=q, prop_type=prop_type, max_price=max_price, city=city)


@accommodation_bp.route("/for-tenants")
def for_tenants():
    return redirect(url_for("accommodation.browse"))


@accommodation_bp.route("/join")
def join():
    return redirect("/accommodation/login#register")


@accommodation_bp.route("/manifest.json")
def pwa_manifest():
    return jsonify({
        "name": "T-Tech Connect",
        "short_name": "T-Tech",
        "description": "Connecting Tenants with Landlords",
        "start_url": "/accommodation/",
        "scope": "/accommodation/",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#1d4ed8",
        "orientation": "portrait-primary",
        "categories": ["real estate", "housing"],
        "icons": [
            {"src": "/accommodation/static/images/icon-72.png",  "sizes": "72x72",   "type": "image/png"},
            {"src": "/accommodation/static/images/icon-96.png",  "sizes": "96x96",   "type": "image/png"},
            {"src": "/accommodation/static/images/icon-128.png", "sizes": "128x128", "type": "image/png"},
            {"src": "/accommodation/static/images/icon-144.png", "sizes": "144x144", "type": "image/png"},
            {"src": "/accommodation/static/images/icon-152.png", "sizes": "152x152", "type": "image/png"},
            {"src": "/accommodation/static/images/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": "/accommodation/static/images/icon-384.png", "sizes": "384x384", "type": "image/png"},
            {"src": "/accommodation/static/images/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ]
    })


@accommodation_bp.route("/sw.js")
def service_worker():
    resp = make_response(
        open(os.path.join(os.path.dirname(__file__), "static", "js", "sw.js")).read()
    )
    resp.headers["Content-Type"] = "application/javascript"
    resp.headers["Service-Worker-Allowed"] = "/accommodation/"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@accommodation_bp.route("/offline")
def offline_page():
    return render_template("accommodation/offline.html")


@accommodation_bp.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out successfully.", "info")
    return redirect(url_for("accommodation.login"))


@accommodation_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        data = request.get_json(silent=True) or request.form
        current_pw  = (data.get("current_password") or "").strip()
        new_pw      = (data.get("new_password") or "").strip()
        confirm_pw  = (data.get("confirm_password") or "").strip()

        def err(msg):
            if request.is_json:
                return jsonify({"success": False, "error": msg}), 400
            return render_template("accommodation/change_password.html",
                                   error=msg,
                                   user_name=session.get("user_name"),
                                   user_role=session.get("user_role"),
                                   user_email=session.get("user_email"),
                                   unread_count=get_unread_count(session["user_id"]))

        if not current_pw:
            return err("Current password is required.")
        if len(new_pw) < 8:
            return err("New password must be at least 8 characters.")
        if new_pw != confirm_pw:
            return err("New passwords do not match.")

        with get_db() as conn:
            user = conn.execute("SELECT password_hash FROM users WHERE id=?",
                                (session["user_id"],)).fetchone()
            if not user or not check_password_hash(user["password_hash"], current_pw):
                return err("Current password is incorrect.")
            conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                         (generate_password_hash(new_pw), session["user_id"]))
            conn.commit()

        if request.is_json:
            return jsonify({"success": True})
        flash("Password updated successfully.", "success")
        role = session.get("user_role")
        return redirect(
            url_for("accommodation.admin_dashboard") if role == "admin"
            else url_for("accommodation.landlord_dashboard") if role == "landlord"
            else url_for("accommodation.dashboard")
        )

    return render_template("accommodation/change_password.html",
                           user_name=session.get("user_name"),
                           user_role=session.get("user_role"),
                           user_email=session.get("user_email"),
                           unread_count=get_unread_count(session["user_id"]))


@accommodation_bp.route("/check-email")
def check_email_page():
    email = request.args.get("email", "")
    return render_template("accommodation/check_email.html",
                           email=email,
                           user_name=None,
                           user_role=None)


@accommodation_bp.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("5 per hour")
def forgot_password():
    if request.method == "POST":
        data  = request.get_json() if request.is_json else request.form
        email = (data.get("email") or "").strip().lower()
        ok_msg = "If that email is registered you'll receive a reset link shortly. Check your inbox (and spam folder)."

        if email and is_valid_email(email):
            with get_db() as conn:
                user = conn.execute(
                    "SELECT id, full_name FROM users WHERE email=? AND is_active=1", (email,)
                ).fetchone()

            if user:
                token     = secrets.token_urlsafe(48)
                expires   = datetime.utcnow() + timedelta(hours=1)
                with get_db() as conn:
                    conn.execute(
                        "UPDATE password_resets SET used=1 WHERE user_id=? AND used=0",
                        (user["id"],)
                    )
                    conn.execute(
                        "INSERT INTO password_resets (user_id, token, expires_at) VALUES (?,?,?)",
                        (user["id"], token, expires.isoformat())
                    )
                    conn.commit()

                reset_url = url_for("accommodation.reset_password", token=token, _external=True)
                _send_reset_email(email, user["full_name"], reset_url)

        if request.is_json:
            return jsonify({"success": True, "message": ok_msg})
        flash(ok_msg, "info")
        return redirect(url_for("accommodation.forgot_password"))

    return render_template("accommodation/forgot_password.html")


def _send_email(to_email, subject, html_body):
    if not SENDGRID_API_KEY:
        current_app.logger.error("SENDGRID_API_KEY not set — email not sent")
        return False
    try:
        resp = http_requests.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={"Authorization": f"Bearer {SENDGRID_API_KEY}", "Content-Type": "application/json"},
            json={
                "personalizations": [{"to": [{"email": to_email}]}],
                "from": {"email": MAIL_FROM_EMAIL, "name": MAIL_FROM_NAME},
                "subject": subject,
                "content": [{"type": "text/html", "value": html_body}]
            },
            timeout=10
        )
        if resp.status_code not in (200, 202):
            current_app.logger.error(f"SendGrid error {resp.status_code}: {resp.text}")
            return False
        return True
    except Exception as e:
        current_app.logger.error(f"Email send failed: {e}")
        return False


def _send_reset_email(to_email, name, reset_url):
    try:
        html_body = f"""
        <!DOCTYPE html>
        <html>
        <body style="margin:0;padding:0;background:#f0f4ff;font-family:Inter,system-ui,sans-serif">
          <div style="max-width:560px;margin:40px auto;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.08)">
            <div style="background:linear-gradient(135deg,#1d4ed8,#1e3a8a);padding:32px;text-align:center">
              <h1 style="color:#fff;margin:0;font-size:22px;font-weight:700">T-Tech Connect</h1>
              <p style="color:rgba(255,255,255,.8);margin:6px 0 0;font-size:14px">Connecting Tenants with Landlords</p>
            </div>
            <div style="padding:36px 32px">
              <h2 style="color:#111827;font-size:18px;margin:0 0 8px">Hi {name},</h2>
              <p style="color:#6b7280;line-height:1.6;margin:0 0 24px">
                We received a request to reset your T-Tech Connect password. Click the button below to choose a new password.
              </p>
              <div style="text-align:center;margin:0 0 28px">
                <a href="{reset_url}"
                   style="display:inline-block;padding:14px 32px;background:#1d4ed8;color:#fff;text-decoration:none;border-radius:10px;font-weight:600;font-size:15px">
                  Reset My Password
                </a>
              </div>
              <p style="color:#9ca3af;font-size:13px;line-height:1.6;margin:0 0 8px">
                This link expires in <strong>1 hour</strong>. If you didn't request a password reset, you can safely ignore this email — your account remains secure.
              </p>
              <p style="color:#9ca3af;font-size:12px;word-break:break-all;margin:0">
                Or copy this link: {reset_url}
              </p>
            </div>
            <div style="background:#f9fafb;padding:20px 32px;text-align:center;border-top:1px solid #f3f4f6">
              <p style="color:#9ca3af;font-size:12px;margin:0">© 2026 T-Tech Connect · This is an automated message, please do not reply.</p>
            </div>
          </div>
        </body>
        </html>
        """
        _send_email(to_email, "Reset your T-Tech Connect password", html_body)
    except Exception as e:
        current_app.logger.error(f"Password reset email failed: {e}")


def _send_verification_email(to_email, name, role, verify_url):
    role_label = "Tenant" if role == "student" else role.capitalize()
    try:
        html_body = f"""
        <!DOCTYPE html><html><body style="margin:0;padding:0;background:#f0f4ff;font-family:Inter,system-ui,sans-serif">
          <div style="max-width:560px;margin:40px auto;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.08)">
            <div style="background:linear-gradient(135deg,#1d4ed8,#1e3a8a);padding:32px;text-align:center">
              <h1 style="color:#fff;margin:0;font-size:22px;font-weight:700">Welcome to T-Tech Connect!</h1>
              <p style="color:rgba(255,255,255,.8);margin:6px 0 0;font-size:14px">Connecting Tenants with Landlords</p>
            </div>
            <div style="padding:36px 32px">
              <h2 style="color:#111827;font-size:18px;margin:0 0 8px">Hi {name},</h2>
              <p style="color:#6b7280;line-height:1.6;margin:0 0 16px">
                Welcome to T-Tech Connect as a <strong>{role_label}</strong>! We're excited to have you on board.
              </p>
              <p style="color:#6b7280;line-height:1.6;margin:0 0 24px">
                To complete your registration and activate your account, please verify your email address by clicking the button below.
              </p>
              <div style="text-align:center;margin:0 0 28px">
                <a href="{verify_url}"
                   style="display:inline-block;padding:14px 32px;background:#1d4ed8;color:#fff;text-decoration:none;border-radius:10px;font-weight:600;font-size:15px">
                  Verify My Email Address
                </a>
              </div>
              <p style="color:#9ca3af;font-size:13px;line-height:1.6;margin:0 0 8px">
                This link expires in <strong>24 hours</strong>. If you didn't create an account, you can safely ignore this email.
              </p>
              <p style="color:#9ca3af;font-size:12px;word-break:break-all;margin:0">
                Or copy this link: {verify_url}
              </p>
            </div>
            <div style="background:#f9fafb;padding:20px 32px;text-align:center;border-top:1px solid #f3f4f6">
              <p style="color:#9ca3af;font-size:12px;margin:0">© 2026 T-Tech Connect · This is an automated message, please do not reply.</p>
            </div>
          </div>
        </body></html>
        """
        _send_email(to_email, "Verify your T-Tech Connect email address", html_body)
    except Exception as e:
        current_app.logger.error(f"Verification email failed: {e}")


@accommodation_bp.route("/verify-email/<token>")
def verify_email(token):
    with get_db() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE email_verify_token=? AND is_active=1", (token,)
        ).fetchone()
        if not user:
            flash("Invalid or expired verification link.", "error")
            return redirect(url_for("accommodation.login"))
        conn.execute(
            "UPDATE users SET is_email_verified=1, email_verify_token=NULL WHERE id=?",
            (user["id"],)
        )
        conn.execute("UPDATE users SET last_login=CURRENT_TIMESTAMP, last_seen=CURRENT_TIMESTAMP WHERE id=?", (user["id"],))
        conn.commit()

    session.clear()
    session["user_id"]    = user["id"]
    session["user_name"]  = user["full_name"]
    session["user_role"]  = user["role"]
    session["user_email"] = user["email"]
    flash("Email verified! Welcome to T-Tech Connect.", "success")
    return redirect(role_redirect(user["role"]))


@accommodation_bp.route("/resend-verification", methods=["POST"])
def resend_verification():
    email = (request.get_json() or {}).get("email", "").strip().lower()
    if not email:
        return jsonify({"error": "Email required"}), 400
    with get_db() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE email=? AND is_active=1 AND is_email_verified=0", (email,)
        ).fetchone()
        if not user:
            return jsonify({"success": True})
        token = secrets.token_urlsafe(32)
        conn.execute("UPDATE users SET email_verify_token=? WHERE id=?", (token, user["id"]))
        conn.commit()
    verify_url = url_for("accommodation.verify_email", token=token, _external=True)
    _send_verification_email(email, user["full_name"], user["role"], verify_url)
    return jsonify({"success": True})


@accommodation_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    with get_db() as conn:
        reset = conn.execute(
            "SELECT * FROM password_resets WHERE token=? AND used=0",
            (token,)
        ).fetchone()

    if not reset:
        flash("This reset link is invalid or has already been used.", "error")
        return redirect(url_for("accommodation.forgot_password"))

    if datetime.utcnow() > datetime.fromisoformat(reset["expires_at"]):
        flash("This reset link has expired. Please request a new one.", "error")
        return redirect(url_for("accommodation.forgot_password"))

    if request.method == "POST":
        data     = request.get_json() if request.is_json else request.form
        password = data.get("password") or ""
        confirm  = data.get("confirm_password") or ""

        def err(msg):
            if request.is_json:
                return jsonify({"success": False, "error": msg}), 400
            return render_template("accommodation/reset_password.html", token=token, error=msg)

        if len(password) < 8:
            return err("Password must be at least 8 characters.")
        if password != confirm:
            return err("Passwords do not match.")

        with get_db() as conn:
            conn.execute(
                "UPDATE users SET password_hash=? WHERE id=?",
                (generate_password_hash(password), reset["user_id"])
            )
            conn.execute(
                "UPDATE password_resets SET used=1 WHERE token=?",
                (token,)
            )
            conn.commit()

        if request.is_json:
            return jsonify({"success": True, "redirect": url_for("accommodation.login")})
        flash("Password updated successfully. You can now sign in.", "success")
        return redirect(url_for("accommodation.login"))

    return render_template("accommodation/reset_password.html", token=token, error=None)


# ── Landlord routes ───────────────────────────────────────────────────────────

@accommodation_bp.route("/landlord")
@landlord_required
def landlord_dashboard():
    if session.get("user_role") == "admin":
        return redirect(url_for("accommodation.admin_properties"))
    lid = session["user_id"]
    with get_db() as conn:
        props = conn.execute("""
            SELECT p.*, COALESCE(AVG(r.rating), 0) as avg_rating, COUNT(r.id) as review_count
            FROM properties p LEFT JOIN reviews r ON r.property_id=p.id
            WHERE p.landlord_id=? AND p.is_active=1
            GROUP BY p.id ORDER BY p.created_at DESC
        """, (lid,)).fetchall()
        stats = conn.execute("""
            SELECT COUNT(*) as total,
                SUM(CASE WHEN status='available'   THEN 1 ELSE 0 END) as available,
                SUM(CASE WHEN status='occupied'    THEN 1 ELSE 0 END) as occupied,
                SUM(CASE WHEN status='partial'     THEN 1 ELSE 0 END) as partial,
                SUM(available_rooms) as total_available_rooms,
                SUM(price_per_month) as total_monthly
            FROM properties WHERE landlord_id=? AND is_active=1
        """, (lid,)).fetchone()

    prop_list = []
    for p in props:
        d = {**dict(p), "services": json.loads(p["services"] or "[]")}
        with get_db() as conn:
            cover = conn.execute(
                "SELECT filename FROM property_images WHERE property_id=? AND is_primary=1 LIMIT 1", (p["id"],)
            ).fetchone()
        d["cover_image"] = cover["filename"] if cover else None
        prop_list.append(d)

    unread = get_unread_count(lid)
    return render_template("accommodation/landlord_dashboard.html",
                           user_name=session.get("user_name"),
                           user_role=session.get("user_role"),
                           user_email=session.get("user_email"),
                           properties=prop_list, stats=stats,
                           unread_count=unread)


@accommodation_bp.route("/landlord/property/new", methods=["GET", "POST"])
@landlord_required
def property_new():
    if request.method == "POST": return _save_property(None)
    return render_template("accommodation/property_form.html", prop=None,
                           user_name=session.get("user_name"), user_role=session.get("user_role"),
                           user_email=session.get("user_email"),
                           unread_count=get_unread_count(session["user_id"]))


@accommodation_bp.route("/landlord/property/<int:pid>/edit", methods=["GET", "POST"])
@landlord_required
def property_edit(pid):
    prop = _get_own_property(pid)
    if not prop:
        flash("Property not found.", "error")
        return redirect(url_for("accommodation.admin_properties") if session.get("user_role") == "admin" else url_for("accommodation.landlord_dashboard"))
    if request.method == "POST": return _save_property(pid)
    d = {**dict(prop), "services": json.loads(prop["services"] or "[]")}
    d["images"] = _get_images(pid)
    return render_template("accommodation/property_form.html", prop=d,
                           user_name=session.get("user_name"), user_role=session.get("user_role"),
                           user_email=session.get("user_email"),
                           unread_count=get_unread_count(session["user_id"]))


@accommodation_bp.route("/landlord/property/<int:pid>/delete", methods=["POST"])
@landlord_required
def property_delete(pid):
    if not _get_own_property(pid):
        return jsonify({"success": False, "error": "Not found"}), 404
    with get_db() as conn:
        conn.execute("UPDATE properties SET is_active=0 WHERE id=?", (pid,))
        conn.commit()
    if request.is_json: return jsonify({"success": True})
    flash("Property deleted.", "success")
    return redirect(url_for("accommodation.admin_properties") if session.get("user_role") == "admin" else url_for("accommodation.landlord_dashboard"))


@accommodation_bp.route("/landlord/property/<int:pid>/image/<int:img_id>/delete", methods=["POST"])
@login_required
def property_image_delete(pid, img_id):
    uid  = session["user_id"]
    role = session.get("user_role")
    with get_db() as conn:
        prop = conn.execute("SELECT landlord_id FROM properties WHERE id=?", (pid,)).fetchone()
        if not prop or (prop["landlord_id"] != uid and role != "admin"):
            return jsonify({"error": "Not authorized"}), 403
        img = conn.execute(
            "SELECT filename FROM property_images WHERE id=? AND property_id=?", (img_id, pid)
        ).fetchone()
        if not img:
            return jsonify({"error": "Not found"}), 404
        conn.execute("DELETE FROM property_images WHERE id=?", (img_id,))
        conn.commit()
    path = os.path.join(UPLOAD_FOLDER, img["filename"])
    if os.path.exists(path):
        os.remove(path)
    return jsonify({"success": True})


@accommodation_bp.route("/landlord/property/<int:pid>/image/<int:img_id>/set-cover", methods=["POST"])
@login_required
def property_image_set_cover(pid, img_id):
    uid  = session["user_id"]
    role = session.get("user_role")
    with get_db() as conn:
        prop = conn.execute("SELECT landlord_id FROM properties WHERE id=?", (pid,)).fetchone()
        if not prop or (prop["landlord_id"] != uid and role != "admin"):
            return jsonify({"error": "Not authorized"}), 403
        if not conn.execute(
            "SELECT id FROM property_images WHERE id=? AND property_id=?", (img_id, pid)
        ).fetchone():
            return jsonify({"error": "Not found"}), 404
        conn.execute("UPDATE property_images SET is_primary=0 WHERE property_id=?", (pid,))
        conn.execute("UPDATE property_images SET is_primary=1 WHERE id=?", (img_id,))
        conn.commit()
    return jsonify({"success": True})


@accommodation_bp.route("/property/<int:pid>/pay", methods=["POST"])
@login_required
def pay_commission(pid):
    uid  = session["user_id"]
    role = session.get("user_role")
    if role not in ("student", "admin"):
        return jsonify({"error": "Only students can pay commission"}), 403

    with get_db() as conn:
        prop = conn.execute(
            "SELECT price_per_month, currency FROM properties WHERE id=? AND is_active=1", (pid,)
        ).fetchone()
    if not prop:
        return jsonify({"error": "Property not found"}), 404

    if has_paid(uid, pid):
        return jsonify({"success": True, "already_paid": True})

    data      = request.get_json() or {}
    reference = data.get("reference", "").strip()
    method    = data.get("method", "").strip()
    if not reference:
        return jsonify({"error": "Payment reference is required"}), 400

    ALLOWED_METHODS = {"ecocash", "paynow", "cash", "bank_transfer", "card"}
    if method.lower() not in ALLOWED_METHODS:
        return jsonify({"error": "Invalid payment method"}), 400

    amount = round(prop["price_per_month"] * get_commission_rate(), 2)
    with get_db() as conn:
        conn.execute(
            """INSERT INTO payments (student_id, property_id, amount, currency, reference)
               VALUES (?,?,?,?,?) ON CONFLICT (student_id, property_id) DO NOTHING""",
            (uid, pid, amount, prop["currency"], f"[{method.lower()}] {reference}")
        )
        conn.commit()
        landlord_row = conn.execute(
            "SELECT landlord_id, title FROM properties WHERE id=?", (pid,)
        ).fetchone()
        student_name = conn.execute("SELECT full_name FROM users WHERE id=?", (uid,)).fetchone()
    if landlord_row and student_name:
        _notify(
            landlord_row["landlord_id"], "commission_paid",
            f'Commission received for {landlord_row["title"]}',
            f'{student_name["full_name"]} has paid the viewing commission.',
            f"/accommodation/landlord/property/{pid}"
        )
    return jsonify({"success": True})


@accommodation_bp.route("/property/<int:pid>/ecocash-initiate", methods=["POST"])
@login_required
def ecocash_initiate(pid):
    uid = session["user_id"]
    if session.get("user_role") not in ("student", "admin"):
        return jsonify({"error": "Only tenants can initiate payment"}), 403

    if has_paid(uid, pid):
        return jsonify({"success": True, "already_paid": True})

    with get_db() as conn:
        existing_req = conn.execute(
            "SELECT id FROM payment_requests WHERE student_id=? AND property_id=? AND status='pending'",
            (uid, pid)
        ).fetchone()
    if existing_req:
        return jsonify({"success": True, "request_id": existing_req["id"], "already_pending": True})

    data  = request.get_json() or {}
    phone = data.get("phone", "").strip().replace(" ", "").replace("-", "")

    if phone.startswith("+263"):
        phone = "0" + phone[4:]
    elif phone.startswith("263"):
        phone = "0" + phone[3:]

    if not re.match(r"^07[78]\d{7}$", phone):
        return jsonify({"error": "Please enter a valid EcoCash number (077XXXXXXX or 078XXXXXXX)"}), 400

    with get_db() as conn:
        prop = conn.execute(
            "SELECT title, price_per_month, currency FROM properties WHERE id=? AND is_active=1", (pid,)
        ).fetchone()
    if not prop:
        return jsonify({"error": "Property not found"}), 404

    pn = get_paynow()
    if not pn:
        return jsonify({"error": "EcoCash payments are not configured. Ask admin to set PAYNOW_INTEGRATION_ID and PAYNOW_INTEGRATION_KEY."}), 503

    amount     = round(prop["price_per_month"] * get_commission_rate(), 2)
    request_id = str(uuid.uuid4())

    payment = pn.create_payment(f"TTC-{request_id[:8]}", session.get("user_email", ""))
    payment.add(f'Commission: {prop["title"]}', amount)

    try:
        response = pn.send_mobile(payment, phone, "ecocash")
    except Exception as e:
        return jsonify({"error": f"Could not reach payment gateway: {str(e)}"}), 502

    if not response.success:
        err = getattr(response, "errors", None) or "EcoCash payment failed to initiate"
        return jsonify({"error": str(err)}), 400

    with get_db() as conn:
        conn.execute(
            """INSERT INTO payment_requests (id, student_id, property_id, amount, currency, phone, poll_url)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (request_id, uid, pid, amount, prop["currency"], phone, response.poll_url)
        )
        conn.commit()

    return jsonify({"success": True, "request_id": request_id})


@accommodation_bp.route("/property/<int:pid>/payment-status/<req_id>")
@login_required
def check_payment_status(pid, req_id):
    uid = session["user_id"]

    with get_db() as conn:
        req = conn.execute(
            "SELECT * FROM payment_requests WHERE id=? AND student_id=? AND property_id=?",
            (req_id, uid, pid)
        ).fetchone()

    if not req:
        return jsonify({"error": "Request not found"}), 404

    if req["status"] == "paid":
        return jsonify({"status": "paid"})

    pn = get_paynow()
    if not pn:
        return jsonify({"error": "Payment system unavailable"}), 503

    try:
        status = pn.check_transaction_status(req["poll_url"])
    except Exception:
        return jsonify({"status": "pending"})

    if status.paid:
        with get_db() as conn:
            conn.execute("UPDATE payment_requests SET status='paid' WHERE id=?", (req_id,))
            conn.execute(
                """INSERT INTO payments (student_id, property_id, amount, currency, reference)
                   VALUES (?,?,?,?,?) ON CONFLICT (student_id, property_id) DO NOTHING""",
                (uid, pid, req["amount"], req["currency"], f'[EcoCash] {req["phone"]}')
            )
            conn.commit()
            prop = conn.execute(
                "SELECT title, landlord_id FROM properties WHERE id=?", (pid,)
            ).fetchone()
            student_name = conn.execute(
                "SELECT full_name FROM users WHERE id=?", (uid,)
            ).fetchone()
        if prop and student_name:
            _notify(
                prop["landlord_id"], "commission_paid",
                f'Commission received for {prop["title"]}',
                f'{student_name["full_name"]} has paid the viewing commission and wants to contact you.',
                f"/accommodation/landlord/property/{pid}"
            )
        return jsonify({"status": "paid"})

    return jsonify({"status": req["status"] or "pending"})


@accommodation_bp.route("/landlord/property/<int:pid>")
@login_required
def property_view(pid):
    with get_db() as conn:
        prop = conn.execute(
            """SELECT p.*, u.full_name as landlord_name, u.id as landlord_user_id,
                      u.is_verified as landlord_verified,
                      COALESCE(AVG(r.rating), 0) as avg_rating,
                      COUNT(r.id) as review_count
               FROM properties p JOIN users u ON p.landlord_id = u.id
               LEFT JOIN reviews r ON r.property_id = p.id
               WHERE p.id=? AND p.is_active=1
               GROUP BY p.id, u.full_name, u.id, u.is_verified""", (pid,)
        ).fetchone()
    if not prop:
        flash("Property not found.", "error")
        return redirect(url_for("accommodation.dashboard"))
    d = {**dict(prop), "services": json.loads(prop["services"] or "[]"),
         "images": _get_images(pid)}
    rate = get_commission_rate()
    d["commission"] = round(d["price_per_month"] * rate, 2)
    d["commission_pct"] = round(rate * 100, 1)

    uid  = session["user_id"]
    role = session.get("user_role")
    paid = True if role in ("landlord", "admin") else has_paid(uid, pid)

    with get_db() as conn:
        reviews_rows = conn.execute("""
            SELECT r.rating, r.comment, r.created_at, u.full_name as reviewer_name
            FROM reviews r JOIN users u ON r.reviewer_id=u.id
            WHERE r.property_id=? ORDER BY r.created_at DESC
        """, (pid,)).fetchall()
        user_reviewed = conn.execute(
            "SELECT rating FROM reviews WHERE property_id=? AND reviewer_id=?",
            (pid, uid)
        ).fetchone()

    return render_template("accommodation/property_view.html", prop=d,
                           user_name=session.get("user_name"),
                           user_role=role,
                           user_email=session.get("user_email"),
                           current_user_id=uid,
                           has_paid=paid,
                           reviews=[dict(r) for r in reviews_rows],
                           user_reviewed=user_reviewed,
                           unread_count=get_unread_count(uid))


@accommodation_bp.route("/property/<int:pid>/review", methods=["POST"])
@login_required
def submit_review(pid):
    uid  = session["user_id"]
    role = session.get("user_role")
    if role != "student":
        flash("Only tenants can leave reviews.", "error")
        return redirect(url_for("accommodation.property_view", pid=pid))

    if not has_paid(uid, pid):
        flash("You must pay the viewing commission before reviewing this property.", "error")
        return redirect(url_for("accommodation.property_view", pid=pid))

    rating  = (request.form.get("rating") or "").strip()
    comment = (request.form.get("comment") or "").strip()[:500]

    if not rating or not rating.isdigit() or not (1 <= int(rating) <= 5):
        flash("Please select a rating between 1 and 5 stars.", "error")
        return redirect(url_for("accommodation.property_view", pid=pid))

    with get_db() as conn:
        if not conn.execute("SELECT id FROM properties WHERE id=? AND is_active=1", (pid,)).fetchone():
            flash("Property not found.", "error")
            return redirect(url_for("accommodation.dashboard"))
        try:
            conn.execute(
                "INSERT INTO reviews (property_id, reviewer_id, rating, comment) VALUES (?,?,?,?)",
                (pid, uid, int(rating), comment)
            )
            conn.commit()
            flash("Your review has been posted. Thank you!", "success")
        except Exception:
            conn.rollback()
            flash("You have already reviewed this property.", "info")

    return redirect(url_for("accommodation.property_view", pid=pid))


# ── Messaging routes ──────────────────────────────────────────────────────────

@accommodation_bp.route("/contact-support")
@login_required
def contact_support():
    uid  = session["user_id"]
    role = session.get("user_role")
    if role == "admin":
        return redirect(url_for("accommodation.messages_page"))

    with get_db() as conn:
        admin = conn.execute(
            "SELECT id FROM users WHERE role='admin' AND is_active=1 AND id!=? ORDER BY id LIMIT 1",
            (uid,)
        ).fetchone()
        if not admin:
            flash("No support agent is available right now. Please try again later.", "warning")
            return redirect(url_for("accommodation.dashboard") if role == "student" else url_for("accommodation.landlord_dashboard"))

        admin_id = admin["id"]

        existing = conn.execute("""
            SELECT c.id FROM conversations c
            JOIN conversation_members cm1 ON c.id=cm1.conversation_id AND cm1.user_id=?
            JOIN conversation_members cm2 ON c.id=cm2.conversation_id AND cm2.user_id=?
            WHERE c.property_id IS NULL
            LIMIT 1
        """, (uid, admin_id)).fetchone()

        if existing:
            return redirect(url_for("accommodation.messages_page", c=existing["id"]))

        cur = conn.execute(
            "INSERT INTO conversations (subject, property_id) VALUES (?, NULL) RETURNING id",
            ("T-Tech Connect Support",)
        )
        conv_id = cur.fetchone()["id"]
        conn.execute("INSERT INTO conversation_members (conversation_id, user_id) VALUES (?,?)", (conv_id, uid))
        conn.execute("INSERT INTO conversation_members (conversation_id, user_id) VALUES (?,?)", (conv_id, admin_id))
        conn.commit()

    return redirect(url_for("accommodation.messages_page", c=conv_id))


@accommodation_bp.route("/messages")
@login_required
def messages_page():
    uid = session["user_id"]
    open_conv = request.args.get("c", type=int)
    with get_db() as conn:
        conn.execute("UPDATE users SET last_seen=CURRENT_TIMESTAMP WHERE id=?", (uid,))
        conn.commit()
    return render_template("accommodation/chat.html",
                           user_name=session.get("user_name"),
                           user_role=session.get("user_role"),
                           user_email=session.get("user_email"),
                           current_user_id=uid,
                           open_conv=open_conv,
                           unread_count=0)


@accommodation_bp.route("/api/conversations")
@login_required
def api_conversations():
    uid = session["user_id"]
    with get_db() as conn:
        rows = conn.execute("""
            SELECT
                c.id, c.subject, c.property_id, c.updated_at,
                p.title as property_title,
                u.id as other_id,
                CASE WHEN u.role='admin' THEN 'T-Tech Support' ELSE u.full_name END as other_name,
                u.role as other_role,
                u.last_seen as other_last_seen,
                (SELECT content FROM messages WHERE conversation_id=c.id
                 AND is_deleted=0 ORDER BY sent_at DESC LIMIT 1) as last_msg,
                (SELECT sent_at FROM messages WHERE conversation_id=c.id
                 AND is_deleted=0 ORDER BY sent_at DESC LIMIT 1) as last_msg_time,
                (SELECT sender_id FROM messages WHERE conversation_id=c.id
                 AND is_deleted=0 ORDER BY sent_at DESC LIMIT 1) as last_sender_id,
                (SELECT COUNT(*) FROM messages m2
                 JOIN conversation_members cm2 ON m2.conversation_id=cm2.conversation_id AND cm2.user_id=?
                 WHERE m2.conversation_id=c.id AND m2.sender_id!=?
                   AND (m2.sent_at > cm2.last_read_at OR cm2.last_read_at IS NULL)
                   AND m2.is_deleted=0) as unread
            FROM conversations c
            JOIN conversation_members cm ON c.id = cm.conversation_id AND cm.user_id = ?
            JOIN conversation_members cm2 ON c.id = cm2.conversation_id AND cm2.user_id != ?
            JOIN users u ON cm2.user_id = u.id
            LEFT JOIN properties p ON c.property_id = p.id
            ORDER BY COALESCE(last_msg_time, c.updated_at) DESC
        """, (uid, uid, uid, uid)).fetchall()
    return jsonify([dict(r) for r in rows])


@accommodation_bp.route("/api/messages/<int:conv_id>")
@login_required
def api_get_messages(conv_id):
    uid = session["user_id"]
    with get_db() as conn:
        member = conn.execute(
            "SELECT 1 FROM conversation_members WHERE conversation_id=? AND user_id=?",
            (conv_id, uid)
        ).fetchone()
        if not member:
            return jsonify({"error": "Not a member"}), 403

        rows = conn.execute("""
            SELECT m.id, m.sender_id, m.content, m.sent_at,
                   u.full_name as sender_name, u.role as sender_role
            FROM messages m
            JOIN users u ON m.sender_id = u.id
            WHERE m.conversation_id=? AND m.is_deleted=0
            ORDER BY m.sent_at ASC
        """, (conv_id,)).fetchall()

        conn.execute("""
            UPDATE conversation_members SET last_read_at=CURRENT_TIMESTAMP
            WHERE conversation_id=? AND user_id=?
        """, (conv_id, uid))
        conn.commit()

    return jsonify([dict(r) for r in rows])


@accommodation_bp.route("/api/conversations/start", methods=["POST"])
@login_required
def api_start_conversation():
    uid  = session["user_id"]
    data = request.get_json() or {}
    recipient_id = data.get("recipient_id")
    property_id  = data.get("property_id")
    subject      = data.get("subject", "Property Inquiry")

    if not recipient_id:
        return jsonify({"error": "recipient_id required"}), 400
    if recipient_id == uid:
        return jsonify({"error": "Cannot message yourself"}), 400

    role = session.get("user_role")
    if role == "student":
        with get_db() as conn:
            row = conn.execute("SELECT role FROM users WHERE id=?", (recipient_id,)).fetchone()
            recipient_role = row["role"] if row else None
        if recipient_role == "landlord":
            if not property_id:
                return jsonify({"error": "A property must be selected to contact a landlord"}), 400
            if not has_paid(uid, property_id):
                return jsonify({"error": "Commission payment required to contact this landlord"}), 403

    with get_db() as conn:
        if property_id:
            existing = conn.execute("""
                SELECT c.id FROM conversations c
                JOIN conversation_members cm1 ON c.id=cm1.conversation_id AND cm1.user_id=?
                JOIN conversation_members cm2 ON c.id=cm2.conversation_id AND cm2.user_id=?
                WHERE c.property_id=?
                LIMIT 1
            """, (uid, recipient_id, property_id)).fetchone()
        else:
            existing = conn.execute("""
                SELECT c.id FROM conversations c
                JOIN conversation_members cm1 ON c.id=cm1.conversation_id AND cm1.user_id=?
                JOIN conversation_members cm2 ON c.id=cm2.conversation_id AND cm2.user_id=?
                LIMIT 1
            """, (uid, recipient_id)).fetchone()

        if existing:
            return jsonify({"conv_id": existing["id"]})

        cur = conn.execute(
            "INSERT INTO conversations (subject, property_id) VALUES (?,?) RETURNING id",
            (subject, property_id)
        )
        conv_id = cur.fetchone()["id"]
        conn.execute("INSERT INTO conversation_members (conversation_id, user_id) VALUES (?,?)", (conv_id, uid))
        conn.execute("INSERT INTO conversation_members (conversation_id, user_id) VALUES (?,?)", (conv_id, recipient_id))
        conn.commit()

    return jsonify({"conv_id": conv_id})


@accommodation_bp.route("/api/conversations/<int:conv_id>/send", methods=["POST"])
@login_required
def api_send_message_rest(conv_id):
    uid     = session["user_id"]
    data    = request.get_json() or {}
    content = (data.get("content") or "").strip()

    if not content:
        return jsonify({"error": "Message cannot be empty"}), 400

    with get_db() as conn:
        if not conn.execute(
            "SELECT 1 FROM conversation_members WHERE conversation_id=? AND user_id=?",
            (conv_id, uid)
        ).fetchone():
            return jsonify({"error": "Not a member"}), 403

        cur = conn.execute(
            "INSERT INTO messages (conversation_id, sender_id, content) VALUES (?,?,?) RETURNING id",
            (conv_id, uid, content)
        )
        msg_id = cur.fetchone()["id"]
        conn.execute("UPDATE conversations SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (conv_id,))
        conn.execute(
            "UPDATE conversation_members SET last_read_at=CURRENT_TIMESTAMP WHERE conversation_id=? AND user_id=?",
            (conv_id, uid)
        )
        conn.commit()

        msg_row = conn.execute(
            """SELECT m.*, u.full_name as sender_name, u.role as sender_role
               FROM messages m JOIN users u ON m.sender_id=u.id WHERE m.id=?""",
            (msg_id,)
        ).fetchone()

    socketio.emit("new_msg", dict(msg_row), room=f"conv_{conv_id}")
    return jsonify({"success": True, "msg_id": msg_id})


@accommodation_bp.route("/api/conversations/<int:conv_id>/read", methods=["POST"])
@login_required
def api_mark_read(conv_id):
    uid = session["user_id"]
    with get_db() as conn:
        conn.execute("""
            UPDATE conversation_members SET last_read_at=CURRENT_TIMESTAMP
            WHERE conversation_id=? AND user_id=?
        """, (conv_id, uid))
        conn.commit()
    return jsonify({"success": True})


@accommodation_bp.route("/api/messages/unread-count")
@login_required
def api_unread_count():
    return jsonify({"count": get_unread_count(session["user_id"])})


@accommodation_bp.route("/api/users/search")
@login_required
def api_users_search():
    uid  = session["user_id"]
    role = session.get("user_role")
    q    = request.args.get("q", "").strip()
    with get_db() as conn:
        if role == "admin":
            if q:
                rows = conn.execute(
                    """SELECT id, full_name, email, role FROM users
                       WHERE is_active=1 AND id!=?
                         AND (full_name LIKE ? OR email LIKE ?)
                       ORDER BY full_name LIMIT 20""",
                    (uid, f"%{q}%", f"%{q}%")
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, full_name, email, role FROM users WHERE is_active=1 AND id!=? ORDER BY full_name LIMIT 20",
                    (uid,)
                ).fetchall()
        else:
            return jsonify({"error": "Not authorised"}), 403
    return jsonify([dict(r) for r in rows])


@accommodation_bp.route("/api/properties")
def api_properties():
    status = request.args.get("status")
    city   = request.args.get("city")
    query  = """
        SELECT p.*, u.full_name as landlord_name, u.phone as landlord_phone,
               u.is_verified as landlord_verified
        FROM properties p
        JOIN users u ON p.landlord_id = u.id
        WHERE p.is_active=1
    """
    params = []
    if status: query += " AND p.status=?";    params.append(status)
    if city:   query += " AND p.city LIKE ?"; params.append(f"%{city}%")
    query += " ORDER BY p.created_at DESC"
    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
        result = []
        for r in rows:
            d = {**dict(r), "services": json.loads(r["services"] or "[]")}
            imgs = conn.execute(
                "SELECT filename, is_primary FROM property_images WHERE property_id=? ORDER BY is_primary DESC, uploaded_at ASC",
                (r["id"],)
            ).fetchall()
            d["images"] = [
                {
                    "filename": i["filename"],
                    "url": f'/accommodation/static/uploads/properties/{i["filename"]}',
                    "is_primary": bool(i["is_primary"]),
                }
                for i in imgs
            ]
            result.append(d)
    return jsonify(result)


@accommodation_bp.route("/api/enquiries", methods=["POST"])
@require_api_key
def api_create_enquiry():
    data        = request.get_json() or {}
    property_id = data.get("property_id")
    name        = (data.get("name") or "").strip()
    email       = (data.get("email") or "").strip()
    phone       = (data.get("phone") or "").strip()
    message     = (data.get("message") or "").strip()

    if not property_id or not name or not email:
        return jsonify({"error": "property_id, name and email are required"}), 400

    with get_db() as conn:
        prop = conn.execute(
            "SELECT * FROM properties WHERE id=? AND is_active=1", (property_id,)
        ).fetchone()
        if not prop:
            return jsonify({"error": "Property not found"}), 404
        cur = conn.execute(
            "INSERT INTO enquiries (property_id, name, email, phone, message) VALUES (?,?,?,?,?) RETURNING id",
            (property_id, name, email, phone, message)
        )
        enquiry_id = cur.fetchone()["id"]
        conn.commit()

    _send_webhook("enquiry.created", {
        "enquiry_id": enquiry_id,
        "property_id": property_id,
        "property_title": prop["title"],
        "name": name,
        "email": email,
        "phone": phone,
        "message": message,
    })
    _notify(
        prop["landlord_id"], "enquiry",
        f'New enquiry for {prop["title"]}',
        f"{name} sent an enquiry via the chatbot.",
        f"/accommodation/landlord/property/{property_id}"
    )
    return jsonify({"success": True, "enquiry_id": enquiry_id}), 201


@accommodation_bp.route("/api/viewings", methods=["POST"])
@require_api_key
def api_create_viewing():
    data           = request.get_json() or {}
    property_id    = data.get("property_id")
    name           = (data.get("name") or "").strip()
    email          = (data.get("email") or "").strip()
    phone          = (data.get("phone") or "").strip()
    preferred_date = (data.get("preferred_date") or "").strip()
    preferred_time = (data.get("preferred_time") or "").strip()
    notes          = (data.get("notes") or "").strip()

    if not property_id or not name or not email:
        return jsonify({"error": "property_id, name and email are required"}), 400

    with get_db() as conn:
        prop = conn.execute(
            "SELECT * FROM properties WHERE id=? AND is_active=1", (property_id,)
        ).fetchone()
        if not prop:
            return jsonify({"error": "Property not found"}), 404
        cur = conn.execute(
            "INSERT INTO viewings (property_id, name, email, phone, preferred_date, preferred_time, notes) VALUES (?,?,?,?,?,?,?) RETURNING id",
            (property_id, name, email, phone, preferred_date or None, preferred_time, notes)
        )
        viewing_id = cur.fetchone()["id"]
        conn.commit()

    _send_webhook("viewing.scheduled", {
        "viewing_id": viewing_id,
        "property_id": property_id,
        "property_title": prop["title"],
        "name": name,
        "email": email,
        "phone": phone,
        "preferred_date": preferred_date,
        "preferred_time": preferred_time,
    })
    _notify(
        prop["landlord_id"], "viewing_request",
        f'Viewing request for {prop["title"]}',
        f'{name} wants to view your property on {preferred_date or "a date TBD"}.',
        f"/accommodation/landlord/property/{property_id}"
    )
    return jsonify({"success": True, "viewing_id": viewing_id}), 201


@accommodation_bp.route("/api/appointments", methods=["POST"])
@require_api_key
def api_create_appointment():
    data             = request.get_json() or {}
    property_id      = data.get("property_id")
    name             = (data.get("name") or "").strip()
    email            = (data.get("email") or "").strip()
    phone            = (data.get("phone") or "").strip()
    appointment_date = (data.get("appointment_date") or "").strip()
    appointment_time = (data.get("appointment_time") or "").strip()
    appt_type        = (data.get("type") or "viewing").strip()
    notes            = (data.get("notes") or "").strip()

    if not property_id or not name or not email or not appointment_date:
        return jsonify({"error": "property_id, name, email and appointment_date are required"}), 400

    with get_db() as conn:
        prop = conn.execute(
            "SELECT * FROM properties WHERE id=? AND is_active=1", (property_id,)
        ).fetchone()
        if not prop:
            return jsonify({"error": "Property not found"}), 404
        cur = conn.execute(
            "INSERT INTO appointments (property_id, name, email, phone, appointment_date, appointment_time, type, notes) VALUES (?,?,?,?,?,?,?,?) RETURNING id",
            (property_id, name, email, phone, appointment_date, appointment_time, appt_type, notes)
        )
        appointment_id = cur.fetchone()["id"]
        conn.commit()

    _send_webhook("appointment.booked", {
        "appointment_id": appointment_id,
        "property_id": property_id,
        "property_title": prop["title"],
        "name": name,
        "email": email,
        "phone": phone,
        "appointment_date": appointment_date,
        "appointment_time": appointment_time,
        "type": appt_type,
    })
    _notify(
        prop["landlord_id"], "appointment",
        f'New appointment for {prop["title"]}',
        f"{name} booked a {appt_type} appointment on {appointment_date}.",
        f"/accommodation/landlord/property/{property_id}"
    )
    return jsonify({"success": True, "appointment_id": appointment_id}), 201


@accommodation_bp.route("/api/check-session")
def check_session():
    if "user_id" in session:
        return jsonify({"authenticated": True, "role": session.get("user_role")})
    return jsonify({"authenticated": False}), 401


# ── Notifications ─────────────────────────────────────────────────────────────

@accommodation_bp.route("/api/notifications")
@login_required
def api_notifications():
    uid = session["user_id"]
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 50",
            (uid,)
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@accommodation_bp.route("/api/notifications/<int:nid>/read", methods=["POST"])
@login_required
def api_notification_read(nid):
    uid = session["user_id"]
    with get_db() as conn:
        conn.execute(
            "UPDATE notifications SET is_read=1 WHERE id=? AND user_id=?", (nid, uid)
        )
        conn.commit()
    return jsonify({"success": True})


@accommodation_bp.route("/api/notifications/read-all", methods=["POST"])
@login_required
def api_notifications_read_all():
    uid = session["user_id"]
    with get_db() as conn:
        conn.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (uid,))
        conn.commit()
    return jsonify({"success": True})


@accommodation_bp.route("/api/notifications/unread-count")
@login_required
def api_notifications_unread_count():
    uid = session["user_id"]
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM notifications WHERE user_id=? AND is_read=0", (uid,)
        ).fetchone()
    return jsonify({"count": row["cnt"] if row else 0})


# ── Bookings (application workflow) ───────────────────────────────────────────

@accommodation_bp.route("/property/<int:pid>/book", methods=["POST"])
@login_required
def booking_create(pid):
    uid  = session["user_id"]
    role = session.get("user_role")
    if role != "student":
        return jsonify({"error": "Only tenants can submit booking applications"}), 403

    if not has_paid(uid, pid):
        return jsonify({"error": "Commission payment required before applying"}), 403

    with get_db() as conn:
        prop = conn.execute(
            "SELECT * FROM properties WHERE id=? AND is_active=1", (pid,)
        ).fetchone()
        if not prop:
            return jsonify({"error": "Property not found"}), 404
        if prop["available_rooms"] <= 0 or prop["status"] == "occupied":
            return jsonify({"error": "No rooms available on this property"}), 400

        existing = conn.execute(
            "SELECT id, status FROM bookings WHERE property_id=? AND tenant_id=?",
            (pid, uid)
        ).fetchone()
        if existing:
            if existing["status"] == "pending":
                return jsonify({"error": "You already have a pending application for this property"}), 400
            if existing["status"] == "accepted":
                return jsonify({"error": "You are already accepted for this property"}), 400

        data             = request.get_json() or {}
        message          = (data.get("message") or "").strip()[:1000]
        proposed_move_in = (data.get("proposed_move_in") or "").strip() or None

        if existing:
            conn.execute(
                "UPDATE bookings SET message=?, proposed_move_in=?, status='pending', updated_at=CURRENT_TIMESTAMP WHERE property_id=? AND tenant_id=?",
                (message, proposed_move_in, pid, uid)
            )
            conn.commit()
            booking_id = existing["id"]
        else:
            cur = conn.execute(
                """INSERT INTO bookings (property_id, tenant_id, landlord_id, message, proposed_move_in)
                   VALUES (?,?,?,?,?) RETURNING id""",
                (pid, uid, prop["landlord_id"], message, proposed_move_in)
            )
            booking_id = cur.fetchone()["id"]
            conn.commit()

        student_name = conn.execute("SELECT full_name FROM users WHERE id=?", (uid,)).fetchone()

    _notify(
        prop["landlord_id"], "booking_request",
        f'New booking application for {prop["title"]}',
        f'{student_name["full_name"]} has applied to rent your property.',
        "/accommodation/landlord/bookings"
    )
    return jsonify({"success": True, "booking_id": booking_id})


@accommodation_bp.route("/landlord/bookings")
@landlord_required
def landlord_bookings():
    lid = session["user_id"]
    with get_db() as conn:
        bookings = conn.execute("""
            SELECT b.*, p.title as property_title, p.price_per_month,
                   u.full_name as tenant_name, u.email as tenant_email, u.phone as tenant_phone
            FROM bookings b
            JOIN properties p ON b.property_id=p.id
            JOIN users u ON b.tenant_id=u.id
            WHERE b.landlord_id=? AND p.is_active=1
            ORDER BY b.created_at DESC
        """, (lid,)).fetchall()
    return render_template("accommodation/landlord_bookings.html",
                           bookings=[dict(b) for b in bookings],
                           user_name=session.get("user_name"),
                           user_role=session.get("user_role"),
                           user_email=session.get("user_email"),
                           unread_count=get_unread_count(lid))


@accommodation_bp.route("/landlord/bookings/<int:bid>/accept", methods=["POST"])
@landlord_required
def booking_accept(bid):
    lid  = session["user_id"]
    data = request.get_json() or {}
    unit_number  = (data.get("unit_number") or "").strip()
    lease_start  = (data.get("lease_start") or "").strip()
    lease_end    = (data.get("lease_end") or "").strip() or None
    landlord_notes = (data.get("notes") or "").strip()

    if not lease_start:
        return jsonify({"error": "Lease start date is required"}), 400

    with get_db() as conn:
        booking = conn.execute(
            "SELECT * FROM bookings WHERE id=? AND landlord_id=? AND status='pending'",
            (bid, lid)
        ).fetchone()
        if not booking:
            return jsonify({"error": "Booking not found or already actioned"}), 404

        prop = conn.execute(
            "SELECT * FROM properties WHERE id=? AND is_active=1", (booking["property_id"],)
        ).fetchone()
        if not prop:
            return jsonify({"error": "Property not found"}), 404

        conn.execute("""
            INSERT INTO tenancies
                (property_id, tenant_id, landlord_id, booking_id, agreed_rent, currency,
                 unit_number, lease_start, lease_end, status)
            VALUES (?,?,?,?,?,?,?,?,?,'active')
        """, (
            booking["property_id"], booking["tenant_id"], lid, bid,
            prop["price_per_month"], prop["currency"],
            unit_number, lease_start, lease_end
        ))

        new_available = max(0, prop["available_rooms"] - 1)
        new_status    = "occupied" if new_available == 0 else "partial"
        conn.execute(
            "UPDATE properties SET available_rooms=?, status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (new_available, new_status, booking["property_id"])
        )

        conn.execute(
            "UPDATE bookings SET status='accepted', landlord_notes=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (landlord_notes, bid)
        )
        conn.commit()

        tenant_name = conn.execute("SELECT full_name FROM users WHERE id=?", (booking["tenant_id"],)).fetchone()

    _notify(
        booking["tenant_id"], "booking_accepted",
        f'Your application for {prop["title"]} was accepted!',
        f"Congratulations! Your lease starts on {lease_start}. Please contact your landlord for next steps.",
        "/accommodation/tenant/my-tenancy"
    )
    _send_webhook("booking.confirmed", {
        "booking_id": bid,
        "property_id": booking["property_id"],
        "property_title": prop["title"],
        "tenant_name": tenant_name["full_name"] if tenant_name else "",
        "lease_start": lease_start,
        "lease_end": lease_end,
    })
    return jsonify({"success": True})


@accommodation_bp.route("/landlord/bookings/<int:bid>/reject", methods=["POST"])
@landlord_required
def booking_reject(bid):
    lid  = session["user_id"]
    data = request.get_json() or {}
    notes = (data.get("notes") or "").strip()

    with get_db() as conn:
        booking = conn.execute(
            "SELECT * FROM bookings WHERE id=? AND landlord_id=? AND status='pending'",
            (bid, lid)
        ).fetchone()
        if not booking:
            return jsonify({"error": "Booking not found or already actioned"}), 404
        conn.execute(
            "UPDATE bookings SET status='rejected', landlord_notes=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (notes, bid)
        )
        conn.commit()
        prop = conn.execute("SELECT title FROM properties WHERE id=?", (booking["property_id"],)).fetchone()

    _notify(
        booking["tenant_id"], "booking_rejected",
        f'Your application for {prop["title"]} was not successful',
        notes or "The landlord has reviewed your application.",
        "/accommodation/dashboard"
    )
    return jsonify({"success": True})


@accommodation_bp.route("/tenant/bookings")
@login_required
def tenant_bookings():
    uid  = session["user_id"]
    if session.get("user_role") != "student":
        return redirect(url_for("accommodation.dashboard"))
    with get_db() as conn:
        bookings = conn.execute("""
            SELECT b.*, p.title as property_title, p.address, p.price_per_month,
                   u.full_name as landlord_name, u.phone as landlord_phone, u.email as landlord_email
            FROM bookings b
            JOIN properties p ON b.property_id=p.id
            JOIN users u ON b.landlord_id=u.id
            WHERE b.tenant_id=?
            ORDER BY b.created_at DESC
        """, (uid,)).fetchall()
    return render_template("accommodation/tenant_bookings.html",
                           bookings=[dict(b) for b in bookings],
                           user_name=session.get("user_name"),
                           user_role=session.get("user_role"),
                           user_email=session.get("user_email"),
                           unread_count=get_unread_count(uid))


# ── Tenancies ─────────────────────────────────────────────────────────────────

@accommodation_bp.route("/landlord/tenancies")
@landlord_required
def landlord_tenancies():
    lid = session["user_id"]
    with get_db() as conn:
        tenancies = conn.execute("""
            SELECT t.*, p.title as property_title, p.address,
                   u.full_name as tenant_name, u.email as tenant_email, u.phone as tenant_phone
            FROM tenancies t
            JOIN properties p ON t.property_id=p.id
            JOIN users u ON t.tenant_id=u.id
            WHERE t.landlord_id=?
            ORDER BY t.lease_start DESC
        """, (lid,)).fetchall()
    return render_template("accommodation/landlord_tenancies.html",
                           tenancies=[dict(t) for t in tenancies],
                           user_name=session.get("user_name"),
                           user_role=session.get("user_role"),
                           user_email=session.get("user_email"),
                           unread_count=get_unread_count(lid))


@accommodation_bp.route("/landlord/tenancies/<int:tid>/end", methods=["POST"])
@landlord_required
def tenancy_end(tid):
    lid  = session["user_id"]
    data = request.get_json() or {}
    notes = (data.get("notes") or "").strip()
    with get_db() as conn:
        tenancy = conn.execute(
            "SELECT * FROM tenancies WHERE id=? AND landlord_id=? AND status='active'",
            (tid, lid)
        ).fetchone()
        if not tenancy:
            return jsonify({"error": "Active tenancy not found"}), 404
        conn.execute(
            "UPDATE tenancies SET status='ended', notes=?, lease_end=CURRENT_DATE, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (notes, tid)
        )
        prop = conn.execute("SELECT available_rooms, total_rooms FROM properties WHERE id=?",
                            (tenancy["property_id"],)).fetchone()
        if prop:
            new_available = min(prop["total_rooms"], prop["available_rooms"] + 1)
            new_status    = "available" if new_available == prop["total_rooms"] else "partial"
            conn.execute(
                "UPDATE properties SET available_rooms=?, status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (new_available, new_status, tenancy["property_id"])
            )
        conn.commit()
        prop_title = conn.execute("SELECT title FROM properties WHERE id=?", (tenancy["property_id"],)).fetchone()
    _notify(
        tenancy["tenant_id"], "tenancy_ended",
        "Your tenancy has ended",
        notes or f'Your tenancy at {prop_title["title"] if prop_title else "the property"} has been marked as ended.',
        "/accommodation/tenant/my-tenancy"
    )
    return jsonify({"success": True})


@accommodation_bp.route("/tenant/my-tenancy")
@login_required
def tenant_my_tenancy():
    uid  = session["user_id"]
    if session.get("user_role") != "student":
        return redirect(url_for("accommodation.dashboard"))
    with get_db() as conn:
        tenancy = conn.execute("""
            SELECT t.*, p.title as property_title, p.address, p.city,
                   u.full_name as landlord_name, u.email as landlord_email, u.phone as landlord_phone
            FROM tenancies t
            JOIN properties p ON t.property_id=p.id
            JOIN users u ON t.landlord_id=u.id
            WHERE t.tenant_id=? AND t.status='active'
            ORDER BY t.created_at DESC LIMIT 1
        """, (uid,)).fetchone()
        past = conn.execute("""
            SELECT t.*, p.title as property_title
            FROM tenancies t JOIN properties p ON t.property_id=p.id
            WHERE t.tenant_id=? AND t.status != 'active'
            ORDER BY t.created_at DESC
        """, (uid,)).fetchall()
    return render_template("accommodation/tenant_tenancy.html",
                           tenancy=dict(tenancy) if tenancy else None,
                           past_tenancies=[dict(t) for t in past],
                           user_name=session.get("user_name"),
                           user_role=session.get("user_role"),
                           user_email=session.get("user_email"),
                           unread_count=get_unread_count(uid))


# ── Maintenance Requests ───────────────────────────────────────────────────────

@accommodation_bp.route("/property/<int:pid>/maintenance", methods=["POST"])
@login_required
def maintenance_create(pid):
    uid  = session["user_id"]
    role = session.get("user_role")
    if role != "student":
        return jsonify({"error": "Only tenants can submit maintenance requests"}), 403

    with get_db() as conn:
        prop = conn.execute(
            "SELECT * FROM properties WHERE id=? AND is_active=1", (pid,)
        ).fetchone()
        if not prop:
            return jsonify({"error": "Property not found"}), 404
        tenancy = conn.execute(
            "SELECT id FROM tenancies WHERE property_id=? AND tenant_id=? AND status='active'",
            (pid, uid)
        ).fetchone()
        if not tenancy:
            return jsonify({"error": "You must be an active tenant to submit a maintenance request"}), 403

    data     = request.get_json() or {}
    title    = (data.get("title") or "").strip()
    desc     = (data.get("description") or "").strip()[:2000]
    priority = (data.get("priority") or "normal").strip().lower()

    if not title:
        return jsonify({"error": "Title is required"}), 400
    if priority not in ("low", "normal", "high", "urgent"):
        priority = "normal"

    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO maintenance_requests (property_id, tenant_id, title, description, priority) VALUES (?,?,?,?,?) RETURNING id",
            (pid, uid, title, desc, priority)
        )
        rid = cur.fetchone()["id"]
        conn.commit()
        student_name = conn.execute("SELECT full_name FROM users WHERE id=?", (uid,)).fetchone()

    _notify(
        prop["landlord_id"], "maintenance_request",
        f"Maintenance request: {title}",
        f'{student_name["full_name"]} submitted a {priority}-priority request for {prop["title"]}.',
        "/accommodation/landlord/maintenance"
    )
    return jsonify({"success": True, "request_id": rid})


@accommodation_bp.route("/landlord/maintenance")
@landlord_required
def landlord_maintenance():
    lid = session["user_id"]
    status_filter = request.args.get("status", "").strip()
    filters = ["p.landlord_id=?"]
    params  = [lid]
    if status_filter:
        filters.append("mr.status=?")
        params.append(status_filter)
    with get_db() as conn:
        requests_ = conn.execute(f"""
            SELECT mr.*, p.title as property_title, u.full_name as tenant_name, u.phone as tenant_phone
            FROM maintenance_requests mr
            JOIN properties p ON mr.property_id=p.id
            JOIN users u ON mr.tenant_id=u.id
            WHERE {' AND '.join(filters)}
            ORDER BY CASE mr.priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 WHEN 'normal' THEN 3 ELSE 4 END,
                     mr.created_at DESC
        """, params).fetchall()
    return render_template("accommodation/landlord_maintenance.html",
                           requests=[dict(r) for r in requests_],
                           status_filter=status_filter,
                           user_name=session.get("user_name"),
                           user_role=session.get("user_role"),
                           user_email=session.get("user_email"),
                           unread_count=get_unread_count(lid))


@accommodation_bp.route("/landlord/maintenance/<int:rid>/update", methods=["POST"])
@landlord_required
def maintenance_update(rid):
    lid  = session["user_id"]
    data = request.get_json() or {}
    new_status = (data.get("status") or "").strip().lower()
    notes      = (data.get("notes") or "").strip()

    if new_status not in ("open", "in_progress", "resolved", "closed"):
        return jsonify({"error": "Invalid status"}), 400

    with get_db() as conn:
        req = conn.execute("""
            SELECT mr.*, p.title as property_title
            FROM maintenance_requests mr JOIN properties p ON mr.property_id=p.id
            WHERE mr.id=? AND p.landlord_id=?
        """, (rid, lid)).fetchone()
        if not req:
            return jsonify({"error": "Request not found"}), 404
        conn.execute(
            "UPDATE maintenance_requests SET status=?, landlord_notes=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (new_status, notes, rid)
        )
        conn.commit()

    status_labels = {"in_progress": "In Progress", "resolved": "Resolved", "closed": "Closed", "open": "Reopened"}
    _notify(
        req["tenant_id"], "maintenance_update",
        f'Maintenance update: {req["title"]}',
        f'Your request has been marked as {status_labels.get(new_status, new_status)}. {notes}'.strip(),
        "/accommodation/tenant/maintenance"
    )
    return jsonify({"success": True})


@accommodation_bp.route("/tenant/maintenance")
@login_required
def tenant_maintenance():
    uid  = session["user_id"]
    if session.get("user_role") != "student":
        return redirect(url_for("accommodation.dashboard"))
    with get_db() as conn:
        requests_ = conn.execute("""
            SELECT mr.*, p.title as property_title
            FROM maintenance_requests mr JOIN properties p ON mr.property_id=p.id
            WHERE mr.tenant_id=?
            ORDER BY mr.created_at DESC
        """, (uid,)).fetchall()
    return render_template("accommodation/tenant_maintenance.html",
                           requests=[dict(r) for r in requests_],
                           user_name=session.get("user_name"),
                           user_role=session.get("user_role"),
                           user_email=session.get("user_email"),
                           unread_count=get_unread_count(uid))


# ── Saved / Favourite Properties ───────────────────────────────────────────────

@accommodation_bp.route("/api/properties/<int:pid>/save", methods=["POST"])
@login_required
def api_toggle_save_property(pid):
    uid  = session["user_id"]
    if session.get("user_role") != "student":
        return jsonify({"error": "Only tenants can save properties"}), 403
    with get_db() as conn:
        existing = conn.execute(
            "SELECT 1 FROM saved_properties WHERE tenant_id=? AND property_id=?", (uid, pid)
        ).fetchone()
        if existing:
            conn.execute("DELETE FROM saved_properties WHERE tenant_id=? AND property_id=?", (uid, pid))
            saved = False
        else:
            if not conn.execute("SELECT id FROM properties WHERE id=? AND is_active=1", (pid,)).fetchone():
                return jsonify({"error": "Property not found"}), 404
            conn.execute("INSERT INTO saved_properties (tenant_id, property_id) VALUES (?,?)", (uid, pid))
            saved = True
        conn.commit()
    return jsonify({"success": True, "saved": saved})


@accommodation_bp.route("/api/saved-properties")
@login_required
def api_saved_properties():
    uid  = session["user_id"]
    if session.get("user_role") != "student":
        return jsonify({"error": "Only tenants can view saved properties"}), 403
    with get_db() as conn:
        props = conn.execute("""
            SELECT p.*, u.full_name as landlord_name, u.is_verified as landlord_verified,
                   COALESCE(AVG(r.rating),0) as avg_rating, COUNT(r.id) as review_count,
                   sp.saved_at
            FROM saved_properties sp
            JOIN properties p ON sp.property_id=p.id
            JOIN users u ON p.landlord_id=u.id
            LEFT JOIN reviews r ON r.property_id=p.id
            WHERE sp.tenant_id=? AND p.is_active=1
            GROUP BY p.id, u.full_name, u.is_verified, sp.saved_at
            ORDER BY sp.saved_at DESC
        """, (uid,)).fetchall()
        prop_list = []
        for p in props:
            d = {**dict(p), "services": json.loads(p["services"] or "[]")}
            cover = conn.execute(
                "SELECT filename FROM property_images WHERE property_id=? AND is_primary=1 LIMIT 1",
                (p["id"],)
            ).fetchone()
            d["cover_image"] = cover["filename"] if cover else None
            prop_list.append(d)
    return jsonify(prop_list)


@accommodation_bp.route("/saved-properties")
@login_required
def saved_properties_page():
    uid  = session["user_id"]
    if session.get("user_role") != "student":
        return redirect(url_for("accommodation.dashboard"))
    with get_db() as conn:
        props = conn.execute("""
            SELECT p.*, u.full_name as landlord_name, u.is_verified as landlord_verified,
                   COALESCE(AVG(r.rating),0) as avg_rating, COUNT(r.id) as review_count
            FROM saved_properties sp
            JOIN properties p ON sp.property_id=p.id
            JOIN users u ON p.landlord_id=u.id
            LEFT JOIN reviews r ON r.property_id=p.id
            WHERE sp.tenant_id=? AND p.is_active=1
            GROUP BY p.id, u.full_name, u.is_verified, sp.saved_at ORDER BY sp.saved_at DESC
        """, (uid,)).fetchall()
        prop_list = []
        for p in props:
            d = {**dict(p), "services": json.loads(p["services"] or "[]")}
            cover = conn.execute(
                "SELECT filename FROM property_images WHERE property_id=? AND is_primary=1 LIMIT 1",
                (p["id"],)
            ).fetchone()
            d["cover_image"] = cover["filename"] if cover else None
            prop_list.append(d)
    return render_template("accommodation/saved_properties.html",
                           properties=prop_list,
                           user_name=session.get("user_name"),
                           user_role=session.get("user_role"),
                           user_email=session.get("user_email"),
                           unread_count=get_unread_count(uid))


# ── Admin routes ──────────────────────────────────────────────────────────────

def _admin_common():
    return dict(user_name=session.get("user_name"), user_role=session.get("user_role"),
                unread_count=get_unread_count(session["user_id"]))


@accommodation_bp.route("/admin/settings", methods=["GET", "POST"])
@admin_required
def admin_settings():
    if request.method == "POST":
        data = request.get_json() or {}
        rate = data.get("commission_rate")
        try:
            rate = float(rate)
            if not (0 <= rate <= 100):
                return jsonify({"error": "Rate must be between 0 and 100"}), 400
            rate = round(rate, 2)
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid rate value"}), 400
        with get_db() as conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES ('commission_rate', ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (str(rate),)
            )
            conn.commit()
        socketio.emit("commission_rate_changed", {"rate": rate})
        return jsonify({"success": True, "commission_rate": rate})

    with get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='commission_rate'").fetchone()
    current_rate = float(row["value"]) if row else 5.0
    return jsonify({"commission_rate": current_rate})


@accommodation_bp.route("/admin/test-email")
@admin_required
def admin_test_email():
    to = request.args.get("to") or session.get("user_email")
    ok = _send_email(to, "T-Tech Connect — Email Test",
                     f"<p>Test email from T-Tech Connect. Email is working correctly.</p><p>Sent to: {to}</p>")
    if ok:
        return jsonify({"success": True, "message": f"Test email sent to {to}"})
    return jsonify({"success": False, "error": "Check SENDGRID_API_KEY env var or Render logs"}), 500


@accommodation_bp.route("/admin")
@admin_required
def admin_dashboard():
    with get_db() as conn:
        stats = conn.execute("""
            SELECT
              (SELECT COUNT(*) FROM users WHERE is_active=1)                             AS total_users,
              (SELECT COUNT(*) FROM users WHERE role='student'  AND is_active=1)         AS students,
              (SELECT COUNT(*) FROM users WHERE role='landlord' AND is_active=1)         AS landlords,
              (SELECT COUNT(*) FROM properties WHERE is_active=1)                        AS total_props,
              (SELECT COUNT(*) FROM properties WHERE status='available' AND is_active=1) AS avail_props,
              (SELECT COALESCE(SUM(amount),0) FROM payments)                             AS total_revenue,
              (SELECT COUNT(*) FROM payments)                                            AS total_payments,
              (SELECT COALESCE(SUM(price_per_month),0) FROM properties WHERE is_active=1) AS total_monthly_rent
        """).fetchone()

        recent_users = conn.execute(
            "SELECT id,full_name,email,role,is_active,created_at FROM users ORDER BY created_at DESC LIMIT 6"
        ).fetchall()

        recent_props = conn.execute("""
            SELECT p.id,p.title,p.status,p.price_per_month,p.currency,p.created_at,
                   u.full_name AS landlord_name
            FROM properties p JOIN users u ON p.landlord_id=u.id
            WHERE p.is_active=1 ORDER BY p.created_at DESC LIMIT 6
        """).fetchall()

        recent_payments = conn.execute("""
            SELECT pay.amount,pay.currency,pay.reference,pay.paid_at,
                   u.full_name AS student_name, p.title AS property_title
            FROM payments pay
            JOIN users u ON pay.student_id=u.id
            JOIN properties p ON pay.property_id=p.id
            ORDER BY pay.paid_at DESC LIMIT 6
        """).fetchall()

    with get_db() as conn:
        rate_row = conn.execute("SELECT value FROM settings WHERE key='commission_rate'").fetchone()
    commission_rate = float(rate_row["value"]) if rate_row else 5.0
    estimated_revenue = round((stats["total_monthly_rent"] or 0) * commission_rate / 100, 2)

    return render_template("accommodation/admin_dashboard.html",
                           stats=stats,
                           recent_users=recent_users,
                           recent_props=recent_props,
                           recent_payments=recent_payments,
                           commission_rate=commission_rate,
                           estimated_revenue=estimated_revenue,
                           **_admin_common())


@accommodation_bp.route("/admin/users")
@admin_required
def admin_users():
    q           = request.args.get("q", "").strip()
    role_filter = request.args.get("role", "").strip()
    filters, params = [], []
    if q:
        filters.append("(full_name LIKE ? OR email LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    if role_filter:
        filters.append("role=?")
        params.append(role_filter)
    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    with get_db() as conn:
        users = conn.execute(
            f"SELECT id,full_name,email,role,is_active,is_verified,phone,created_at,last_login "
            f"FROM users {where} ORDER BY created_at DESC", params
        ).fetchall()
    return render_template("accommodation/admin_users.html", users=users,
                           q=q, role_filter=role_filter, **_admin_common())


@accommodation_bp.route("/admin/users/<int:uid>/toggle", methods=["POST"])
@admin_required
def admin_user_toggle(uid):
    if uid == session["user_id"]:
        return jsonify({"error": "You cannot deactivate your own account"}), 400
    with get_db() as conn:
        user = conn.execute("SELECT is_active FROM users WHERE id=?", (uid,)).fetchone()
        if not user:
            return jsonify({"error": "User not found"}), 404
        new = 0 if user["is_active"] else 1
        conn.execute("UPDATE users SET is_active=? WHERE id=?", (new, uid))
        conn.commit()
    return jsonify({"success": True, "is_active": new})


@accommodation_bp.route("/admin/users/<int:uid>/set-role", methods=["POST"])
@admin_required
def admin_user_set_role(uid):
    if uid == session["user_id"]:
        return jsonify({"error": "You cannot change your own role"}), 400
    role = (request.get_json() or {}).get("role", "")
    if role not in ("student", "landlord", "admin"):
        return jsonify({"error": "Invalid role"}), 400
    with get_db() as conn:
        if not conn.execute("SELECT id FROM users WHERE id=?", (uid,)).fetchone():
            return jsonify({"error": "User not found"}), 404
        conn.execute("UPDATE users SET role=? WHERE id=?", (role, uid))
        conn.commit()
    return jsonify({"success": True})


@accommodation_bp.route("/admin/users/<int:uid>/toggle-verified", methods=["POST"])
@admin_required
def admin_user_toggle_verified(uid):
    with get_db() as conn:
        user = conn.execute("SELECT is_verified, role FROM users WHERE id=?", (uid,)).fetchone()
        if not user:
            return jsonify({"error": "User not found"}), 404
        if user["role"] != "landlord":
            return jsonify({"error": "Only landlords can be verified"}), 400
        new = 0 if user["is_verified"] else 1
        conn.execute("UPDATE users SET is_verified=? WHERE id=?", (new, uid))
        conn.commit()
    return jsonify({"success": True, "is_verified": new})


@accommodation_bp.route("/admin/users/<int:uid>/delete", methods=["POST"])
@admin_required
def admin_user_delete(uid):
    if uid == session["user_id"]:
        return jsonify({"error": "You cannot delete your own account"}), 400
    with get_db() as conn:
        if not conn.execute("SELECT id FROM users WHERE id=?", (uid,)).fetchone():
            return jsonify({"error": "User not found"}), 404
        conn.execute("UPDATE users SET is_active=0 WHERE id=?", (uid,))
        conn.commit()
    return jsonify({"success": True})


@accommodation_bp.route("/admin/properties")
@admin_required
def admin_properties():
    q             = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "").strip()
    filters = ["p.is_active=1"]
    params  = []
    if q:
        filters.append("(p.title LIKE ? OR p.address LIKE ? OR u.full_name LIKE ?)")
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]
    if status_filter:
        filters.append("p.status=?")
        params.append(status_filter)
    with get_db() as conn:
        props = conn.execute(
            f"SELECT p.*,u.full_name AS landlord_name FROM properties p "
            f"JOIN users u ON p.landlord_id=u.id WHERE {' AND '.join(filters)} "
            f"ORDER BY p.created_at DESC", params
        ).fetchall()
    prop_list = [{**dict(p), "services": json.loads(p["services"] or "[]")} for p in props]
    return render_template("accommodation/admin_properties.html", properties=prop_list,
                           q=q, status_filter=status_filter, **_admin_common())


@accommodation_bp.route("/admin/property/<int:pid>/delete", methods=["POST"])
@admin_required
def admin_property_delete(pid):
    with get_db() as conn:
        conn.execute("UPDATE properties SET is_active=0 WHERE id=?", (pid,))
        conn.commit()
    if request.is_json:
        return jsonify({"success": True})
    flash("Property removed.", "success")
    return redirect(url_for("accommodation.admin_properties"))


@accommodation_bp.route("/admin/payments")
@admin_required
def admin_payments():
    with get_db() as conn:
        payments = conn.execute("""
            SELECT pay.id,pay.amount,pay.currency,pay.reference,pay.paid_at,
                   u.full_name AS student_name, u.email AS student_email,
                   p.title AS property_title, p.id AS property_id,
                   lu.full_name AS landlord_name
            FROM payments pay
            JOIN users u  ON pay.student_id=u.id
            JOIN properties p ON pay.property_id=p.id
            JOIN users lu ON p.landlord_id=lu.id
            ORDER BY pay.paid_at DESC
        """).fetchall()
        total_revenue = conn.execute(
            "SELECT COALESCE(SUM(amount),0) AS t FROM payments"
        ).fetchone()["t"]
    return render_template("accommodation/admin_payments.html", payments=payments,
                           total_revenue=total_revenue, **_admin_common())
