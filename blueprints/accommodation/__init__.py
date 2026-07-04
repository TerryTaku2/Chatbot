from flask import Blueprint
from flask_socketio import SocketIO
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

accommodation_bp = Blueprint(
    "accommodation",
    __name__,
    url_prefix="/accommodation",
    template_folder="templates",
    static_folder="static",
    static_url_path="/static",
)

# Deferred init (no `app=`) so app.py can call socketio.init_app(app)/limiter.init_app(app)
# after both this blueprint and the main Flask app exist, avoiding a circular import.
socketio = SocketIO(async_mode="threading", cors_allowed_origins="*")
limiter = Limiter(get_remote_address, default_limits=[])

from . import routes, sockets  # noqa: E402,F401  (registers routes/socket handlers on import)
