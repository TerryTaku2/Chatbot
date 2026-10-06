import time
from collections import defaultdict, deque

from flask import Blueprint, current_app, jsonify
from flask_login import current_user, login_required, login_user, logout_user

from .. import db
from ..models import User, utcnow
from ..utils import ApiError, audit, body, require

bp = Blueprint("auth", __name__)

_failed = defaultdict(deque)  # username -> timestamps of recent failures


def _throttled(username):
    window = current_app.config["LOGIN_WINDOW"]
    q = _failed[username]
    now = time.time()
    while q and now - q[0] > window:
        q.popleft()
    return len(q) >= current_app.config["LOGIN_MAX_ATTEMPTS"]


def validate_password(pw):
    if len(pw) < 8 or pw.isalpha() or pw.isdigit():
        raise ApiError("Password must be at least 8 characters and mix letters with numbers or symbols",
                       fields={"password": "Too weak"})


@bp.post("/auth/login")
def login():
    data = body()
    require(data, "username", "password")
    username = str(data["username"]).strip().lower()
    if _throttled(username):
        raise ApiError("Too many failed attempts. Try again in a few minutes.", 429)
    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(str(data["password"])):
        _failed[username].append(time.time())
        raise ApiError("Invalid username or password", 401)
    if not user.active:
        raise ApiError("This account has been deactivated", 403)
    _failed.pop(username, None)
    login_user(user, remember=bool(data.get("remember")))
    user.last_login = utcnow()
    audit("login", "user", user.id)
    db.session.commit()
    return jsonify(user=user.to_dict())


@bp.post("/auth/logout")
@login_required
def logout():
    logout_user()
    return jsonify(ok=True)


@bp.get("/auth/me")
@login_required
def me():
    return jsonify(user=current_user.to_dict(),
                   school=current_app.config["SCHOOL_NAME"],
                   currency=current_app.config["CURRENCY"])


@bp.post("/auth/change-password")
@login_required
def change_password():
    data = body()
    require(data, "current_password", "new_password")
    if not current_user.check_password(data["current_password"]):
        raise ApiError("Current password is incorrect", fields={"current_password": "Incorrect"})
    validate_password(data["new_password"])
    current_user.set_password(data["new_password"])
    audit("password", "user", current_user.id)
    db.session.commit()
    return jsonify(ok=True)
