import os
import secrets

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _secret_key():
    """Use SECRET_KEY from the environment, otherwise persist a random one in instance/."""
    key = os.environ.get("SECRET_KEY")
    if key:
        return key
    path = os.path.join(BASE_DIR, "instance", "secret.key")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w") as fh:
            fh.write(secrets.token_hex(32))
    with open(path) as fh:
        return fh.read().strip()


class Config:
    SECRET_KEY = _secret_key()
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "instance", "school.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    JSON_SORT_KEYS = False

    SCHOOL_NAME = os.environ.get("SCHOOL_NAME", "Greenfield Academy")
    CURRENCY = os.environ.get("CURRENCY", "USD")
    # Highest class level; students in this level graduate on promotion.
    MAX_CLASS_LEVEL = int(os.environ.get("MAX_CLASS_LEVEL", "6"))
    # Minimum attendance % before a student is flagged as at-risk.
    ATTENDANCE_THRESHOLD = 85.0
    # Pass mark for an individual subject (percentage).
    PASS_MARK = 50.0
    # Failed login attempts allowed per username within LOGIN_WINDOW seconds.
    LOGIN_MAX_ATTEMPTS = 5
    LOGIN_WINDOW = 300

    # WhatsApp chatbot integration (see app/api/integration.py). The chatbot calls
    # /api/integration/* with this key as a Bearer token, and the same key signs the
    # notifications this app posts to CHATBOT_WEBHOOK_URL. Unset = integration off.
    CHATBOT_API_KEY = os.environ.get("CHATBOT_API_KEY", "")
    CHATBOT_WEBHOOK_URL = os.environ.get("CHATBOT_WEBHOOK_URL", "")
    # Country code assumed for guardian phones stored in local format (0771...).
    PHONE_COUNTRY_CODE = os.environ.get("PHONE_COUNTRY_CODE", "263")


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SECRET_KEY = "test"
    CHATBOT_API_KEY = "test-chatbot-key"
    CHATBOT_WEBHOOK_URL = ""
