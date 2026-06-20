import os
import uuid
import json
import hmac
import hashlib
import time
import functools
import filetype
from collections import defaultdict
import requests
from flask import Flask, request, jsonify, render_template, send_from_directory, session, redirect
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
from db import (
    init_db,
    register_seller, get_seller, set_seller_status, get_pending_sellers,
    search_products, add_product, get_product_by_id, get_pending_products,
    get_products_by_category, get_seller_products,
    set_product_status, update_stock,
    create_vendor_token, validate_token, mark_token_used,
    get_session, set_session, clear_session,
    log_message, add_to_waitlist,
    get_waitlist_for_product, clear_waitlist_for_product,
    create_order, get_order, get_buyer_orders, get_seller_orders, update_order_status,
    log_property_enquiry, get_property_enquiries, update_enquiry_status,
    get_admin_stats, get_all_sellers_admin, get_all_products_admin,
    get_recent_orders_admin, get_all_user_phones, get_seller_phone_list,
    add_service, get_service, get_services_by_category, search_services,
    get_pending_services, get_provider_services, set_service_status,
    add_service_review, get_service_reviews, log_service_enquiry,
    get_service_enquiries,
    get_setting, set_setting,
    log_admin_action, check_and_record_hit, log_send, cleanup_expired_sessions,
    add_to_cart, remove_from_cart, get_cart, get_cart_total, clear_cart, update_cart_qty,
    create_dispute, get_disputes, update_dispute, get_buyer_disputes,
    newsletter_subscribe, newsletter_unsubscribe, is_subscribed, get_newsletter_phones,
    log_social_post, get_analytics_summary, get_seller_trust_score,
    get_audit_log,
    add_product_review, get_product_reviews, get_product_avg_rating,
    get_fulfilled_orders_for_buyer,
    register_delivery_person, get_delivery_person, get_pending_delivery_personnel,
    get_approved_delivery_personnel, set_delivery_person_status, get_delivery_orders,
)

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-in-production")
init_db()

# Clean up stale sessions on startup
cleanup_expired_sessions(max_age_minutes=60)

VERIFY_TOKEN        = os.getenv("VERIFY_TOKEN", "my_secure_token_0304")
WHATSAPP_TOKEN      = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "")
PHONE_NUMBER_ID     = os.getenv("PHONE_NUMBER_ID")
BASE_URL            = os.getenv("BASE_URL", "http://localhost:5000")
ADMIN_PHONE         = os.getenv("ADMIN_PHONE", "")
TTECH_CONNECT_URL       = os.getenv("TTECH_CONNECT_URL", "http://localhost:8000")
UPLOAD_FOLDER           = os.path.join(os.path.dirname(__file__), "static", "uploads")
ALLOWED_EXT             = {"jpg", "jpeg", "png", "webp"}
MAX_IMAGE_BYTES         = 5 * 1024 * 1024   # 5 MB
FACEBOOK_PAGE_TOKEN     = os.getenv("FACEBOOK_PAGE_TOKEN", "")
FACEBOOK_PAGE_ID        = os.getenv("FACEBOOK_PAGE_ID", "")
PAYNOW_INTEGRATION_ID   = os.getenv("PAYNOW_INTEGRATION_ID", "")
PAYNOW_INTEGRATION_KEY  = os.getenv("PAYNOW_INTEGRATION_KEY", "")
WA_BUSINESS_NUMBER      = os.getenv("WHATSAPP_BUSINESS_NUMBER", ADMIN_PHONE)

ZIM_CITIES = [
    "Harare", "Bulawayo", "Mutare", "Gweru",
    "Masvingo", "Chinhoyi", "Victoria Falls",
]

VENDOR_NUMBERS = set(
    n.strip() for n in os.getenv("VENDOR_NUMBERS", "").split(",") if n.strip()
)

_seen_message_ids: set = set()
RATE_LIMIT_MAX    = 20
RATE_LIMIT_WINDOW = 60

CATEGORIES = [
    "Laptops & Desktops",
    "Networking Equipment",
    "CCTV & Security Systems",
    "Printers & Accessories",
    "Software Licenses",
    "IT Services",
]

NUM_EMOJI = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]

GREETING_WORDS = {
    "hello", "hi", "hey", "hie", "good morning", "good afternoon",
    "good evening", "howdy", "greetings", "sup", "yo", "start", "help",
}

# ── Message templates ─────────────────────────────────────────────────────────

SERVICE_CATEGORIES = [
    ("🏠", "Home Services"),
    ("🔨", "Construction & Building"),
    ("💻", "IT & Technology"),
    ("🚗", "Automotive"),
    ("🎓", "Education & Tutoring"),
    ("🍳", "Catering & Food"),
    ("✂️", "Beauty & Personal Care"),
    ("📦", "Delivery & Moving"),
]

SERVICE_PRICE_TYPES = ["Hourly rate", "Fixed price", "Get a quote"]

WELCOME = (
    "👋 Welcome to *T-Tech Connect!*\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "Your all-in-one digital marketplace 🇿🇼\n\n"
    "Please select an option:\n\n"
    "1️⃣  — 🛒 *Buy* a product\n"
    "2️⃣  — 🔧 *Find* a service\n"
    "3️⃣  — 💼 *Sell* / offer a service\n"
    "4️⃣  — 🏠 Find *Accommodation*\n"
    "5️⃣  — 📬 *Contact* T-Tech Connect\n\n"
    "_Reply with *1–5* to select_"
)

ACCOMMODATION_MENU = (
    "🏠 *Find Accommodation*\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "1️⃣  — Search properties\n"
    "2️⃣  — Browse by city\n"
    "3️⃣  — Student-friendly only\n"
    "4️⃣  — All available properties\n\n"
    "_Reply *1–4* to select | *0* for main menu_"
)

CITIES_MENU = (
    "📍 *Select a City:*\n\n"
    "1️⃣  — Harare\n"
    "2️⃣  — Bulawayo\n"
    "3️⃣  — Mutare\n"
    "4️⃣  — Gweru\n"
    "5️⃣  — Masvingo\n"
    "6️⃣  — Chinhoyi\n"
    "7️⃣  — Victoria Falls\n\n"
    "_Reply *1–7* to browse | *0* to go back_"
)

BUYER_MENU = (
    "🛒 *Buyer Menu*\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "1️⃣  — Browse by category\n"
    "2️⃣  — Our services\n"
    "3️⃣  — Search for a product\n"
    "4️⃣  — Request a quote\n"
    "5️⃣  — My orders\n\n"
    "_Reply *1–5* to select | *0* for main menu_"
)

SELLER_MENU = (
    "💼 *Sell / Offer Services*\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "1️⃣  — 📝 *Register* as a seller\n"
    "2️⃣  — 📦 List a *product* (physical item)\n"
    "3️⃣  — 🔧 Offer a *service*\n"
    "4️⃣  — 📋 My listings & services\n"
    "5️⃣  — 🛒 My orders & bookings\n\n"
    "💰 10% commission on approved listings\n\n"
    "_Reply *1–5* | *0* for main menu_"
)

FIND_SERVICE_MENU = (
    "🔧 *Find a Service*\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "1️⃣  — Browse by category\n"
    "2️⃣  — Search by keyword\n\n"
    "_Reply *1* or *2* | *0* for main menu_"
)

SERVICE_CATS_MENU = (
    "🔧 *Browse by Service Category:*\n\n"
    "1️⃣  — 🏠 Home Services\n"
    "2️⃣  — 🔨 Construction & Building\n"
    "3️⃣  — 💻 IT & Technology\n"
    "4️⃣  — 🚗 Automotive\n"
    "5️⃣  — 🎓 Education & Tutoring\n"
    "6️⃣  — 🍳 Catering & Food\n"
    "7️⃣  — ✂️ Beauty & Personal Care\n"
    "8️⃣  — 📦 Delivery & Moving\n\n"
    "_Reply *1–8* to browse | *0* to go back_"
)

CATEGORIES_MENU = (
    "🖥️ *Browse by Category:*\n\n"
    "1️⃣  — Laptops & Desktops\n"
    "2️⃣  — Networking Equipment\n"
    "3️⃣  — CCTV & Security Systems\n"
    "4️⃣  — Printers & Accessories\n"
    "5️⃣  — Software Licenses\n"
    "6️⃣  — IT Services\n\n"
    "_Reply *1–6* to browse | *0* to go back_"
)

SERVICES_RESPONSE = (
    "🛠️ *Our Services:*\n\n"
    "1. IT Support & Maintenance\n"
    "2. Network Setup & Configuration\n"
    "3. CCTV Installation\n"
    "4. Data Recovery\n"
    "5. Website & App Development\n"
    "6. Software Licensing & Setup\n\n"
    "Reply *quote* to get a service estimate.\n\n"
    "_Reply *0* to go back._"
)

def get_contact_response():
    """Build contact message dynamically from settings so it's always current."""
    return (
        "📬 *Contact T-Tech Connect:*\n\n"
        f"📞 Phone   : {get_setting('contact_phone', '+263 77 412 8219')}\n"
        f"📧 Email   : {get_setting('contact_email', 'terrencemuromba@gmail.com')}\n"
        f"🌐 Website : {get_setting('contact_website', 'https://t-techsolutions.co.zw')}\n"
        f"📍 Location: {get_setting('contact_location', 'Harare, Zimbabwe')}\n\n"
        "_Reply *0* for the main menu._"
    )

CONTACT_RESPONSE = get_contact_response   # callable — called at runtime

DEFAULT_RESPONSE = "❓ Sorry, I didn't understand that.\n\n" + WELCOME


# ── WhatsApp API ──────────────────────────────────────────────────────────────

def send_whatsapp_message(to, message):
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message},
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        data     = response.json()
        if response.status_code not in (200, 201) or "error" in data:
            error_msg = str(data.get("error", {}).get("message", response.text))
            log_send(to, message, status="failed", error=error_msg)
            print(f"[SEND FAIL] to={to} status={response.status_code} err={error_msg}")
        else:
            log_send(to, message, status="sent")
        return data
    except Exception as e:
        log_send(to, message, status="error", error=str(e))
        print(f"[SEND ERROR] to={to} exception={e}")
        return {}


def send_whatsapp_image(to, image_url, caption=""):
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": {"link": image_url, "caption": caption},
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        data = response.json()
        if response.status_code not in (200, 201) or "error" in data:
            print(f"[IMG FAIL] to={to} err={data.get('error', {}).get('message', response.text)}")
        return data
    except Exception as e:
        print(f"[IMG ERROR] to={to} exception={e}")
        return {}


def mark_message_read(message_id):
    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    requests.post(url, headers=headers, json={
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    })


def notify_admin(message):
    if ADMIN_PHONE:
        send_whatsapp_message(ADMIN_PHONE, message)


def notify_waitlist(product_id, product_name):
    for phone in get_waitlist_for_product(product_id):
        send_whatsapp_message(
            phone,
            f"✅ Good news! *{product_name}* is back in stock at T-Tech Connect.\n\n"
            f"Reply *0* then search for it to order now.",
        )
    clear_waitlist_for_product(product_id)


# ── Rate limiting (DB-backed, survives restarts) ──────────────────────────────

def is_rate_limited(phone):
    return check_and_record_hit(phone, window_secs=RATE_LIMIT_WINDOW, max_hits=RATE_LIMIT_MAX)


# ── Webhook HMAC signature validation ────────────────────────────────────────

def verify_webhook_signature(req) -> bool:
    """Validate Meta's X-Hub-Signature-256 header to prevent spoofed webhooks."""
    if not WHATSAPP_APP_SECRET:
        return True   # skip if not configured (dev mode)
    signature = req.headers.get("X-Hub-Signature-256", "")
    if not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        WHATSAPP_APP_SECRET.encode(),
        req.get_data(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


# ── Image helpers ─────────────────────────────────────────────────────────────

def save_image(file_obj):
    if not file_obj or file_obj.filename == "":
        return None
    # Read into memory first so we can check size and type
    data = file_obj.read()
    if len(data) > MAX_IMAGE_BYTES:
        return None
    # Detect actual file type from magic bytes (not the extension)
    kind = filetype.guess(data)
    if kind is None or kind.extension not in ALLOWED_EXT:
        return None
    filename = f"{uuid.uuid4().hex}.{kind.extension}"
    path     = os.path.join(UPLOAD_FOLDER, filename)
    with open(path, "wb") as f:
        f.write(data)
    return filename


# ── Context-setting helpers ───────────────────────────────────────────────────

def go_welcome(phone):
    clear_session(phone)
    return WELCOME

def go_buyer_menu(phone):
    set_session(phone, "ctx_buyer")
    return BUYER_MENU

def go_seller_menu(phone):
    set_session(phone, "ctx_seller")
    return SELLER_MENU

def go_categories(phone):
    set_session(phone, "ctx_categories")
    return CATEGORIES_MENU

def go_accommodation_menu(phone):
    set_session(phone, "ctx_accommodation")
    return ACCOMMODATION_MENU

def go_find_service_menu(phone):
    set_session(phone, "ctx_find_service")
    return FIND_SERVICE_MENU


# ── Formatters ────────────────────────────────────────────────────────────────

def _to_dict(row):
    """Safely convert sqlite3.Row or dict to a plain dict."""
    if isinstance(row, dict):
        return row
    return dict(row)


def format_numbered_products(results, title="🔍 *Results:*"):
    """Show up to 5 products numbered for easy selection."""
    if not results:
        return "😕 No products found.\n\n_Reply *0* to go back._"
    lines = [f"{title}\n"]
    for i, raw in enumerate(results[:5]):
        row      = _to_dict(raw)
        in_stock = row.get("stock_qty", 0) > 0
        status   = "✅ In Stock" if in_stock else "❌ Out of Stock"
        desc     = row.get("description") or ""
        short    = (desc[:60] + "…") if len(desc) > 60 else desc
        photo    = "  📷 Photo" if row.get("image_path") else ""
        lines.append(
            f"{NUM_EMOJI[i]}  *{row['name']}*\n"
            f"    💰 ${row['price']:.2f}  |  {status}{photo}\n"
            + (f"    _{short}_\n" if short else "")
        )
    lines.append("\n_Reply with a number to select | *0* to go back_")
    return "\n".join(lines)


def format_buyer_orders(orders):
    if not orders:
        return (
            "📭 You have no orders yet.\n\n"
            "_Reply *0* to go back._"
        )
    lines = ["📦 *Your Orders:*\n"]
    for o in orders:
        lines.append(
            f"Ref    : *{o['reference']}*\n"
            f"Item   : {o['name']}\n"
            f"Qty    : {o['quantity']}  |  Total: ${o['total_price']:.2f}\n"
            f"Status : {o['status'].title()}\n"
            "─────────────────"
        )
    lines.append("_Reply *0* to go back._")
    return "\n".join(lines)


def format_seller_listings(products):
    if not products:
        return (
            "📭 You have no listings yet.\n\n"
            "Reply *2* to list your first product.\n\n"
            "_Reply *0* to go back._"
        )
    lines = [f"📋 *Your Listings ({len(products)}):*\n"]
    for p in products:
        icon = {"approved": "✅", "pending": "⏳", "rejected": "❌"}.get(p["status"], "❓")
        lines.append(
            f"{icon} *{p['name']}*  (ID: {p['id']})\n"
            f"    💰 ${p['price']:.2f}  |  Stock: {p['stock_qty']}\n"
            f"    Status: {p['status'].title()}\n"
            "─────────────────"
        )
    lines.append("_Reply *0* to go back._")
    return "\n".join(lines)


def format_seller_orders(orders):
    if not orders:
        return "📭 No orders on your products yet.\n\n_Reply *0* to go back._"
    lines = ["🛒 *Orders on Your Products:*\n"]
    for o in orders:
        lines.append(
            f"Ref    : *{o['reference']}*\n"
            f"Item   : {o['name']}  |  Qty: {o['quantity']}\n"
            f"Revenue: ${o['total_price']:.2f}  |  Buyer: {o['buyer_phone']}\n"
            f"Status : {o['status'].title()}\n"
            "─────────────────"
        )
    lines.append("_Reply *0* to go back._")
    return "\n".join(lines)


# ── NLP intent detection ─────────────────────────────────────────────────────

INTENT_PATTERNS = {
    "Home Services":           ["leaking", "plumb", "electric", "paint", "clean", "roof", "pipe", "tap", "geyser", "drain", "tile", "ceiling"],
    "Construction & Building": ["build", "construct", "renovat", "brick", "cement", "wall", "floor", "house", "extension", "slab"],
    "IT & Technology":         ["computer", "laptop", "network", "wifi", "cctv", "software", "website", "virus", "hack", "printer", "server"],
    "Automotive":              ["car", "vehicle", "mechanic", "tyre", "engine", "brake", "service car", "panel beat", "weld"],
    "Education & Tutoring":    ["tutor", "teach", "lesson", "math", "science", "homework", "exam", "school", "college"],
    "Catering & Food":         ["food", "cater", "cook", "chef", "event", "wedding", "birthday", "party", "meal"],
    "Beauty & Personal Care":  ["hair", "nail", "makeup", "salon", "beauty", "barber", "weave", "braids", "lash"],
    "Delivery & Moving":       ["deliver", "move", "transport", "courier", "ship", "relocat", "removals"],
}

def detect_service_intent(text):
    """Return the most likely service category from free-text or None."""
    t      = text.lower()
    scores = {}
    for category, keywords in INTENT_PATTERNS.items():
        score = sum(1 for kw in keywords if kw in t)
        if score:
            scores[category] = score
    if not scores:
        return None
    return max(scores, key=scores.get)


# ── Facebook Graph API auto-poster ────────────────────────────────────────────

def post_to_facebook(message, image_url=None):
    """Post to the Facebook Page. Returns post_id or None."""
    if not FACEBOOK_PAGE_TOKEN or not FACEBOOK_PAGE_ID:
        return None
    if get_setting("auto_post_facebook", "0") != "1":
        return None
    try:
        if image_url:
            resp = requests.post(
                f"https://graph.facebook.com/v19.0/{FACEBOOK_PAGE_ID}/photos",
                data={"url": image_url, "caption": message, "access_token": FACEBOOK_PAGE_TOKEN},
                timeout=10,
            )
        else:
            resp = requests.post(
                f"https://graph.facebook.com/v19.0/{FACEBOOK_PAGE_ID}/feed",
                data={"message": message, "access_token": FACEBOOK_PAGE_TOKEN},
                timeout=10,
            )
        data = resp.json()
        return data.get("id") or data.get("post_id")
    except Exception as e:
        print(f"[FB ERROR] {e}")
        return None


def auto_post_product(product):
    """Auto-post an approved product to Facebook."""
    wa_link = f"https://wa.me/{WA_BUSINESS_NUMBER}?text=search+{product['name'].replace(' ', '+')}"
    msg = (
        f"🆕 *{product['name']}*\n"
        f"📦 {product['category']}\n"
        f"💰 ${product['price']:.2f}\n\n"
        f"{product.get('description', '')}\n\n"
        f"🛒 Order on WhatsApp: {wa_link}\n"
        f"#TechConnect #Zimbabwe #ShopOnline"
    )
    image_url = f"{BASE_URL}/uploads/{product['image_path']}" if product.get("image_path") else None
    post_id   = post_to_facebook(msg, image_url)
    if post_id:
        log_social_post("facebook", post_id, product_id=product["id"])
    return post_id


def auto_post_service(service):
    """Auto-post an approved service to Facebook."""
    wa_link = f"https://wa.me/{WA_BUSINESS_NUMBER}?text=find+{service['title'].replace(' ', '+')}"
    msg = (
        f"🔧 *{service['title']}*\n"
        f"📦 {service['category']}\n"
        f"💰 {_price_label(service)}\n"
        f"📍 {service.get('service_area', 'Zimbabwe')}\n\n"
        f"{service.get('description', '')}\n\n"
        f"📩 Enquire on WhatsApp: {wa_link}\n"
        f"#Services #Zimbabwe #TechConnect"
    )
    post_id = post_to_facebook(msg)
    if post_id:
        log_social_post("facebook", post_id, service_id=service["id"])
    return post_id


# ── Paynow / EcoCash payment ──────────────────────────────────────────────────

def initiate_ecocash_payment(phone_number, amount, reference, buyer_email="buyer@ttech.co.zw"):
    """Initiate EcoCash payment via Paynow. Returns dict with success/poll_url."""
    if not PAYNOW_INTEGRATION_ID or not PAYNOW_INTEGRATION_KEY:
        return {"success": False, "error": "Payment gateway not configured."}
    try:
        from paynow import Paynow
        pn = Paynow(
            PAYNOW_INTEGRATION_ID,
            PAYNOW_INTEGRATION_KEY,
            f"{BASE_URL}/paynow/result",
            "",
        )
        payment = pn.create_payment(reference, buyer_email)
        payment.add(f"T-Tech Connect Order {reference}", amount)
        # Normalize phone: 07x → 07x (Paynow wants local format)
        local_phone = phone_number.lstrip("+")
        if local_phone.startswith("263"):
            local_phone = "0" + local_phone[3:]
        response = pn.send_mobile(payment, local_phone, "ecocash")
        if response.success:
            return {"success": True, "poll_url": response.poll_url, "reference": reference}
        return {"success": False, "error": str(getattr(response, "errors", "Payment failed"))}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Cart formatters ───────────────────────────────────────────────────────────

def format_cart(items):
    if not items:
        return (
            "🛒 *Your Cart is Empty*\n\n"
            "Browse products and use *add <number>* to add items.\n\n"
            "_Reply *0* for the main menu._"
        )
    lines = ["🛒 *Your Cart:*\n"]
    total = 0
    for i, item in enumerate(items):
        subtotal = item["price"] * item["quantity"]
        total   += subtotal
        lines.append(
            f"{NUM_EMOJI[i]}  *{item['name']}*\n"
            f"    💰 ${item['price']:.2f} × {item['quantity']} = *${subtotal:.2f}*\n"
        )
    lines.append(
        f"\n━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🧾 *Total: ${total:.2f}*\n\n"
        f"1️⃣  — ✅ Checkout\n"
        f"2️⃣  — 🗑️ Clear cart\n"
        f"3️⃣  — ➖ Remove an item\n"
        f"0️⃣  — Continue shopping"
    )
    return "\n".join(lines)


# ── Service formatters ────────────────────────────────────────────────────────

def _price_label(svc):
    pt = svc.get("price_type", "quoted")
    p  = svc.get("price", 0)
    if pt == "hourly":
        return f"${p:.0f}/hr"
    if pt == "fixed":
        return f"${p:.0f} fixed"
    return "Get a quote"


def _star_str(rating, count):
    if not count:
        return "⭐ No reviews yet"
    stars = "⭐" * int(round(rating))
    return f"{stars} {rating:.1f} ({count} review{'s' if count != 1 else ''})"


def format_service_list(services, title="🔧 *Services Found:*"):
    if not services:
        return "😕 No services found.\n\n_Reply *0* to go back._"
    lines = [f"{title} ({len(services)} found)\n"]
    for i, s in enumerate(services[:8]):
        lines.append(
            f"{NUM_EMOJI[i]}  *{s['title']}*\n"
            f"    {_star_str(s.get('avg_rating',0), s.get('review_count',0))}\n"
            f"    💰 {_price_label(s)}  |  📍 {s.get('service_area','Zimbabwe')}\n"
        )
    lines.append("\n_Reply with a number to view details | *0* to go back_")
    return "\n".join(lines)


def format_service_detail(s, reviews):
    review_lines = []
    for r in reviews:
        stars   = "⭐" * r["rating"]
        comment = r["comment"] or "No comment"
        review_lines.append(f"  {stars} _{comment}_")
    reviews_block = "\n".join(review_lines) if review_lines else "  _No reviews yet — be the first!_"

    return (
        f"🔧 *{s['title']}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 Category : {s['category']}\n"
        f"💰 Pricing  : {_price_label(s)}\n"
        f"📍 Area     : {s.get('service_area','Zimbabwe')}\n"
        f"🏢 Provider : {s.get('provider_business') or s.get('provider_name','N/A')}\n"
        f"{_star_str(s.get('avg_rating',0), s.get('review_count',0))}\n\n"
        f"📝 _{s.get('description','No description provided.')}_\n\n"
        f"💬 *Recent Reviews:*\n{reviews_block}\n\n"
        f"1️⃣  — 📩 Enquire about this service\n"
        f"2️⃣  — ⭐ Leave a review\n"
        f"0️⃣  — Back to results"
    )


# ── Accommodation: API caller & formatters ────────────────────────────────────

def fetch_properties(city=None, student_friendly=False, search=None, status="available"):
    """Call T-Tech Connect1 public API. Returns list or None on connection error.
    Retries once — Render free tier can take up to 30s to wake from sleep."""
    params = {"status": status}
    if city:
        params["city"] = city

    for attempt in range(2):
        try:
            resp = requests.get(
                f"{TTECH_CONNECT_URL}/api/properties",
                params=params,
                timeout=30,   # generous — Render cold-start can be ~20-30s
            )
            if resp.status_code != 200:
                return None
            props = resp.json()
            if student_friendly:
                props = [p for p in props if p.get("student_friendly")]
            if search:
                kw = search.lower()
                props = [
                    p for p in props
                    if kw in (
                        p.get("title", "") + " " +
                        p.get("description", "") + " " +
                        p.get("address", "") + " " +
                        p.get("city", "")
                    ).lower()
                ]
            return props
        except Exception:
            if attempt == 1:
                return None   # both attempts failed
    return None


def format_property_list(props, title="🏠 *Available Properties:*"):
    """Numbered list of up to 5 properties."""
    if props is None:
        return (
            "⚠️ Could not reach the accommodation service right now.\n\n"
            "Please try again shortly or reply *4* to contact us directly.\n\n"
            "_Reply *0* to go back._"
        )
    if not props:
        return (
            "😕 No properties found matching your search.\n\n"
            "Try a different keyword or city.\n\n"
            "_Reply *0* to go back._"
        )
    lines = [f"{title} ({len(props)} found)\n"]
    for i, p in enumerate(props[:5]):
        rooms = p.get("available_rooms", 0)
        price = p.get("price_per_month", 0)
        city  = p.get("city", "")
        sf    = "🎓 Student-friendly  " if p.get("student_friendly") else ""
        lines.append(
            f"{NUM_EMOJI[i]}  *{p['title']}*\n"
            f"    📍 {city}\n"
            f"    💰 ${price:.2f}/month  |  🛏️ {rooms} room(s) available\n"
            f"    {sf}"
        )
    lines.append("\n_Reply *1–5* to view details | *0* to go back_")
    return "\n".join(lines)


def format_property_detail(p):
    """Full detail card for a single property."""
    services = p.get("services", [])
    if isinstance(services, str):
        try:
            services = json.loads(services)
        except Exception:
            services = []
    svc_str   = ", ".join(s.title() for s in services) if services else "Not listed"
    sf        = "✅ Yes" if p.get("student_friendly") else "❌ No"
    shared    = "Yes" if p.get("is_shared") else "No"
    price     = p.get("price_per_month", 0)
    accom_rate = float(get_setting("accommodation_commission_rate", "5")) / 100
    commission = round(price * accom_rate, 2)
    desc      = (p.get("description") or "")[:200]
    rooms     = p.get("available_rooms", 0)
    bathrooms = p.get("bathrooms", 1)
    web_link  = f"{TTECH_CONNECT_URL}/landlord/property/{p['id']}"

    return (
        f"🏠 *{p['title']}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📍 {p.get('address', '')} , {p.get('city', '')}\n"
        f"💰 ${price:.2f}/month  |  🛏️ {rooms} room(s)  |  🚿 {bathrooms} bath\n"
        f"👥 Shared: {shared}  |  🎓 Student-friendly: {sf}\n"
        f"🔧 Services: {svc_str}\n\n"
        f"📝 {desc}\n\n"
        f"💸 *Viewing commission: ${commission:.2f}* (5% of rent)\n\n"
        f"1️⃣  — Enquire about this property\n"
        f"2️⃣  — View full listing on web\n"
        f"0️⃣  — Back to results\n\n"
        f"_Link: {web_link}_"
    )


# ── Session handler ───────────────────────────────────────────────────────────

def handle_session(phone, msg_text, session):
    state = session["state"]
    data  = json.loads(session["data"] or "{}")

    # "0" = go back one level
    if msg_text == "0":
        if state in ("ctx_buyer", "ctx_categories", "ctx_search", "ctx_results"):
            return go_buyer_menu(phone)
        if state == "ctx_seller":
            return go_welcome(phone)
        if state in ("ctx_accommodation", "ctx_city_select",
                     "ctx_prop_search", "ctx_prop_results"):
            return go_accommodation_menu(phone)
        if state == "ctx_prop_detail":
            # Go back to the property list stored in session
            props = data.get("props", [])
            if props:
                set_session(phone, "ctx_prop_results", {"props": props})
                return format_property_list(props, title="🏠 *Properties:*")
            return go_accommodation_menu(phone)
        if state == "prop_enquiry_name":
            return go_accommodation_menu(phone)
        # Cart back-navigation
        if state in ("ctx_cart", "ctx_cart_remove"):
            return go_buyer_menu(phone)
        if state in ("ctx_checkout_delivery", "ctx_checkout_delivery_addr"):
            set_session(phone, "ctx_cart", {})
            return format_cart(get_cart(phone))
        if state == "ctx_checkout":
            total = data.get("total", 0)
            set_session(phone, "ctx_checkout_delivery", {"total": total})
            return (
                f"🚚 *Delivery Options*\n\n"
                f"Order total: *${total:.2f}*\n\n"
                f"1️⃣  — 🚚 Delivery (send to me)\n"
                f"2️⃣  — 🏪 Self-collect (I'll pick it up)\n"
                f"0️⃣  — Back to cart"
            )
        if state in ("ctx_checkout_ecocash", "ctx_checkout_pending"):
            set_session(phone, "ctx_checkout", {
                "total": data.get("total", 0),
                "delivery_type": data.get("delivery_type", "self_collect"),
                "delivery_address": data.get("delivery_address", ""),
            })
            delivery_line = (
                f"\n📍 Delivering to: _{data.get('delivery_address')}_\n"
                if data.get("delivery_type") == "delivery" else ""
            )
            return (
                f"💳 *Checkout — ${data.get('total', 0):.2f}*"
                f"{delivery_line}\n\n"
                "1️⃣  — 📱 EcoCash\n2️⃣  — 💵 Cash on Delivery\n0️⃣  — Back"
            )
        if state in ("buy_delivery", "buy_delivery_addr"):
            set_session(phone, "buy_confirm", data)
            product = get_product_by_id(data.get("product_id"))
            total = data.get("total", 0)
            qty   = data.get("qty", 1)
            pname = product["name"] if product else "N/A"
            price = product["price"] if product else 0
            return (
                f"🛒 *Order Summary*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Product : {pname}\n"
                f"Qty     : {qty}\n"
                f"Price   : ${price:.2f} each\n"
                f"*Total  : ${total:.2f}*\n\n"
                "1️⃣  — ✅ *Confirm order*\n"
                "0️⃣  — ❌ Cancel\n\n"
                "_Reply *1* to confirm or *0* to cancel._"
            )
        if state in ("ctx_dispute_type", "ctx_dispute_desc"):
            clear_session(phone)
            return WELCOME
        if state in ("reg_kyc", "reg_location", "reg_name", "reg_business"):
            clear_session(phone)
            return WELCOME
        if state in ("del_reg_name", "del_reg_vehicle", "del_reg_area"):
            clear_session(phone)
            return WELCOME
        if state in ("prod_review_select", "prod_review_rating", "prod_review_comment"):
            clear_session(phone)
            return WELCOME
        # Service browsing back-navigation
        if state in ("ctx_find_service", "ctx_svc_cats", "ctx_svc_search", "ctx_svc_results"):
            return go_find_service_menu(phone)
        if state == "ctx_svc_detail":
            services = data.get("services", [])
            if services:
                set_session(phone, "ctx_svc_results", {"services": services})
                return format_service_list(services, title="🔧 *Services:*")
            return go_find_service_menu(phone)
        if state.startswith("svc_enq") or state.startswith("svc_review") or state.startswith("svc_offer"):
            return go_find_service_menu(phone)
        # All admin sub-states → go back to admin dashboard
        if state == "ctx_admin_seller_reject_reason":
            clear_session(phone)
            return build_admin_dashboard(phone)
        if state.startswith("ctx_admin"):
            return build_admin_dashboard(phone)
        clear_session(phone)
        return WELCOME

    # Hard exits — always back to top
    if msg_text in ("reset", "menu"):
        return go_welcome(phone)

    # Top-level numbers work from anywhere mid-session
    if msg_text in ("1", "2", "3", "4", "5") and state not in (
        "ctx_buyer", "ctx_seller", "ctx_accommodation",
        "ctx_find_service", "ctx_svc_cats", "ctx_svc_results", "ctx_svc_detail",
        "ctx_categories", "ctx_city_select",
        "ctx_prop_results", "ctx_prop_detail",
        "ctx_cart", "ctx_cart_remove",
        "ctx_checkout", "ctx_checkout_ecocash", "ctx_checkout_pending",
        "ctx_checkout_delivery", "ctx_checkout_delivery_addr",
        "buy_delivery", "buy_delivery_addr",
        "del_reg_vehicle",
        "ctx_dispute_type",
    ) and not state.startswith("ctx_admin") \
      and not state.startswith("svc_") \
      and not state.startswith("prod_review"):
        clear_session(phone)
        if msg_text == "1": return go_buyer_menu(phone)
        if msg_text == "2": return go_find_service_menu(phone)
        if msg_text == "3": return go_seller_menu(phone)
        if msg_text == "4": return go_accommodation_menu(phone)
        if msg_text == "5": return get_contact_response()


    # ── Menu context: main buyer menu ─────────────────────────────────────────
    if state == "ctx_buyer":
        if msg_text == "1":
            return go_categories(phone)
        if msg_text == "2":
            return SERVICES_RESPONSE
        if msg_text == "3":
            set_session(phone, "ctx_search")
            return "🔍 What are you looking for?\n\nType your search term:\n_e.g. laptop, cctv, printer_\n\n_Reply *0* to go back._"
        if msg_text == "4":
            set_session(phone, "awaiting_name")
            return "📋 *Get a Quote*\n━━━━━━━━━━━━━━━━━━━━━━━━━\n\nWhat is your *full name*?\n\n_Reply *0* to cancel._"
        if msg_text == "5":
            return format_buyer_orders(get_buyer_orders(phone)) + f"\n\n{BUYER_MENU}"
        return BUYER_MENU

    # ── Menu context: main seller menu ────────────────────────────────────────
    if state == "ctx_seller":
        if msg_text == "1":
            return _handle_register(phone)
        if msg_text == "2":
            return _handle_sell_product(phone)
        if msg_text == "3":
            return _handle_offer_service(phone)
        if msg_text == "4":
            seller = get_seller(phone)
            if not seller or seller["status"] != "approved":
                return "You need an approved seller account first.\n\nReply *1* to register.\n\n_Reply *0* to go back to the menu."
            # Show both product listings and service listings
            products = get_seller_products(phone)
            services = get_provider_services(phone)
            lines    = []
            if products:
                lines.append("📦 *My Product Listings:*\n")
                for p in products:
                    icon = {"approved": "✅", "pending": "⏳", "rejected": "❌"}.get(p["status"], "•")
                    lines.append(f"{icon} {p['name']} — ${p['price']:.2f} ({p['status'].title()})")
            if services:
                lines.append("\n🔧 *My Service Listings:*\n")
                for s in services:
                    icon = {"approved": "✅", "pending": "⏳", "rejected": "❌"}.get(s["status"], "•")
                    lines.append(f"{icon} {s['title']} — {_price_label(s)} ({s['status'].title()})")
            if not products and not services:
                return "📭 You have no listings yet.\n\nReply *2* to list a product or *3* to offer a service.\n\n_Reply *0* for main menu._"
            lines.append("\n_Reply *0* for the main menu._")
            return "\n".join(lines)
        if msg_text == "5":
            seller = get_seller(phone)
            if seller and seller["status"] == "approved":
                return format_seller_orders(get_seller_orders(phone))
            return format_buyer_orders(get_buyer_orders(phone))
        return SELLER_MENU

    # ── Menu context: category list ───────────────────────────────────────────
    if state == "ctx_categories":
        cat_map = {str(i + 1): CATEGORIES[i] for i in range(len(CATEGORIES))}
        if msg_text in cat_map:
            category = cat_map[msg_text]
            results  = get_products_by_category(category)
            if not results:
                # IT Services & no listings → offer a quote instead
                if category == "IT Services":
                    return (
                        f"🛠️ No services are currently listed under *{category}*.\n\n"
                        "Would you like to request a custom service quote?\n\n"
                        "1️⃣  — Yes, request a quote\n"
                        "0️⃣  — Back to categories"
                    )
                return (
                    f"😕 No products listed under *{category}* yet.\n\n"
                    "_Reply *0* to browse other categories._"
                )
            # Convert to dicts to avoid sqlite3.Row issues
            product_data = [_to_dict(r) for r in results[:5]]
            set_session(phone, "ctx_results", {"products": product_data, "back": "categories"})
            return format_numbered_products(product_data, title=f"🖥️ *{category}:*")
        # Handle "1" for quote after "no IT services" message
        if msg_text == "1":
            set_session(phone, "awaiting_name")
            return (
                "📋 *Request a Service Quote*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "What is your *full name*?\n\n"
                "_Reply *0* to cancel._"
            )
        return CATEGORIES_MENU

    # ── Menu context: search prompt ───────────────────────────────────────────
    if state == "ctx_search":
        results = search_products(msg_text)
        if not results:
            return (
                f"😕 No results for *{msg_text}*.\n\n"
                "Try a different keyword, or reply *0* to go back."
            )
        product_data = [_to_dict(r) for r in results[:5]]
        set_session(phone, "ctx_results", {"products": product_data, "back": "buyer"})
        return format_numbered_products(product_data, title=f"🔍 *Results for \"{msg_text}\":*")

    # ── Menu context: numbered product results ────────────────────────────────
    if state == "ctx_results":
        products = data.get("products", [])
        num_map  = {str(i + 1): products[i] for i in range(len(products))}
        if msg_text in num_map:
            p       = num_map[msg_text]
            product = get_product_by_id(p["id"])
            if not product or product["status"] != "approved":
                return "❌ This item is no longer available.\n\n_Reply *0* to go back._"
            if product["stock_qty"] == 0:
                add_to_waitlist(phone, product["id"])
                return (
                    f"❌ *{product['name']}* is currently out of stock.\n\n"
                    "🔔 You've been added to the waitlist — we'll notify you when it's back.\n\n"
                    "_Reply *0* to go back._"
                )
            # Show full product card then ask for quantity
            desc = product["description"] or "No description available."
            set_session(phone, "buy_qty", {
                "product_id": product["id"],
                "back": data.get("back", "buyer"),
                "products": products,
            })
            # Send product photo over WhatsApp if available
            if product.get("image_path"):
                image_url = f"{BASE_URL}/uploads/{product['image_path']}"
                send_whatsapp_image(phone, image_url, caption=product["name"])
            web_link = f"{BASE_URL}/product/{product['id']}"
            return (
                f"🛒 *{product['name']}*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📦 Category : {product['category']}\n"
                f"💰 Price    : ${product['price']:.2f} each\n"
                f"📦 In stock : {product['stock_qty']} unit(s)\n"
                f"📝 {desc[:120]}\n"
                f"🔗 _View photos: {web_link}_\n\n"
                "How many would you like?\n"
                "_Type a number (e.g. 1, 2, 3...) or *0* to go back._"
            )
        # Invalid number — re-show the list
        return format_numbered_products(products, title="📋 *Select a product:*")

    # ── Accommodation: sub-menu ───────────────────────────────────────────────
    if state == "ctx_accommodation":
        if msg_text == "1":
            set_session(phone, "ctx_prop_search")
            return "🔍 What are you looking for?\n\nType a keyword, area or property name:\n_e.g. Borrowdale, 2 bedroom, furnished_\n\n_Reply *0* to go back._"
        if msg_text == "2":
            set_session(phone, "ctx_city_select")
            return CITIES_MENU
        if msg_text == "3":
            props = fetch_properties(student_friendly=True)
            if props is not None:
                props = props[:5]
            set_session(phone, "ctx_prop_results", {"props": props or [], "label": "Student-Friendly"})
            return format_property_list(props, title="🎓 *Student-Friendly Properties:*")
        if msg_text == "4":
            props = fetch_properties()
            if props is not None:
                props = props[:5]
            set_session(phone, "ctx_prop_results", {"props": props or [], "label": "All Available"})
            return format_property_list(props, title="🏠 *All Available Properties:*")
        return ACCOMMODATION_MENU

    # ── Accommodation: city select ────────────────────────────────────────────
    if state == "ctx_city_select":
        city_map = {str(i + 1): ZIM_CITIES[i] for i in range(len(ZIM_CITIES))}
        if msg_text in city_map:
            city  = city_map[msg_text]
            props = fetch_properties(city=city)
            if props is not None:
                props = props[:5]
            set_session(phone, "ctx_prop_results", {"props": props or [], "label": city})
            return format_property_list(props, title=f"🏠 *Properties in {city}:*")
        return CITIES_MENU

    # ── Accommodation: keyword search ─────────────────────────────────────────
    if state == "ctx_prop_search":
        props = fetch_properties(search=msg_text)
        if props is not None:
            props = props[:5]
        set_session(phone, "ctx_prop_results", {"props": props or [], "label": msg_text})
        return format_property_list(props, title=f"🔍 *Results for \"{msg_text}\":*")

    # ── Accommodation: numbered results ───────────────────────────────────────
    if state == "ctx_prop_results":
        props   = data.get("props", [])
        num_map = {str(i + 1): props[i] for i in range(len(props))}
        if msg_text in num_map:
            prop = num_map[msg_text]
            # Store selected prop + full list so we can go back
            set_session(phone, "ctx_prop_detail", {
                "prop": prop,
                "props": props,
            })
            return format_property_detail(prop)
        return format_property_list(props, title="🏠 *Properties:*")

    # ── Accommodation: property detail ────────────────────────────────────────
    if state == "ctx_prop_detail":
        prop = data.get("prop", {})
        if msg_text == "1":
            # Start enquiry flow
            set_session(phone, "prop_enquiry_name", {
                "prop_id":    prop.get("id"),
                "prop_title": prop.get("title"),
                "prop_city":  prop.get("city", ""),
                "prop_price": prop.get("price_per_month", 0),
                "props":      data.get("props", []),
            })
            return (
                f"📋 *Enquire: {prop.get('title')}*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "What is your *full name*?\n\n"
                "_Reply *0* to cancel._"
            )
        if msg_text == "2":
            link = f"{TTECH_CONNECT_URL}/landlord/property/{prop.get('id')}"
            return (
                f"🌐 *View Full Listing:*\n\n"
                f"{link}\n\n"
                "Open the link to see all photos, reviews, and book a viewing.\n\n"
                "_Reply *0* to go back._"
            )
        return format_property_detail(prop)

    # ── Accommodation: enquiry name collection ────────────────────────────────
    if state == "prop_enquiry_name":
        name = msg_text.title()
        log_property_enquiry(
            phone=phone,
            name=name,
            property_id=data.get("prop_id", 0),
            property_title=data.get("prop_title", ""),
            property_city=data.get("prop_city", ""),
            price_per_month=data.get("prop_price", 0),
        )
        notify_admin(
            f"🏠 *New Property Enquiry*\n\n"
            f"Property : {data.get('prop_title')}\n"
            f"City     : {data.get('prop_city')}\n"
            f"Price    : ${data.get('prop_price', 0):.2f}/month\n"
            f"Enquirer : {name}\n"
            f"Phone    : {phone}\n\n"
            f"Link: {TTECH_CONNECT_URL}/landlord/property/{data.get('prop_id')}"
        )
        clear_session(phone)
        return (
            f"✅ *Enquiry Sent!*\n\n"
            f"Thank you, *{name}*!\n\n"
            f"Your enquiry for *{data.get('prop_title')}* has been received.\n\n"
            "Our team will contact you within *24 hours* to arrange a viewing. 🕐\n\n"
            f"💸 Viewing commission: *${round(data.get('prop_price', 0) * 0.05, 2):.2f}*\n"
            f"Pay via EcoCash or at {TTECH_CONNECT_URL}\n\n"
            "_Reply *0* for the main menu._"
        )

    # ── Find a service: top menu ──────────────────────────────────────────────
    if state == "ctx_find_service":
        if msg_text == "1":
            set_session(phone, "ctx_svc_cats")
            return SERVICE_CATS_MENU
        if msg_text == "2":
            set_session(phone, "ctx_svc_search")
            return "🔍 What service are you looking for?\n\nType a keyword:\n_e.g. plumber, electrician, tutor_\n\n_Reply *0* to go back._"
        return FIND_SERVICE_MENU

    # ── Service category browse ────────────────────────────────────────────────
    if state == "ctx_svc_cats":
        cat_map = {str(i + 1): SERVICE_CATEGORIES[i][1] for i in range(len(SERVICE_CATEGORIES))}
        if msg_text in cat_map:
            category = cat_map[msg_text]
            services = get_services_by_category(category)
            if not services:
                return (
                    f"😕 No services listed under *{category}* yet.\n\n"
                    "Reply *2* to search by keyword, or *0* to go back."
                )
            set_session(phone, "ctx_svc_results", {"services": services})
            return format_service_list(services, title=f"🔧 *{category}:*")
        return SERVICE_CATS_MENU

    # ── Service keyword search ─────────────────────────────────────────────────
    if state == "ctx_svc_search":
        services = search_services(msg_text)
        if not services:
            return (
                f"😕 No services found for *{msg_text}*.\n\n"
                "Try a different keyword or reply *0* to go back."
            )
        set_session(phone, "ctx_svc_results", {"services": services, "query": msg_text})
        return format_service_list(services, title=f"🔍 *Results for \"{msg_text}\":*")

    # ── Numbered service results ───────────────────────────────────────────────
    if state == "ctx_svc_results":
        services = data.get("services", [])
        num_map  = {str(i + 1): services[i] for i in range(len(services))}
        if msg_text in num_map:
            svc     = num_map[msg_text]
            reviews = get_service_reviews(svc["id"])
            set_session(phone, "ctx_svc_detail", {
                "service": svc,
                "services": services,
            })
            return format_service_detail(svc, reviews)
        return format_service_list(services, title="📋 *Select a service:*")

    # ── Service detail: enquire or review ──────────────────────────────────────
    if state == "ctx_svc_detail":
        svc      = data.get("service", {})
        services = data.get("services", [])
        if msg_text == "1":
            set_session(phone, "svc_enq_name", {"service": svc, "services": services})
            return (
                f"📩 *Enquire: {svc.get('title')}*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "What is your *full name*?\n\n"
                "_Reply *0* to cancel._"
            )
        if msg_text == "2":
            set_session(phone, "svc_review_rating", {"service": svc, "services": services})
            return (
                f"⭐ *Review: {svc.get('title')}*\n\n"
                "Rate this service:\n"
                "1️⃣  ⭐\n2️⃣  ⭐⭐\n3️⃣  ⭐⭐⭐\n4️⃣  ⭐⭐⭐⭐\n5️⃣  ⭐⭐⭐⭐⭐\n\n"
                "_Reply *0* to cancel._"
            )
        reviews = get_service_reviews(svc["id"])
        return format_service_detail(svc, reviews)

    # ── Service enquiry: name collection ──────────────────────────────────────
    if state == "svc_enq_name":
        svc       = data.get("service", {})
        data["customer_name"] = msg_text.title()
        set_session(phone, "svc_enq_detail", data)
        return (
            f"Thanks, *{data['customer_name']}*! 👋\n\n"
            "Please describe what you need:\n"
            "_e.g. fix a leaking pipe, need a website, catering for 50 people_\n\n"
            "_Reply *0* to cancel._"
        )

    # ── Service enquiry: details collection ───────────────────────────────────
    if state == "svc_enq_detail":
        svc      = data.get("service", {})
        name     = data.get("customer_name", "Customer")
        details  = msg_text
        log_service_enquiry(svc["id"], phone, name, details)
        # Notify provider
        if svc.get("provider_phone"):
            send_whatsapp_message(
                svc["provider_phone"],
                f"📩 *New Service Enquiry!*\n\n"
                f"Service  : {svc['title']}\n"
                f"From     : {name}\n"
                f"Phone    : {phone}\n"
                f"Details  : {details}\n\n"
                "Reply to this number to respond to the customer."
            )
        notify_admin(
            f"📩 *Service Enquiry*\n\n"
            f"Service : {svc['title']}\n"
            f"Customer: {name} ({phone})\n"
            f"Details : {details}"
        )
        clear_session(phone)
        return (
            f"✅ *Enquiry Sent!*\n\n"
            f"Thank you, *{name}*!\n\n"
            f"Your enquiry for *{svc['title']}* has been received.\n"
            "The service provider will contact you directly. 📞\n\n"
            "_Reply *0* for the main menu._"
        )

    # ── Service review: rating ─────────────────────────────────────────────────
    if state == "svc_review_rating":
        svc = data.get("service", {})
        if msg_text in ("1", "2", "3", "4", "5"):
            data["rating"] = int(msg_text)
            set_session(phone, "svc_review_comment", data)
            stars = "⭐" * int(msg_text)
            return (
                f"{stars}\n\n"
                "Would you like to add a comment? (optional)\n"
                "Type your comment or reply *skip* to post without one.\n\n"
                "_Reply *0* to cancel._"
            )
        return "Please reply with a number from *1* to *5*."

    # ── Service review: comment ────────────────────────────────────────────────
    if state == "svc_review_comment":
        svc     = data.get("service", {})
        rating  = data.get("rating", 5)
        comment = "" if msg_text.lower() == "skip" else msg_text
        success = add_service_review(svc["id"], phone, rating, comment)
        clear_session(phone)
        if success:
            stars = "⭐" * rating
            return (
                f"✅ *Review posted!* {stars}\n\n"
                f"Thank you for rating *{svc['title']}*.\n\n"
                "Your review helps other customers make better decisions. 🙏\n\n"
                "_Reply *0* for the main menu._"
            )
        return "You've already reviewed this service.\n\n_Reply *0* for the main menu._"

    # ── Product review: select order ─────────────────────────────────────────
    if state == "prod_review_select":
        orders  = data.get("orders", [])
        num_map = {str(i + 1): orders[i] for i in range(len(orders))}
        if msg_text in num_map:
            order = num_map[msg_text]
            set_session(phone, "prod_review_rating", {
                "product_id":   order["prod_id"],
                "product_name": order["product_name"],
                "order_id":     order["id"],
            })
            return (
                f"⭐ *Rate: {order['product_name']}*\n\n"
                "1️⃣  ⭐  — Poor\n"
                "2️⃣  ⭐⭐ — Fair\n"
                "3️⃣  ⭐⭐⭐ — Good\n"
                "4️⃣  ⭐⭐⭐⭐ — Very Good\n"
                "5️⃣  ⭐⭐⭐⭐⭐ — Excellent\n\n"
                "_Reply *0* to cancel._"
            )
        return "Reply with a number to select a product to review."

    # ── Product review: rating ────────────────────────────────────────────────
    if state == "prod_review_rating":
        if msg_text in ("1", "2", "3", "4", "5"):
            data["rating"] = int(msg_text)
            set_session(phone, "prod_review_comment", data)
            stars = "⭐" * int(msg_text)
            return (
                f"{stars}\n\n"
                "Add a comment? (optional)\n"
                "Type your comment or reply *skip* to post without one.\n\n"
                "_Reply *0* to cancel._"
            )
        return "Please reply with a number from *1* to *5*."

    # ── Product review: comment ───────────────────────────────────────────────
    if state == "prod_review_comment":
        comment = "" if msg_text.lower() == "skip" else msg_text
        rating  = data.get("rating", 5)
        prod_id = data.get("product_id")
        name    = data.get("product_name", "the product")
        success = add_product_review(prod_id, phone, rating, comment, data.get("order_id"))
        clear_session(phone)
        if success:
            return (
                f"✅ *Review Posted!* {'⭐' * rating}\n\n"
                f"Thank you for rating *{name}*.\n"
                "Your review helps other buyers make better decisions. 🙏\n\n"
                "_Reply *0* for the main menu._"
            )
        return "You've already reviewed this product.\n\n_Reply *0* for the main menu._"

    # ── Offer a service: step-by-step listing ─────────────────────────────────
    if state == "svc_offer_title":
        data["title"] = msg_text.title()
        set_session(phone, "svc_offer_category", data)
        return SERVICE_CATS_MENU.replace("Browse by Service Category", "Select a Category for Your Service")

    if state == "svc_offer_category":
        cat_map = {str(i + 1): SERVICE_CATEGORIES[i][1] for i in range(len(SERVICE_CATEGORIES))}
        if msg_text in cat_map:
            data["category"] = cat_map[msg_text]
            set_session(phone, "svc_offer_price_type", data)
            return (
                "💰 *How do you charge?*\n\n"
                "1️⃣  — Hourly rate ($/hr)\n"
                "2️⃣  — Fixed price per job\n"
                "3️⃣  — Get a quote (varies per job)\n\n"
                "_Reply *1*, *2*, or *3*._"
            )
        return "Please reply with a number from *1* to *8*."

    if state == "svc_offer_price_type":
        pt_map = {"1": "hourly", "2": "fixed", "3": "quoted"}
        if msg_text in pt_map:
            data["price_type"] = pt_map[msg_text]
            if msg_text == "3":
                data["price"] = 0
                set_session(phone, "svc_offer_desc", data)
                return "📝 *Describe your service:*\n\nWhat do you offer? Include your experience, speciality, and what makes you stand out.\n\n_Reply *0* to cancel._"
            label = "hourly rate ($/hr)" if msg_text == "1" else "fixed price per job ($)"
            set_session(phone, "svc_offer_price", data)
            return f"💵 What is your *{label}*?\n\nType a number, e.g. *15*\n\n_Reply *0* to cancel._"
        return "Please reply with *1*, *2*, or *3*."

    if state == "svc_offer_price":
        try:
            price = float(msg_text.replace("$", "").strip())
            if price < 0:
                raise ValueError
        except ValueError:
            return "Please enter a valid number, e.g. *15* or *50*"
        data["price"] = price
        set_session(phone, "svc_offer_desc", data)
        return "📝 *Describe your service:*\n\nWhat do you offer? Include experience, speciality, and availability.\n\n_Reply *0* to cancel._"

    if state == "svc_offer_desc":
        data["description"] = msg_text
        set_session(phone, "svc_offer_area", data)
        return "📍 *What area(s) do you serve?*\n\ne.g. _Harare_, _Bulawayo, Mutare_, _Nationwide_\n\n_Reply *0* to cancel._"

    if state == "svc_offer_area":
        data["service_area"] = msg_text.title()
        set_session(phone, "svc_offer_confirm", data)
        pt    = data.get("price_type", "quoted")
        price = data.get("price", 0)
        p_str = f"${price:.0f}/hr" if pt == "hourly" else f"${price:.0f} fixed" if pt == "fixed" else "Get a quote"
        return (
            f"📋 *Service Listing Preview*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Title    : {data.get('title')}\n"
            f"Category : {data.get('category')}\n"
            f"Pricing  : {p_str}\n"
            f"Area     : {data.get('service_area')}\n\n"
            f"📝 _{data.get('description','')}_\n\n"
            "1️⃣  — ✅ Submit listing\n"
            "2️⃣  — 🔄 Start over\n"
            "0️⃣  — Cancel"
        )

    if state == "svc_offer_confirm":
        if msg_text == "1":
            seller = get_seller(phone)
            svc_id = add_service(
                title=data.get("title"),
                category=data.get("category"),
                description=data.get("description"),
                price_type=data.get("price_type", "quoted"),
                price=data.get("price", 0),
                service_area=data.get("service_area"),
                provider_phone=phone,
                provider_name=seller["name"] if seller else "",
                provider_business=seller["business_name"] if seller else "",
            )
            clear_session(phone)
            notify_admin(
                f"🔧 *New Service Listing Pending*\n\n"
                f"Title    : {data.get('title')}\n"
                f"Category : {data.get('category')}\n"
                f"Provider : {data.get('provider_name', phone)}\n"
                f"Phone    : {phone}\n\n"
                f"➡ *approve service {svc_id}* or *reject service {svc_id}*"
            )
            return (
                f"✅ *Service Submitted!*\n\n"
                f"Your listing for *{data.get('title')}* is under review.\n\n"
                "We'll notify you within *24 hours* once approved. 🕐\n\n"
                "_Reply *0* for the main menu._"
            )
        if msg_text == "2":
            set_session(phone, "svc_offer_title", {})
            return "Let's start over. What is the *title* of your service?\ne.g. _Plumbing Repairs_, _CCTV Installation_"
        clear_session(phone)
        return "Cancelled. ✋\n\n" + WELCOME

    # ── Admin: main dashboard menu ────────────────────────────────────────────
    if state == "ctx_admin":
        if msg_text == "1":
            set_session(phone, "ctx_admin_seller_mgmt", {})
            return (
                "👤 *Seller Management*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "1️⃣  — ⏳ Review pending sellers\n"
                "2️⃣  — ✅ View approved sellers\n"
                "3️⃣  — ⚠️ Suspend a seller\n"
                "0️⃣  — Back to admin panel"
            )
        if msg_text == "2":
            set_session(phone, "ctx_admin_product_mgmt", {})
            return (
                "📦 *Product Management*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "1️⃣  — ⏳ Review pending listings\n"
                "2️⃣  — ✅ View approved listings\n"
                "3️⃣  — 🗑️ Remove a listing\n"
                "0️⃣  — Back to admin panel"
            )
        if msg_text == "3":
            # Manage Services
            rows = get_pending_services()
            if not rows:
                return "✅ No services pending approval.\n\nSend *admin* to return to the panel."
            lines = [f"🔧 *Pending Services ({len(rows)}):*\n"]
            for i, s in enumerate(rows[:9]):
                lines.append(
                    f"{NUM_EMOJI[i]}  *{s['title']}*\n"
                    f"    Category : {s['category']}\n"
                    f"    Provider : {s.get('provider_business') or s['provider_phone']}\n"
                    f"    Pricing  : {_price_label(s)}\n"
                )
            lines.append("_Reply with a number to approve/reject | *0* to go back_")
            set_session(phone, "ctx_admin_services", {"services": rows})
            return "\n".join(lines)
        if msg_text == "4":
            orders = [dict(r) for r in get_recent_orders_admin(9)]
            if not orders:
                return "📭 No orders yet.\n\n_Reply *0* to go back._"
            lines = [f"🛒 *Recent Orders ({len(orders)}):*\n"]
            for i, o in enumerate(orders):
                icon = {"pending": "⏳", "confirmed": "✅", "cancelled": "❌", "fulfilled": "📦"}.get(o["status"], "•")
                lines.append(
                    f"{NUM_EMOJI[i]} {icon} *{o['product_name']}*\n"
                    f"    Qty: {o['quantity']}  |  ${o['total_price']:.2f}  |  {o['status'].title()}\n"
                    f"    Buyer: {o['buyer_phone']}\n"
                )
            lines.append("_Reply with a number to update status | *0* to go back_")
            set_session(phone, "ctx_admin_orders", {"orders": orders})
            return "\n".join(lines)
        if msg_text == "5":
            prop_eq = [dict(r) for r in get_property_enquiries(status="new", limit=5)]
            svc_eq  = [dict(r) for r in get_service_enquiries(status="new", limit=4)]
            rows    = prop_eq + svc_eq
            if not rows:
                return "📭 No new enquiries.\n\n_Reply *0* to go back._"
            lines = [f"📩 *New Enquiries ({len(rows)}):*\n"]
            for i, r in enumerate(rows):
                if "property_title" in r:
                    lines.append(f"{NUM_EMOJI[i]} 🏠 *{r['name']}* — {r['property_title']}\n    📞 {r['phone']}\n")
                else:
                    lines.append(f"{NUM_EMOJI[i]} 🔧 *{r['customer_name']}* — {r['service_title']}\n    📞 {r['customer_phone']}\n")
            lines.append("_Reply with a number to mark as handled | *0* to go back_")
            set_session(phone, "ctx_admin_enquiries", {"enquiries": rows})
            return "\n".join(lines)
        if msg_text == "6":
            set_session(phone, "ctx_admin_broadcast_target", {})
            return (
                "📢 *Send Broadcast Message*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "1️⃣  — Message all *sellers* only\n"
                "2️⃣  — Message *everyone* (all users)\n"
                "0️⃣  — Back to admin panel"
            )
        if msg_text == "7":
            prod_rate  = get_setting("commission_rate", "10")
            svc_rate   = get_setting("service_commission_rate", "10")
            accom_rate = get_setting("accommodation_commission_rate", "5")
            set_session(phone, "ctx_admin_commission", {})
            return (
                f"⚙️ *Commission Settings*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"Current rates:\n"
                f"• 📦 Products      : *{prod_rate}%*\n"
                f"• 🔧 Services      : *{svc_rate}%*\n"
                f"• 🏠 Accommodation : *{accom_rate}%*\n\n"
                f"1️⃣  — Change product commission\n"
                f"2️⃣  — Change service commission\n"
                f"3️⃣  — Change accommodation commission\n"
                f"0️⃣  — Back to admin panel"
            )
        return build_admin_dashboard(phone)

    # ── Admin: seller management submenu ──────────────────────────────────────
    if state == "ctx_admin_seller_mgmt":
        if msg_text == "1":
            return _show_sellers_list(phone, status="pending")
        if msg_text == "2":
            return _show_sellers_list(phone, status="approved", title="👤 *Approved Sellers:*")
        if msg_text == "3":
            rows = [dict(r) for r in get_all_sellers_admin("approved")[:9]]
            if not rows:
                return "✅ No approved sellers to suspend.\n\n_Reply *0* to go back._"
            lines = ["👤 *Select Seller to Suspend:*\n"]
            for i, r in enumerate(rows):
                lines.append(f"{NUM_EMOJI[i]}  *{r['name']}* — {r['business_name']}\n    📞 {r['phone']}\n")
            lines.append("_Reply with a number | *0* to go back_")
            set_session(phone, "ctx_admin_seller_suspend", {"sellers": rows})
            return "\n".join(lines)
        return (
            "👤 *Seller Management*\n\n"
            "1️⃣  — ⏳ Pending\n2️⃣  — ✅ Approved\n3️⃣  — ⚠️ Suspend\n0️⃣  — Back"
        )

    # ── Admin: seller suspend selection ───────────────────────────────────────
    if state == "ctx_admin_seller_suspend":
        sellers = data.get("sellers", [])
        num_map = {str(i + 1): sellers[i] for i in range(len(sellers))}
        if msg_text in num_map:
            seller = num_map[msg_text]
            set_session(phone, "ctx_admin_seller_action", {
                "seller": seller, "sellers": sellers, "mode": "suspend"
            })
            return (
                f"⚠️ Suspend *{seller['name']}*?\n"
                f"Business: {seller['business_name']}\n"
                f"Phone: {seller['phone']}\n\n"
                f"1️⃣  — ⚠️ Yes, suspend\n"
                f"0️⃣  — Cancel"
            )
        return "Reply with a number from the list."

    # ── Admin: numbered sellers list ──────────────────────────────────────────
    if state == "ctx_admin_sellers":
        sellers = data.get("sellers", [])
        num_map = {str(i + 1): sellers[i] for i in range(len(sellers))}
        if msg_text in num_map:
            seller = num_map[msg_text]
            mode   = data.get("mode", "pending")
            set_session(phone, "ctx_admin_seller_action", {
                "seller": seller, "sellers": sellers, "mode": mode
            })
            trust     = get_seller_trust_score(seller["phone"])
            trust_bar = "🟢" if trust >= 70 else "🟡" if trust >= 40 else "🔴"
            # KYC status — prefer new photo fields, fall back to legacy kyc_link
            id_photo     = seller.get("id_photo", "")
            selfie_photo = seller.get("selfie_photo", "")
            kyc_link     = seller.get("kyc_link", "")
            if id_photo and selfie_photo:
                kyc_note = "\nKYC      : ✅ ID + Selfie uploaded (photos follow)"
            elif id_photo or selfie_photo:
                kyc_note = "\nKYC      : ⚠️ Partial — only one photo uploaded"
            elif kyc_link:
                kyc_note = f"\nKYC      : {kyc_link}"
            else:
                kyc_note = "\nKYC      : ❌ Not provided"
            # Push KYC photos to admin WhatsApp so they can review inline
            if id_photo:
                send_whatsapp_image(
                    phone,
                    f"{BASE_URL}/uploads/{id_photo}",
                    caption=f"🪪 ID — {seller['name']} ({seller['business_name']})",
                )
            if selfie_photo:
                send_whatsapp_image(
                    phone,
                    f"{BASE_URL}/uploads/{selfie_photo}",
                    caption=f"🤳 Selfie — {seller['name']} | {seller['phone']}",
                )
            return (
                f"👤 *{seller['name']}*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Business : {seller['business_name']}\n"
                f"Phone    : {seller['phone']}\n"
                f"Location : {seller.get('location') or 'N/A'}\n"
                f"Status   : {seller.get('status','').title()}\n"
                f"Trust    : {trust_bar} {trust}/100{kyc_note}\n\n"
                f"1️⃣  — ✅ Approve seller\n"
                f"2️⃣  — ❌ Reject seller\n"
                f"3️⃣  — ⚠️ Suspend seller\n"
                f"0️⃣  — Back to list"
            )
        return "Reply with a number from the list above."

    # ── Admin: seller action (approve / reject / suspend) ─────────────────────
    if state == "ctx_admin_seller_action":
        seller  = data.get("seller", {})
        sellers = data.get("sellers", [])
        mode    = data.get("mode", "pending")
        if msg_text == "1":
            result = _suspend_seller(seller["phone"]) if mode == "suspend" else _approve_seller(seller["phone"])
            clear_session(phone)
            return result + "\n\nSend *admin* to return to the panel."
        if msg_text == "2":
            # Ask for rejection reason before rejecting
            set_session(phone, "ctx_admin_seller_reject_reason", {
                "seller": seller, "sellers": sellers
            })
            return (
                f"❌ Rejecting *{seller['name']}*\n\n"
                "Type the *reason for rejection* (or *skip* for no reason):\n\n"
                "_Reply *0* to cancel._"
            )
        if msg_text == "3":
            result = _suspend_seller(seller["phone"])
            clear_session(phone)
            return result + "\n\nSend *admin* to return to the panel."
        return (
            f"👤 *{seller.get('name')}*\n\n"
            f"1️⃣  — ✅ Approve\n2️⃣  — ❌ Reject\n3️⃣  — ⚠️ Suspend\n0️⃣  — Back"
        )

    # ── Admin: seller rejection reason input ──────────────────────────────────
    if state == "ctx_admin_seller_reject_reason":
        seller = data.get("seller", {})
        reason = "" if msg_text.lower() == "skip" else msg_text
        result = _reject_seller(seller["phone"], reason)
        clear_session(phone)
        return result + "\n\nSend *admin* to return to the panel."

    # ── Admin: product management submenu ─────────────────────────────────────
    if state == "ctx_admin_product_mgmt":
        if msg_text == "1":
            return _show_products_list(phone, status="pending")
        if msg_text == "2":
            return _show_products_list(phone, status="approved", title="📦 *Approved Listings:*")
        if msg_text == "3":
            return _show_products_list(phone, status="approved", title="🗑️ *Select Listing to Remove:*")
        return (
            "📦 *Product Management*\n\n"
            "1️⃣  — ⏳ Pending\n2️⃣  — ✅ Approved\n3️⃣  — 🗑️ Remove\n0️⃣  — Back"
        )

    # ── Admin: numbered products list ─────────────────────────────────────────
    if state == "ctx_admin_products":
        products = data.get("products", [])
        mode     = data.get("mode", "pending")
        num_map  = {str(i + 1): products[i] for i in range(len(products))}
        if msg_text in num_map:
            product = num_map[msg_text]
            set_session(phone, "ctx_admin_product_action", {
                "product": product, "products": products, "mode": mode
            })
            badge = {"approved": "✅", "pending": "⏳", "rejected": "❌"}.get(product.get("status", ""), "")
            return (
                f"📦 {badge} *{product['name']}*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Category  : {product['category']}\n"
                f"Price     : ${product['price']:.2f}\n"
                f"Commission: ${product['commission']:.2f}\n"
                f"Seller    : {product.get('business_name') or product.get('listed_by', 'N/A')}\n"
                f"Status    : {product.get('status','').title()}\n\n"
                f"1️⃣  — ✅ Approve listing\n"
                f"2️⃣  — ❌ Reject listing\n"
                f"3️⃣  — 🗑️ Remove listing\n"
                f"0️⃣  — Back to list"
            )
        return "Reply with a number from the list above."

    # ── Admin: product action ─────────────────────────────────────────────────
    if state == "ctx_admin_product_action":
        product  = data.get("product", {})
        products = data.get("products", [])
        if msg_text == "1":
            result = _approve_product(product["id"])
            clear_session(phone)
            return result + "\n\nSend *admin* to return to the panel."
        if msg_text == "2":
            set_session(phone, "ctx_admin_product_reject", {
                "product": product, "products": products
            })
            return (
                f"❌ Rejecting *{product['name']}*\n\n"
                "Type the *reason for rejection*:\n\n"
                "_Reply *0* to cancel._"
            )
        if msg_text == "3":
            result = _remove_product(product["id"])
            clear_session(phone)
            return result + "\n\nSend *admin* to return to the panel."
        return (
            f"📦 *{product.get('name')}*\n\n"
            f"1️⃣  — ✅ Approve\n2️⃣  — ❌ Reject\n3️⃣  — 🗑️ Remove\n0️⃣  — Back"
        )

    # ── Admin: product rejection reason ───────────────────────────────────────
    if state == "ctx_admin_product_reject":
        product = data.get("product", {})
        result  = _reject_product(product["id"], msg_text)
        clear_session(phone)
        return result + "\n\nSend *admin* to return to the panel."

    # ── Admin: pending services list ──────────────────────────────────────────
    if state == "ctx_admin_services":
        services = data.get("services", [])
        num_map  = {str(i + 1): services[i] for i in range(len(services))}
        if msg_text in num_map:
            svc = num_map[msg_text]
            set_session(phone, "ctx_admin_service_action", {
                "service": svc, "services": services
            })
            return (
                f"🔧 *{svc['title']}*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Category : {svc['category']}\n"
                f"Pricing  : {_price_label(svc)}\n"
                f"Area     : {svc.get('service_area', 'N/A')}\n"
                f"Provider : {svc.get('provider_business') or svc['provider_phone']}\n"
                f"Phone    : {svc['provider_phone']}\n\n"
                f"📝 _{svc.get('description', 'No description.')}_\n\n"
                f"1️⃣  — ✅ Approve service\n"
                f"2️⃣  — ❌ Reject service\n"
                f"0️⃣  — Back to list"
            )
        return "Reply with a number from the list above."

    # ── Admin: service approve / reject ───────────────────────────────────────
    if state == "ctx_admin_service_action":
        svc      = data.get("service", {})
        services = data.get("services", [])
        if msg_text == "1":
            set_service_status(svc["id"], "approved")
            if svc.get("provider_phone"):
                send_whatsapp_message(
                    svc["provider_phone"],
                    f"🎉 Your service *{svc['title']}* is now *live* on T-Tech Connect!\n\n"
                    "Customers can now find and enquire about your service. 🔧\n\n"
                    "_Reply *0* for the main menu._"
                )
            clear_session(phone)
            return f"✅ *{svc['title']}* approved and live.\n\nSend *admin* to return to the panel."
        if msg_text == "2":
            set_session(phone, "ctx_admin_service_reject", {
                "service": svc, "services": services
            })
            return (
                f"❌ Rejecting *{svc['title']}*\n\n"
                "Type the *reason for rejection*:\n\n"
                "_Reply *0* to cancel._"
            )
        return (
            f"🔧 *{svc.get('title')}*\n\n"
            f"1️⃣  — ✅ Approve\n2️⃣  — ❌ Reject\n0️⃣  — Back"
        )

    # ── Admin: service rejection reason ───────────────────────────────────────
    if state == "ctx_admin_service_reject":
        svc    = data.get("service", {})
        reason = msg_text
        set_service_status(svc["id"], "rejected", reason)
        if svc.get("provider_phone"):
            send_whatsapp_message(
                svc["provider_phone"],
                f"❌ Your service *{svc['title']}* was not approved.\n\n"
                f"Reason: _{reason}_\n\n"
                "Please update and try again from the Sell menu.\n\n"
                "_Reply *0* for the main menu._"
            )
        clear_session(phone)
        return f"❌ *{svc['title']}* rejected. Provider notified.\n\nSend *admin* to return to the panel."

    # ── Admin: orders view ────────────────────────────────────────────────────
    if state == "ctx_admin_orders":
        orders  = data.get("orders", [])
        num_map = {str(i + 1): orders[i] for i in range(len(orders))}
        if msg_text in num_map:
            order = num_map[msg_text]
            set_session(phone, "ctx_admin_order_action", {
                "order": order, "orders": orders
            })
            return (
                f"🛒 *Order #{order.get('reference', order['id'])}*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Product : {order['product_name']}\n"
                f"Qty     : {order['quantity']}  |  ${order['total_price']:.2f}\n"
                f"Buyer   : {order['buyer_phone']}\n"
                f"Status  : {order['status'].title()}\n\n"
                f"1️⃣  — 📦 Mark as Fulfilled\n"
                f"2️⃣  — ❌ Mark as Cancelled\n"
                f"0️⃣  — Back to orders"
            )
        return "Reply with a number from the list above."

    # ── Admin: order status update ────────────────────────────────────────────
    if state == "ctx_admin_order_action":
        order  = data.get("order", {})
        if msg_text == "1":
            update_order_status(order["id"], "fulfilled")
            ref = order.get("reference", str(order["id"]))
            # Fulfillment notification + post-delivery review prompt
            send_whatsapp_message(
                order["buyer_phone"],
                f"📦 *Order Delivered!*\n\n"
                f"Your order *{ref}* for *{order['product_name']}* has been fulfilled. 🎉\n\n"
                "Thank you for shopping with T-Tech Connect!\n\n"
                "⭐ *How was your experience?*\n"
                "Reply *rate product* to leave a quick review — it helps other buyers!"
            )
            log_admin_action(phone, "fulfill_order", "order", ref)
            clear_session(phone)
            return f"📦 Order *{ref}* marked as fulfilled. Buyer notified + review prompt sent."
        if msg_text == "2":
            update_order_status(order["id"], "cancelled")
            send_whatsapp_message(
                order["buyer_phone"],
                f"❌ Your order *{order.get('reference', '')}* for *{order['product_name']}* "
                "has been *cancelled*.\n\n"
                "Contact us for more information:\n"
                "📞 +263 77 412 8219\n\n"
                "_Reply *0* for the main menu._"
            )
            clear_session(phone)
            return f"❌ Order *{order.get('reference', order['id'])}* cancelled. Buyer notified."
        return (
            f"🛒 *{order.get('product_name')}*\n\n"
            f"1️⃣  — 📦 Fulfilled\n2️⃣  — ❌ Cancelled\n0️⃣  — Back"
        )

    # ── Admin: enquiries view ─────────────────────────────────────────────────
    if state == "ctx_admin_enquiries":
        enquiries = data.get("enquiries", [])
        num_map   = {str(i + 1): enquiries[i] for i in range(len(enquiries))}
        if msg_text in num_map:
            eq = num_map[msg_text]
            update_enquiry_status(eq["id"], "handled")
            return (
                f"✅ Marked as handled.\n\n"
                f"*{eq['name']}* — {eq['property_title']}\n"
                f"📞 {eq['phone']}\n\n"
                "Send *admin* to return to the panel."
            )
        return "Reply with a number to mark an enquiry as handled."

    # ── Admin: commission settings ────────────────────────────────────────────
    if state == "ctx_admin_commission":
        prod_rate  = get_setting("commission_rate", "10")
        svc_rate   = get_setting("service_commission_rate", "10")
        accom_rate = get_setting("accommodation_commission_rate", "5")
        if msg_text == "1":
            set_session(phone, "ctx_admin_set_commission", {"type": "product"})
            return (
                f"📦 *Product Commission Rate*\n\n"
                f"Current rate: *{prod_rate}%*\n\n"
                "Enter the new rate (0–100):\n"
                "_e.g. type *10* for 10%_\n\n"
                "_Reply *0* to cancel._"
            )
        if msg_text == "2":
            set_session(phone, "ctx_admin_set_commission", {"type": "service"})
            return (
                f"🔧 *Service Commission Rate*\n\n"
                f"Current rate: *{svc_rate}%*\n\n"
                "Enter the new rate (0–100):\n"
                "_e.g. type *10* for 10%_\n\n"
                "_Reply *0* to cancel._"
            )
        if msg_text == "3":
            set_session(phone, "ctx_admin_set_commission", {"type": "accommodation"})
            return (
                f"🏠 *Accommodation Commission Rate*\n\n"
                f"Current rate: *{accom_rate}%*\n\n"
                "Enter the new rate (0–100):\n"
                "_e.g. type *5* for 5%_\n\n"
                "_Reply *0* to cancel._"
            )
        return (
            f"⚙️ *Commission Settings*\n\n"
            f"• 📦 Products      : *{prod_rate}%*\n"
            f"• 🔧 Services      : *{svc_rate}%*\n"
            f"• 🏠 Accommodation : *{accom_rate}%*\n\n"
            f"1️⃣  Change product rate\n"
            f"2️⃣  Change service rate\n"
            f"3️⃣  Change accommodation rate\n"
            f"0️⃣  Back"
        )

    # ── Admin: set commission rate (input) ────────────────────────────────────
    if state == "ctx_admin_set_commission":
        rate_type   = data.get("type", "product")
        key_map     = {
            "product":       "commission_rate",
            "service":       "service_commission_rate",
            "accommodation": "accommodation_commission_rate",
        }
        label_map   = {
            "product": "📦 Product",
            "service": "🔧 Service",
            "accommodation": "🏠 Accommodation",
        }
        setting_key = key_map.get(rate_type, "commission_rate")
        label       = label_map.get(rate_type, "📦 Product")
        try:
            new_rate = float(msg_text.replace("%", "").strip())
            if new_rate < 0 or new_rate > 100:
                raise ValueError
        except ValueError:
            return "❌ Please enter a valid number between 0 and 100.\n_e.g. type *10* for 10%_"
        old_rate = get_setting(setting_key, "10")
        set_setting(setting_key, str(int(new_rate) if new_rate == int(new_rate) else new_rate))
        clear_session(phone)
        return (
            f"✅ *{label} Commission Updated*\n\n"
            f"Old rate : {old_rate}%\n"
            f"New rate : *{new_rate:.0f}%*\n\n"
            "All new listings will use this rate going forward.\n\n"
            "Send *admin* to return to the panel."
        )

    # ── Admin: broadcast target selection ────────────────────────────────────
    if state == "ctx_admin_broadcast_target":
        if msg_text == "1":
            phones = get_seller_phone_list()
            if not phones:
                return "📭 No approved sellers to message.\n\n_Reply *0* to go back._"
            set_session(phone, "ctx_admin_broadcast_msg", {
                "target": "sellers", "phones": phones
            })
            return (
                f"📢 *Broadcast to {len(phones)} seller(s)*\n\n"
                "Type the message to send:\n\n"
                "_Reply *0* to cancel._"
            )
        if msg_text == "2":
            phones = get_all_user_phones()
            if not phones:
                return "📭 No users found.\n\n_Reply *0* to go back._"
            set_session(phone, "ctx_admin_broadcast_msg", {
                "target": "all", "phones": phones
            })
            return (
                f"📢 *Broadcast to {len(phones)} user(s)*\n\n"
                "Type the message to send:\n\n"
                "⚠️ This will message _everyone_ who has ever contacted the bot.\n\n"
                "_Reply *0* to cancel._"
            )
        return "1️⃣  Sellers only\n2️⃣  Everyone\n0️⃣  Back"

    # ── Admin: broadcast — collect message text ───────────────────────────────
    if state == "ctx_admin_broadcast_msg":
        phones  = data.get("phones", [])
        target  = data.get("target", "")
        preview = (
            f"📢 *T-Tech Connect*\n\n"
            f"{msg_text}\n\n"
            "_Reply *0* for the main menu._"
        )
        # Show preview and ask for confirmation before sending
        recipient_count = len([p for p in phones if p != phone])
        set_session(phone, "ctx_admin_broadcast_confirm", {
            "phones": phones,
            "target": target,
            "message": preview,
        })
        return (
            f"📋 *Broadcast Preview*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{preview}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"This will be sent to *{recipient_count}* {target}.\n\n"
            f"1️⃣  — ✅ Send now\n"
            f"2️⃣  — ✏️ Edit message\n"
            f"0️⃣  — Cancel"
        )

    # ── Admin: broadcast — confirm and send ───────────────────────────────────
    if state == "ctx_admin_broadcast_confirm":
        phones  = data.get("phones", [])
        target  = data.get("target", "")
        message = data.get("message", "")
        if msg_text == "1":
            sent = 0
            for p in phones:
                if p != phone:
                    send_whatsapp_message(p, message)
                    sent += 1
            _log("broadcast", target, "", f"Sent to {sent} recipients")
            clear_session(phone)
            return f"✅ Broadcast sent to *{sent}* {target} successfully."
        if msg_text == "2":
            set_session(phone, "ctx_admin_broadcast_msg", {
                "phones": phones, "target": target
            })
            return "✏️ Type your new message:"
        clear_session(phone)
        return "↩️ Broadcast cancelled."

    # ── Cart: view / checkout menu ────────────────────────────────────────────
    if state == "ctx_cart":
        items = get_cart(phone)
        if msg_text == "1":   # checkout
            if not items:
                clear_session(phone)
                return "🛒 Your cart is empty.\n\n_Reply *0* for the main menu._"
            total = get_cart_total(phone)
            set_session(phone, "ctx_checkout_delivery", {"total": total})
            return (
                f"🚚 *Delivery Options*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🧾 Order total : *${total:.2f}*\n\n"
                f"How would you like to receive your order?\n\n"
                f"1️⃣  — 🚚 Delivery (send to me)\n"
                f"2️⃣  — 🏪 Self-collect (I'll pick it up)\n"
                f"0️⃣  — Back to cart"
            )
        if msg_text == "2":   # clear cart
            clear_cart(phone)
            clear_session(phone)
            return "🗑️ Cart cleared.\n\n_Reply *0* for the main menu._"
        if msg_text == "3":   # remove item
            if not items:
                return "Your cart is empty."
            lines = ["Which item would you like to remove?\n"]
            for i, item in enumerate(items):
                lines.append(f"{NUM_EMOJI[i]}  {item['name']} × {item['quantity']}")
            lines.append("\n_Reply with a number | *0* to cancel_")
            set_session(phone, "ctx_cart_remove", {"items": items})
            return "\n".join(lines)
        return format_cart(items)

    # ── Cart: remove item ─────────────────────────────────────────────────────
    if state == "ctx_cart_remove":
        items   = data.get("items", [])
        num_map = {str(i + 1): items[i] for i in range(len(items))}
        if msg_text in num_map:
            item = num_map[msg_text]
            remove_from_cart(phone, item["product_id"])
            remaining = get_cart(phone)
            set_session(phone, "ctx_cart", {})
            return f"✅ *{item['name']}* removed from cart.\n\n" + format_cart(remaining)
        return "Reply with a number to remove an item."

    # ── Checkout: delivery choice ─────────────────────────────────────────────
    if state == "ctx_checkout_delivery":
        total = data.get("total", 0)
        if msg_text == "1":   # Delivery
            set_session(phone, "ctx_checkout_delivery_addr", {"total": total})
            return (
                "📍 *Your Delivery Address*\n\n"
                "Please enter your delivery address:\n\n"
                "_e.g. 123 Main Street, Harare CBD_\n\n"
                "_Reply *0* to cancel._"
            )
        if msg_text == "2":   # Self-collect
            set_session(phone, "ctx_checkout", {
                "total": total,
                "delivery_type": "self_collect",
                "delivery_address": "",
            })
            return (
                f"💳 *Checkout — ${total:.2f}*\n\n"
                "🏪 You will collect your order from the seller.\n\n"
                "Choose payment method:\n\n"
                "1️⃣  — 📱 EcoCash (pay now)\n"
                "2️⃣  — 💵 Cash on Delivery\n"
                "0️⃣  — Back"
            )
        return (
            f"🚚 *Delivery Options*\n\n"
            f"Order total: *${total:.2f}*\n\n"
            f"1️⃣  — 🚚 Delivery (send to me)\n"
            f"2️⃣  — 🏪 Self-collect (I'll pick it up)\n"
            f"0️⃣  — Back to cart"
        )

    # ── Checkout: delivery address ────────────────────────────────────────────
    if state == "ctx_checkout_delivery_addr":
        total = data.get("total", 0)
        delivery_address = msg_text.strip()
        if len(delivery_address) < 5:
            return "Please provide a valid delivery address (at least 5 characters).\n\n_e.g. 123 Main Street, Harare CBD_"
        set_session(phone, "ctx_checkout", {
            "total": total,
            "delivery_type": "delivery",
            "delivery_address": delivery_address,
        })
        return (
            f"💳 *Checkout — ${total:.2f}*\n\n"
            f"📍 Delivering to: _{delivery_address}_\n\n"
            "Choose payment method:\n\n"
            "1️⃣  — 📱 EcoCash (pay now)\n"
            "2️⃣  — 💵 Cash on Delivery\n"
            "0️⃣  — Back"
        )

    # ── Checkout: payment method ──────────────────────────────────────────────
    if state == "ctx_checkout":
        total            = data.get("total", 0)
        delivery_type    = data.get("delivery_type", "self_collect")
        delivery_address = data.get("delivery_address", "")
        if msg_text == "1":   # EcoCash
            set_session(phone, "ctx_checkout_ecocash", {
                "total": total,
                "delivery_type": delivery_type,
                "delivery_address": delivery_address,
            })
            return (
                f"📱 *EcoCash Payment*\n\n"
                f"Amount: *${total:.2f}*\n\n"
                "Enter your EcoCash phone number:\n"
                "_e.g. 0774128219_\n\n"
                "_Reply *0* to cancel._"
            )
        if msg_text == "2":   # Cash on Delivery
            items = get_cart(phone)
            from db import create_order, update_stock, get_product_by_id
            placed = []
            for item in items:
                product = get_product_by_id(item["product_id"])
                if product and product["stock_qty"] >= item["quantity"]:
                    order_id, order_ref, order_total = create_order(
                        phone, item["product_id"], item["quantity"], item["price"],
                        delivery_type=delivery_type,
                        delivery_address=delivery_address,
                    )
                    update_stock(item["product_id"], product["stock_qty"] - item["quantity"])
                    placed.append(f"• {item['name']} × {item['quantity']}")
                    if product["listed_by"]:
                        d_note = (f"\n📍 Deliver to: {delivery_address}"
                                  if delivery_type == "delivery" else "\n🏪 Buyer will self-collect.")
                        send_whatsapp_message(
                            product["listed_by"],
                            f"🛒 *New COD Order!*\n\nRef: *{order_ref}*\n"
                            f"Item: {item['name']} × {item['quantity']}\n"
                            f"Buyer: {phone}\nPayment: Cash on Delivery{d_note}"
                        )
            clear_cart(phone)
            clear_session(phone)
            items_str = "\n".join(placed) if placed else "No items could be processed."
            buyer_note = (
                "📍 A delivery agent will contact you to arrange delivery. 🚚"
                if delivery_type == "delivery"
                else "🏪 Please collect your order from the seller."
            )
            return (
                f"✅ *Order Placed — Cash on Delivery!*\n\n"
                f"Items ordered:\n{items_str}\n\n"
                f"💵 Pay *${total:.2f}* on delivery.\n\n"
                f"{buyer_note}\n\n"
                "_Reply *0* for the main menu._"
            )
        return (
            f"💳 *Checkout — ${total:.2f}*\n\n"
            f"1️⃣  — 📱 EcoCash\n2️⃣  — 💵 Cash on Delivery\n0️⃣  — Back"
        )

    # ── Checkout: EcoCash phone number ────────────────────────────────────────
    if state == "ctx_checkout_ecocash":
        total            = data.get("total", 0)
        delivery_type    = data.get("delivery_type", "self_collect")
        delivery_address = data.get("delivery_address", "")
        ec_phone = msg_text.strip().replace(" ", "")
        if not (ec_phone.isdigit() and len(ec_phone) >= 9):
            return "❌ Please enter a valid phone number, e.g. *0774128219*"
        ref    = f"TTC-{__import__('uuid').uuid4().hex[:6].upper()}"
        result = initiate_ecocash_payment(ec_phone, total, ref)
        if result["success"]:
            set_session(phone, "ctx_checkout_pending", {
                "poll_url": result["poll_url"],
                "reference": ref,
                "total": total,
                "ec_phone": ec_phone,
                "delivery_type": delivery_type,
                "delivery_address": delivery_address,
            })
            return (
                f"📱 *EcoCash Payment Initiated!*\n\n"
                f"Reference : *{ref}*\n"
                f"Amount    : *${total:.2f}*\n"
                f"Phone     : {ec_phone}\n\n"
                "✅ Check your phone for the EcoCash prompt and enter your PIN.\n\n"
                "Once paid, reply *paid* to confirm your order.\n\n"
                "_Reply *0* to cancel._"
            )
        return (
            f"❌ EcoCash payment could not be initiated.\n\n"
            f"Reason: {result.get('error', 'Unknown error')}\n\n"
            "Try *2* for Cash on Delivery instead, or *0* to go back."
        )

    # ── Checkout: payment confirmation ────────────────────────────────────────
    if state == "ctx_checkout_pending":
        if msg_text == "paid":
            items            = get_cart(phone)
            ref              = data.get("reference", "")
            total            = data.get("total", 0)
            delivery_type    = data.get("delivery_type", "self_collect")
            delivery_address = data.get("delivery_address", "")
            from db import create_order, update_stock, get_product_by_id
            placed = []
            for item in items:
                product = get_product_by_id(item["product_id"])
                if product and product["stock_qty"] >= item["quantity"]:
                    _, order_ref, _ = create_order(
                        phone, item["product_id"], item["quantity"], item["price"],
                        delivery_type=delivery_type,
                        delivery_address=delivery_address,
                    )
                    update_stock(item["product_id"], product["stock_qty"] - item["quantity"])
                    placed.append(item["name"])
                    if product["listed_by"]:
                        d_note = (f"\n📍 Deliver to: {delivery_address}"
                                  if delivery_type == "delivery" else "\n🏪 Buyer will self-collect.")
                        send_whatsapp_message(
                            product["listed_by"],
                            f"💰 *New Paid Order!* (EcoCash)\n\n"
                            f"Ref: *{order_ref}*\n"
                            f"Item: {item['name']} × {item['quantity']}\n"
                            f"Buyer: {phone}{d_note}"
                        )
            clear_cart(phone)
            clear_session(phone)
            d_admin = (f"\n📍 Deliver to: {delivery_address}" if delivery_type == "delivery" else "")
            notify_admin(
                f"💰 *EcoCash Order* {ref}\n"
                f"Buyer: {phone}\nTotal: ${total:.2f}\n"
                f"Items: {', '.join(placed)}{d_admin}"
            )
            buyer_note = (
                "📍 A delivery agent will contact you to arrange delivery. 🚚"
                if delivery_type == "delivery"
                else "🏪 Please collect your order from the seller."
            )
            return (
                f"✅ *Payment Confirmed!*\n\n"
                f"Reference : *{ref}*\n"
                f"Total     : *${total:.2f}*\n\n"
                f"{buyer_note}\n\n"
                "Reply *my orders* to track your orders.\n_Reply *0* for the main menu._"
            )
        return "Reply *paid* once you've completed the EcoCash payment, or *0* to cancel."

    # ── Dispute flow ──────────────────────────────────────────────────────────
    if state == "ctx_dispute_type":
        issue_types = {
            "1": "Item not received",
            "2": "Wrong item delivered",
            "3": "Item damaged or defective",
            "4": "Service not rendered",
            "5": "Other issue",
        }
        if msg_text in issue_types:
            data["issue_type"] = issue_types[msg_text]
            set_session(phone, "ctx_dispute_desc", data)
            return (
                f"📋 *{data['issue_type']}*\n\n"
                "Please describe your issue in detail:\n"
                "_Include order reference if you have it_\n\n"
                "_Reply *0* to cancel._"
            )
        return (
            "🆘 *What is the issue?*\n\n"
            "1️⃣  — Item not received\n"
            "2️⃣  — Wrong item delivered\n"
            "3️⃣  — Item damaged or defective\n"
            "4️⃣  — Service not rendered\n"
            "5️⃣  — Other issue\n"
            "0️⃣  — Cancel"
        )

    if state == "ctx_dispute_desc":
        issue_type = data.get("issue_type", "Other")
        dispute_id, ref = create_dispute(phone, issue_type, msg_text)
        notify_admin(
            f"🆘 *New Dispute — {ref}*\n\n"
            f"From   : {phone}\n"
            f"Issue  : {issue_type}\n"
            f"Detail : {msg_text}\n\n"
            f"➡ Reply *resolve {ref}* with resolution to close."
        )
        clear_session(phone)
        return (
            f"✅ *Dispute Submitted — {ref}*\n\n"
            f"Issue  : {issue_type}\n\n"
            "Our team will review and respond within *24 hours*. 🕐\n\n"
            "_Reply *0* for the main menu._"
        )

    # ── Registration flow ─────────────────────────────────────────────────────
    # Old WhatsApp chat-based registration states — redirect to web form
    if state in ("reg_name", "reg_business", "reg_location", "reg_kyc"):
        clear_session(phone)
        reg_link = f"{BASE_URL}/register"
        return (
            "📝 *Seller Registration*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Registration now requires uploading your ID photo for verification.\n\n"
            f"Please complete your registration at:\n🔗 {reg_link}\n\n"
            "_Reply *0* for the main menu._"
        )

    # ── Quote flow ────────────────────────────────────────────────────────────
    if state == "awaiting_name":
        data["name"] = msg_text.title()
        set_session(phone, "awaiting_product", data)
        return f"Thanks, *{data['name']}*! 👋\n\nWhat *product or service* are you enquiring about?"

    if state == "awaiting_product":
        data["product"] = msg_text
        set_session(phone, "awaiting_location", data)
        return "Got it! What is your *location* (city or area)?"

    if state == "awaiting_location":
        data["location"] = msg_text.title()
        clear_session(phone)
        notify_admin(
            f"📋 *New Quote Request*\n\n"
            f"From    : {phone}\n"
            f"Name    : {data.get('name')}\n"
            f"Item    : {data.get('product')}\n"
            f"Location: {data['location']}"
        )
        return (
            f"✅ Thank you, *{data['name']}*!\n\n"
            f"• Item    : {data['product']}\n"
            f"• Location: {data['location']}\n\n"
            "Our team will contact you within *24 hours*. 🕐\n\n"
            "_Reply *0* for the main menu._"
        )

    # ── Order flow ────────────────────────────────────────────────────────────
    if state == "buy_qty":
        if not msg_text.isdigit() or int(msg_text) < 1:
            return "Please enter a valid quantity (e.g. *1*)."
        qty     = int(msg_text)
        product = get_product_by_id(data["product_id"])
        if not product:
            clear_session(phone)
            return "❌ Product no longer available.\n\n_Reply *0* for the main menu._"
        if qty > product["stock_qty"]:
            return f"❌ Only *{product['stock_qty']}* units available. Please try again."
        data["qty"]   = qty
        data["total"] = round(product["price"] * qty, 2)
        set_session(phone, "buy_confirm", data)
        return (
            f"🛒 *Order Summary*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Product : {product['name']}\n"
            f"Qty     : {qty}\n"
            f"Price   : ${product['price']:.2f} each\n"
            f"*Total  : ${data['total']:.2f}*\n\n"
            "1️⃣  — ✅ *Confirm order*\n"
            "0️⃣  — ❌ Cancel\n\n"
            "_Reply *1* to confirm or *0* to cancel._"
        )

    if state == "buy_confirm":
        if msg_text != "1" and msg_text != "confirm":
            return "Reply *1* to confirm your order or *0* to cancel."
        product = get_product_by_id(data["product_id"])
        if not product:
            clear_session(phone)
            return "❌ Product no longer available."
        set_session(phone, "buy_delivery", data)
        return (
            "🚚 *Delivery Options*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "How would you like to receive your order?\n\n"
            "1️⃣  — 🚚 Delivery (send to me)\n"
            "2️⃣  — 🏪 Self-collect (I'll pick it up)\n\n"
            "_Reply *0* to cancel._"
        )

    if state == "buy_delivery":
        if msg_text == "1":   # Delivery — ask for address
            set_session(phone, "buy_delivery_addr", data)
            return (
                "📍 *Your Delivery Address*\n\n"
                "Please enter your delivery address:\n\n"
                "_e.g. 123 Main Street, Harare CBD_\n\n"
                "_Reply *0* to cancel._"
            )
        if msg_text == "2":   # Self-collect
            return _place_single_order(phone, data, "self_collect", "")
        return (
            "🚚 *Delivery Options*\n\n"
            "1️⃣  — 🚚 Delivery\n"
            "2️⃣  — 🏪 Self-collect\n"
            "_Reply *0* to cancel._"
        )

    if state == "buy_delivery_addr":
        delivery_address = msg_text.strip()
        if len(delivery_address) < 5:
            return "Please provide a valid delivery address (at least 5 characters).\n\n_e.g. 123 Main Street, Harare CBD_"
        return _place_single_order(phone, data, "delivery", delivery_address)

    # ── Delivery agent registration flow ──────────────────────────────────────
    if state == "del_reg_name":
        data["name"] = msg_text.title()
        set_session(phone, "del_reg_vehicle", data)
        return (
            f"Nice to meet you, *{data['name']}*! 🚚\n\n"
            "What type of vehicle do you use for deliveries?\n\n"
            "1️⃣  — 🛵 Motorbike\n"
            "2️⃣  — 🚗 Car\n"
            "3️⃣  — 🚲 Bicycle\n"
            "4️⃣  — 🚶 On foot (local only)\n\n"
            "_Reply *0* to cancel._"
        )

    if state == "del_reg_vehicle":
        vehicles = {"1": "Motorbike", "2": "Car", "3": "Bicycle", "4": "On foot"}
        if msg_text not in vehicles:
            return "Reply with *1*, *2*, *3*, or *4* to select your vehicle type."
        data["vehicle_type"] = vehicles[msg_text]
        set_session(phone, "del_reg_area", data)
        return (
            "📍 *Your Service Area*\n\n"
            "Which city or area will you be delivering in?\n\n"
            "_e.g. Harare, Bulawayo, Mutare_\n\n"
            "_Reply *0* to cancel._"
        )

    if state == "del_reg_area":
        data["service_area"] = msg_text.title()
        register_delivery_person(phone, data["name"], data["vehicle_type"], data["service_area"])
        clear_session(phone)
        notify_admin(
            f"🚚 *New Delivery Agent Application*\n\n"
            f"Name   : {data['name']}\n"
            f"Vehicle: {data['vehicle_type']}\n"
            f"Area   : {data['service_area']}\n"
            f"Phone  : {phone}\n\n"
            f"➡ *approve delivery {phone}* or *reject delivery {phone}*"
        )
        return (
            f"✅ Thank you, *{data['name']}*!\n\n"
            "Your delivery agent application has been submitted.\n"
            "We'll notify you within *24 hours*. 🕐\n\n"
            "_Reply *0* for the main menu._"
        )

    clear_session(phone)
    return DEFAULT_RESPONSE


# ── Reusable action helpers ───────────────────────────────────────────────────

def _handle_register(phone):
    seller = get_seller(phone)
    if seller and seller["status"] == "approved":
        return "✅ You already have an active seller account.\n\nReply *2* to list a product.\n\n_Reply *0* to go back._"
    if seller and seller["status"] == "pending":
        return "⏳ Your application is still under review. We'll notify you soon.\n\n_Reply *0* to go back._"
    reg_link = f"{BASE_URL}/register"
    return (
        "📝 *Seller Registration*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "To register as a seller, open the link below and fill in your details.\n"
        "You will also need to upload a photo of your *ID* and a *selfie* for verification.\n\n"
        f"🔗 {reg_link}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⏱️ Once submitted, we'll review your application and notify you here within *24 hours*.\n\n"
        "_Reply *0* to go back._"
    )


def _check_seller_approved(phone):
    """Returns (seller, error_msg). error_msg is None if approved."""
    seller = get_seller(phone)
    if not seller:
        return None, (
            "You need a seller account first.\n\n"
            f"Register here (takes 2 minutes):\n🔗 {BASE_URL}/register\n\n"
            "_Reply *0* to go back._"
        )
    if seller["status"] == "pending":
        return seller, (
            "⏳ Your account is still under review.\n\n"
            "We'll notify you on WhatsApp within 24 hours once approved.\n\n"
            "_Reply *0* to go back._"
        )
    if seller["status"] == "rejected":
        return seller, (
            "❌ Your application was not approved.\n\n"
            f"You can re-apply at:\n🔗 {BASE_URL}/register\n\n"
            f"📧 {get_setting('contact_email', 'terrencemuromba@gmail.com')}\n"
            f"📞 {get_setting('contact_phone', '+263 77 412 8219')}\n\n"
            "_Reply *0* to go back._"
        )
    if seller["status"] == "suspended":
        return seller, (
            "⚠️ Your seller account has been *suspended*.\n\n"
            "Contact us to resolve this:\n"
            f"📧 {get_setting('contact_email', 'terrencemuromba@gmail.com')}\n"
            f"📞 {get_setting('contact_phone', '+263 77 412 8219')}\n\n"
            "_Reply *0* to go back._"
        )
    return seller, None


def _place_single_order(phone, data, delivery_type, delivery_address):
    """Place a single-item order (direct buy flow) and return the confirmation message."""
    product = get_product_by_id(data["product_id"])
    if not product:
        clear_session(phone)
        return "❌ Product no longer available.\n\n_Reply *0* for the main menu._"
    order_id, ref, total = create_order(
        buyer_phone=phone,
        product_id=data["product_id"],
        quantity=data["qty"],
        unit_price=product["price"],
        delivery_type=delivery_type,
        delivery_address=delivery_address,
    )
    update_stock(product["id"], product["stock_qty"] - data["qty"])
    clear_session(phone)

    d_note = (
        f"\n📍 Deliver to: {delivery_address}"
        if delivery_type == "delivery" else "\n🏪 Buyer will self-collect."
    )
    if product["listed_by"]:
        send_whatsapp_message(
            product["listed_by"],
            f"🛒 *New Order!*\n\n"
            f"Ref    : *{ref}*\n"
            f"Item   : {product['name']}\n"
            f"Qty    : {data['qty']}  |  Revenue: ${total:.2f}\n"
            f"Buyer  : {phone}{d_note}"
        )
    notify_admin(
        f"📦 *New Order* — {ref}\n"
        f"Item: {product['name']} x{data['qty']}  |  ${total:.2f}\n"
        f"Buyer: {phone}{d_note}"
    )
    buyer_note = (
        "📍 A delivery agent will contact you to arrange delivery. 🚚"
        if delivery_type == "delivery"
        else "🏪 Please collect your order from the seller."
    )
    return (
        f"✅ *Order Confirmed!*\n\n"
        f"📌 Reference: *{ref}*\n"
        f"Item  : {product['name']}\n"
        f"Qty   : {data['qty']}  |  Total: *${total:.2f}*\n\n"
        f"{buyer_note}\n\n"
        "_Reply *0* for the main menu._"
    )


def _handle_sell_product(phone):
    seller, err = _check_seller_approved(phone)
    if err:
        return err
    token = create_vendor_token(phone)
    link  = f"{BASE_URL}/list-product?token={token}"
    return (
        "🔗 *Your Product Listing Link:*\n\n"
        f"{link}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📌 Upload a clear photo for faster approval.\n"
        "💰 10% commission charged on approval.\n"
        "⏱️ Link expires in *30 minutes* (one use only).\n\n"
        "_Reply *0* to go back._"
    )


def _handle_offer_service(phone):
    seller, err = _check_seller_approved(phone)
    if err:
        return err
    set_session(phone, "svc_offer_title", {})
    return (
        "🔧 *List Your Service*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Let's set up your service listing step by step.\n\n"
        "What is the *title* of your service?\n"
        "_e.g. Plumbing Repairs, CCTV Installation, Tutoring_\n\n"
        "_Reply *0* to cancel._"
    )


# ── Admin commands ────────────────────────────────────────────────────────────

# ── Admin action helpers ──────────────────────────────────────────────────────

_admin_phone_ctx = None  # set by handle_admin before calling helpers

def _log(action, target_type="", target_id="", detail=""):
    if _admin_phone_ctx:
        log_admin_action(_admin_phone_ctx, action, target_type, str(target_id), detail)


def _approve_seller(seller_phone):
    seller = get_seller(seller_phone)
    if not seller:
        return "❌ No seller found with that phone number."
    set_seller_status(seller_phone, "approved")
    _log("approve_seller", "seller", seller_phone, seller.get("name", ""))
    send_whatsapp_message(
        seller_phone,
        f"🎉 *Congratulations, {seller['name']}!*\n\n"
        f"Your seller account for *{seller['business_name']}* is now *approved*. ✅\n\n"
        "📌 *Here's how to start selling:*\n\n"
        "1️⃣  Message us on WhatsApp (this chat)\n"
        "2️⃣  Reply *3* from the main menu → *Sell / Offer Services*\n"
        "3️⃣  Reply *2* to list a product  —or—  *3* to offer a service\n"
        "4️⃣  Fill in the form and your listing goes live after review!\n\n"
        "💰 Commission: 10% on each approved listing.\n\n"
        "_Reply *0* for the main menu._"
    )
    return f"✅ *{seller['name']}* ({seller['business_name']}) approved. Seller notified."


def _reject_seller(seller_phone, reason=""):
    seller = get_seller(seller_phone)
    if not seller:
        return "❌ No seller found with that phone number."
    set_seller_status(seller_phone, "rejected")
    _log("reject_seller", "seller", seller_phone,
         f"{seller.get('name', '')} — {reason}" if reason else seller.get("name", ""))
    reg_link = f"{BASE_URL}/register"
    reason_line = f"Reason: _{reason}_\n\n" if reason else ""
    send_whatsapp_message(
        seller_phone,
        f"❌ *{seller['name']}*, your seller application was not approved.\n\n"
        f"{reason_line}"
        "You may re-apply after correcting the issue:\n"
        f"🔗 {reg_link}\n\n"
        "Make sure your ID photo is clear and your selfie shows your face and ID together.\n\n"
        "For help contact us:\n"
        f"📧 {get_setting('contact_email', 'terrencemuromba@gmail.com')}\n"
        f"📞 {get_setting('contact_phone', '+263 77 412 8219')}\n\n"
        "_Reply *0* for the main menu._"
    )
    return f"❌ *{seller['name']}* rejected. Seller notified."


def _suspend_seller(seller_phone):
    seller = get_seller(seller_phone)
    if not seller:
        return "❌ No seller found."
    set_seller_status(seller_phone, "suspended")
    _log("suspend_seller", "seller", seller_phone, seller.get("name", ""))
    send_whatsapp_message(
        seller_phone,
        f"⚠️ *{seller['name']}*, your T-Tech Connect seller account has been *suspended*.\n\n"
        "You will not be able to list new products or services until your account is reinstated.\n\n"
        "Contact us for more information:\n"
        f"📧 {get_setting('contact_email', 'terrencemuromba@gmail.com')}\n"
        f"📞 {get_setting('contact_phone', '+263 77 412 8219')}\n\n"
        "_Reply *0* for the main menu._"
    )
    return f"⚠️ *{seller['name']}* suspended. Seller notified."


def _approve_product(product_id):
    product = get_product_by_id(product_id)
    if not product:
        return "❌ No product found with that ID."
    set_product_status(product["id"], "approved")
    _log("approve_product", "product", product_id, product["name"])
    if product["listed_by"]:
        send_whatsapp_message(
            product["listed_by"],
            f"🎉 Your product *{product['name']}* is now *live* on T-Tech Connect!\n\n"
            f"💰 Commission due: *${product['commission']:.2f}*\n"
            "Pay via EcoCash to *+263 77 412 8219* and send proof of payment.\n\n"
            "_Reply *0* for the main menu._"
        )
    # Auto-post to Facebook if enabled
    fb_id = auto_post_product(dict(product))
    fb_note = f" (FB post: {fb_id})" if fb_id else ""
    # Notify newsletter subscribers about new product
    _notify_newsletter_new_product(dict(product))
    return f"✅ *{product['name']}* approved and live.{fb_note}"


def _reject_product(product_id, reason):
    product = get_product_by_id(product_id)
    if not product:
        return "❌ Product not found."
    set_product_status(product["id"], "rejected", reason)
    _log("reject_product", "product", product_id, f"{product['name']} — {reason}")
    if product["listed_by"]:
        send_whatsapp_message(
            product["listed_by"],
            f"❌ Your product *{product['name']}* was not approved.\n\n"
            f"Reason: _{reason}_\n\n"
            "Fix the issue and reply *sell* to try again.\n\n"
            "_Reply *0* for the main menu._"
        )
    return f"❌ *{product['name']}* rejected. Seller notified."


def _remove_product(product_id):
    product = get_product_by_id(product_id)
    if not product:
        return "❌ Product not found."
    set_product_status(product["id"], "rejected", "Removed by admin.")
    if product["listed_by"]:
        send_whatsapp_message(
            product["listed_by"],
            f"⚠️ Your listing *{product['name']}* has been *removed* by T-Tech Connect admin.\n\n"
            "Contact us if you believe this was an error:\n"
            "📞 +263 77 412 8219"
        )
    return f"🗑️ *{product['name']}* removed."


# ── Admin dashboard builder ────────────────────────────────────────────────────

def build_admin_dashboard(phone):
    s            = get_admin_stats()
    pending_svcs = len(get_pending_services())
    prod_rate    = get_setting("commission_rate", "10")
    svc_rate     = get_setting("service_commission_rate", "10")
    dashboard = (
        f"🔧 *Admin Panel — T-Tech Connect*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 *Live Overview:*\n"
        f"• ⏳ Pending sellers   : {s['pending_sellers']}\n"
        f"• ✅ Approved sellers  : {s['approved_sellers']}\n"
        f"• ⏳ Pending products  : {s['pending_products']}\n"
        f"• ✅ Live products     : {s['approved_products']}\n"
        f"• ⏳ Pending services  : {pending_svcs}\n"
        f"• 🛒 Total orders      : {s['total_orders']}\n"
        f"• 💰 Total revenue     : ${s['total_revenue']:.2f}\n"
        f"• 🏠 New enquiries     : {s['new_enquiries']}\n"
        f"• 👥 Unique users      : {s['unique_users']}\n\n"
        f"⚙️ *Commission Rates:*\n"
        f"• Products : *{prod_rate}%*\n"
        f"• Services : *{svc_rate}%*\n\n"
        f"*Select an action:*\n\n"
        f"1️⃣  — 👤 Manage Sellers\n"
        f"2️⃣  — 📦 Manage Products\n"
        f"3️⃣  — 🔧 Manage Services\n"
        f"4️⃣  — 🛒 View Orders\n"
        f"5️⃣  — 🏠 Enquiries\n"
        f"6️⃣  — 📢 Broadcast Message\n"
        f"7️⃣  — ⚙️ Commission Settings\n"
        f"0️⃣  — Exit admin panel\n\n"
        f"_Reply *1–7* to select_"
    )
    set_session(phone, "ctx_admin", {})
    return dashboard


# ── Admin menu handler ────────────────────────────────────────────────────────

def _notify_newsletter_new_product(product):
    """Push new approved product to newsletter subscribers."""
    phones = get_newsletter_phones()
    if not phones:
        return
    msg = (
        f"🛍️ *New on T-Tech Connect!*\n\n"
        f"*{product['name']}*\n"
        f"📦 {product['category']}  |  💰 ${product['price']:.2f}\n"
        f"{(product.get('description') or '')[:100]}\n\n"
        f"Reply *search {product['name'].split()[0]}* to find it.\n"
        "_Reply *unsubscribe* to stop these alerts._"
    )
    for p in phones:
        send_whatsapp_message(p, msg)


def handle_admin(msg_text, phone):
    global _admin_phone_ctx
    _admin_phone_ctx = phone   # allow helpers to log actions

    if msg_text in ("admin", "panel", "dashboard"):
        return build_admin_dashboard(phone)

    # Quick shortcut commands
    if msg_text == "sellers":
        return _show_sellers_list(phone, status="pending")
    if msg_text == "pending":
        return _show_products_list(phone, status="pending")

    if msg_text in ("analytics", "stats", "report"):
        s    = get_analytics_summary(days=7)
        top  = "\n".join(f"  {i+1}. {p['name']} ({p['cnt']} orders, ${p['revenue']:.2f})"
                         for i, p in enumerate(s["top_products"])) or "  No orders yet"
        hrs  = ", ".join(f"{h['hour']:02d}:00" for h in s["peak_hours"]) or "N/A"
        return (
            f"📊 *Analytics — Last 7 Days*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💰 Revenue        : ${s['total_revenue']:.2f}\n"
            f"🛒 Orders         : {s['total_orders']}\n"
            f"👥 New users      : {s['new_users']}\n"
            f"📦 New listings   : {s['new_listings']}\n"
            f"🔧 New services   : {s['new_services']}\n"
            f"🆘 Open disputes  : {s['open_disputes']}\n"
            f"📧 Newsletter subs: {s['newsletter_count']}\n\n"
            f"🏆 *Top Products:*\n{top}\n\n"
            f"⏰ *Peak Hours:* {hrs}\n\n"
            f"View full dashboard: {BASE_URL}/admin/analytics"
        )

    if msg_text.startswith("resolve "):
        ref = msg_text[8:].strip().upper()
        from db import get_connection
        conn = get_connection()
        row  = conn.execute("SELECT * FROM disputes WHERE reference = ?", (ref,)).fetchone()
        conn.close()
        if not row:
            return f"❌ No dispute found with reference *{ref}*."
        from db import update_dispute
        update_dispute(row["id"], "resolved", "Resolved by admin")
        send_whatsapp_message(
            row["buyer_phone"],
            f"✅ *Your dispute {ref} has been resolved.*\n\n"
            "Thank you for your patience. If you have further concerns, please contact us.\n\n"
            "_Reply *0* for the main menu._"
        )
        log_admin_action(phone, "resolve_dispute", "dispute", ref)
        return f"✅ Dispute *{ref}* marked as resolved. Buyer notified."

    if msg_text.startswith("newsletter "):
        # newsletter <message to send>
        message = msg_text[11:].strip()
        phones  = get_newsletter_phones()
        if not phones:
            return "📭 No newsletter subscribers yet."
        broadcast = (
            f"📢 *T-Tech Connect Newsletter*\n\n"
            f"{message}\n\n"
            "_Reply *unsubscribe* to opt out._"
        )
        for p in phones:
            send_whatsapp_message(p, broadcast)
        log_admin_action(phone, "newsletter_send", "", f"{len(phones)} recipients")
        return f"✅ Newsletter sent to *{len(phones)}* subscribers."

    # ── Delivery agent management ─────────────────────────────────────────────
    if msg_text == "delivery agents":
        rows = get_pending_delivery_personnel()
        if not rows:
            return "✅ No pending delivery agent applications.\n\n_Reply *0* to go back._"
        lines = [f"🚚 *Pending Delivery Agents ({len(rows)}):*\n"]
        for dp in rows[:9]:
            lines.append(
                f"• *{dp['name']}* — {dp['vehicle_type']} — {dp['service_area']}\n"
                f"  📞 {dp['phone']}\n"
            )
        lines.append("_*approve delivery <phone>* or *reject delivery <phone>*_")
        return "\n".join(lines)

    if msg_text.startswith("approve seller "):
        seller_phone = msg_text[15:].strip()
        return _approve_seller(seller_phone)

    if msg_text.startswith("reject seller "):
        parts        = msg_text[14:].strip().split(maxsplit=1)
        seller_phone = parts[0]
        reason       = parts[1] if len(parts) > 1 else ""
        return _reject_seller(seller_phone, reason)

    if msg_text.startswith("approve delivery "):
        dp_phone = msg_text[17:].strip()
        dp = get_delivery_person(dp_phone)
        if not dp:
            return f"❌ No delivery agent found with phone *{dp_phone}*."
        set_delivery_person_status(dp_phone, "approved")
        send_whatsapp_message(
            dp_phone,
            f"🎉 *Congratulations, {dp['name']}!*\n\n"
            "Your delivery agent application has been *approved*! 🚚\n\n"
            "Reply *my deliveries* to see pending deliveries in your area.\n\n"
            "_Reply *0* for the main menu._"
        )
        log_admin_action(phone, "approve_delivery", "delivery_personnel", dp_phone)
        return f"✅ Delivery agent *{dp['name']}* ({dp_phone}) approved."

    if msg_text.startswith("reject delivery "):
        dp_phone = msg_text[16:].strip()
        dp = get_delivery_person(dp_phone)
        if not dp:
            return f"❌ No delivery agent found with phone *{dp_phone}*."
        set_delivery_person_status(dp_phone, "rejected")
        send_whatsapp_message(
            dp_phone,
            "❌ *Your delivery agent application was not approved.*\n\n"
            "Contact us for more information:\n"
            f"📧 {get_setting('contact_email', '')}\n"
            "_Reply *0* for the main menu._"
        )
        log_admin_action(phone, "reject_delivery", "delivery_personnel", dp_phone)
        return f"❌ Delivery agent *{dp['name']}* ({dp_phone}) rejected."

    # Approve / reject a service listing
    if msg_text.startswith("approve service "):
        svc_id = msg_text[16:].strip()
        if svc_id.isdigit():
            svc = get_service(int(svc_id))
            if not svc:
                return f"❌ No service found with ID *{svc_id}*."
            set_service_status(int(svc_id), "approved")
            if svc.get("provider_phone"):
                send_whatsapp_message(
                    svc["provider_phone"],
                    f"🎉 Your service *{svc['title']}* is now *live* on T-Tech Connect!\n\n"
                    "Customers can now find and enquire about your service.\n\n"
                    "_Reply *0* for the main menu._"
                )
            fb_id = auto_post_service(svc)
            fb_note = f" (FB post: {fb_id})" if fb_id else ""
            return f"✅ *{svc['title']}* approved and live.{fb_note}"

    if msg_text.startswith("reject service "):
        parts = msg_text[15:].strip().split(maxsplit=1)
        if parts and parts[0].isdigit():
            svc    = get_service(int(parts[0]))
            reason = parts[1] if len(parts) > 1 else "Does not meet listing requirements."
            if not svc:
                return f"❌ No service found with ID *{parts[0]}*."
            set_service_status(int(parts[0]), "rejected", reason)
            if svc.get("provider_phone"):
                send_whatsapp_message(
                    svc["provider_phone"],
                    f"❌ Your service *{svc['title']}* was not approved.\n\n"
                    f"Reason: _{reason}_\n\n"
                    "Fix the issue and try again from the Sell menu.\n\n"
                    "_Reply *0* for the main menu._"
                )
            return f"❌ *{svc['title']}* rejected. Provider notified."

    return None


def _show_sellers_list(phone, status=None, title=None):
    rows    = get_all_sellers_admin(status) if status != "pending" else get_pending_sellers()
    sellers = [dict(r) for r in rows[:9]]
    if not sellers:
        label = status or "any"
        return f"✅ No {label} sellers found.\n\n_Reply *0* to go back._"
    head  = title or f"👤 *{'Pending' if status == 'pending' else 'Approved'} Sellers ({len(sellers)}):*"
    lines = [head + "\n"]
    for i, r in enumerate(sellers):
        badge = {"approved": "✅", "pending": "⏳", "rejected": "❌"}.get(r.get("status", ""), "•")
        lines.append(
            f"{NUM_EMOJI[i]} {badge} *{r['name']}* — {r['business_name']}\n"
            f"    📞 {r['phone']}\n"
        )
    lines.append("_Reply with a number to action | *0* to go back_")
    set_session(phone, "ctx_admin_sellers", {"sellers": sellers, "mode": status or "all"})
    return "\n".join(lines)


def _show_products_list(phone, status=None, title=None):
    rows     = [dict(r) for r in (get_pending_products() if status == "pending"
                else get_all_products_admin(status))[:9]]
    if not rows:
        return f"✅ No {'pending' if status == 'pending' else ''} products found.\n\n_Reply *0* to go back._"
    head  = title or f"📦 *{'Pending' if status == 'pending' else 'All'} Products ({len(rows)}):*"
    lines = [head + "\n"]
    for i, r in enumerate(rows):
        badge = {"approved": "✅", "pending": "⏳", "rejected": "❌"}.get(r.get("status", ""), "•")
        lines.append(
            f"{NUM_EMOJI[i]} {badge} *{r['name']}*\n"
            f"    {r.get('business_name') or r.get('listed_by', 'N/A')}  |  💰 ${r['price']:.2f}\n"
        )
    lines.append("_Reply with a number to action | *0* to go back_")
    set_session(phone, "ctx_admin_products", {"products": rows, "mode": status or "all"})
    return "\n".join(lines)


# ── Main message router ───────────────────────────────────────────────────────

def handle_message(phone, msg_text):

    if msg_text == "reset":
        return go_welcome(phone)

    # Active session (includes all menu contexts and action flows)
    session = get_session(phone)
    if session:
        return handle_session(phone, msg_text, session)

    # Greetings and global nav — no active session
    if any(word in msg_text for word in GREETING_WORDS):
        return WELCOME

    if msg_text in ("menu", "home", "back"):
        return WELCOME

    # Main menu numbers — set context so sub-navigation works
    if msg_text == "1":
        return go_buyer_menu(phone)
    if msg_text == "2":
        return go_find_service_menu(phone)
    if msg_text == "3":
        return go_seller_menu(phone)
    if msg_text == "4":
        return go_accommodation_menu(phone)
    if msg_text == "5":
        return get_contact_response()

    # Admin
    if phone == ADMIN_PHONE:
        reply = handle_admin(msg_text, phone)
        if reply:
            return reply

    # Staff stock update
    if phone in VENDOR_NUMBERS and msg_text.startswith("update "):
        parts = msg_text.split()
        if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
            product = get_product_by_id(int(parts[1]))
            if not product:
                return f"❌ No product with ID *{parts[1]}*."
            old = product["stock_qty"]
            new = int(parts[2])
            update_stock(product["id"], new)
            if old == 0 and new > 0:
                notify_waitlist(product["id"], product["name"])
            return f"✅ *{product['name']}* stock: {old} → {new}"
        return "Usage: *update <product_id> <quantity>*"

    # Keyword shortcuts (backward compat + power users)
    if msg_text == "contact":
        return get_contact_response()

    # ── Cart commands ─────────────────────────────────────────────────────────
    if msg_text == "cart":
        set_session(phone, "ctx_cart", {})
        return format_cart(get_cart(phone))

    if msg_text == "checkout":
        items = get_cart(phone)
        if not items:
            return "🛒 Your cart is empty.\n\nBrowse products and add items first.\n\n_Reply *0* for the main menu._"
        total = get_cart_total(phone)
        set_session(phone, "ctx_checkout_delivery", {"total": total})
        return (
            f"🚚 *Delivery Options*\n\n"
            f"Order total: *${total:.2f}*\n\n"
            f"1️⃣  — 🚚 Delivery (send to me)\n"
            f"2️⃣  — 🏪 Self-collect (I'll pick it up)\n"
            f"0️⃣  — Back to cart"
        )

    if msg_text.startswith("add "):
        pid_str = msg_text[4:].strip()
        if pid_str.isdigit():
            product = get_product_by_id(int(pid_str))
            if product and product["status"] == "approved" and product["stock_qty"] > 0:
                add_to_cart(phone, product["id"], 1)
                cart_count = len(get_cart(phone))
                return (
                    f"✅ *{product['name']}* added to cart!\n\n"
                    f"🛒 You have *{cart_count}* item(s) in your cart.\n\n"
                    "Reply *cart* to view  |  *checkout* to order\n"
                    "_Reply *0* for the main menu._"
                )
            if product and product["stock_qty"] == 0:
                return f"❌ *{product['name']}* is out of stock.\n\nReply *notify {product['id']}* to be alerted when it's back."
        return "❌ Invalid product ID. Find product IDs in search results."

    # ── Dispute / issue ───────────────────────────────────────────────────────
    if msg_text in ("rate product", "review product", "leave review"):
        orders = get_fulfilled_orders_for_buyer(phone)
        if not orders:
            return (
                "😕 No delivered orders to review yet.\n\n"
                "You can only rate products that have been delivered.\n\n"
                "_Reply *0* for the main menu._"
            )
        lines = ["⭐ *Which product would you like to rate?*\n"]
        for i, o in enumerate(orders):
            lines.append(f"{NUM_EMOJI[i]}  *{o['product_name']}*\n    Order: {o['reference']}\n")
        lines.append("_Reply with a number | *0* to cancel_")
        set_session(phone, "prod_review_select", {"orders": orders})
        return "\n".join(lines)

    # ── Delivery agent registration ───────────────────────────────────────────
    if msg_text in ("delivery agent", "become delivery agent", "courier",
                    "register courier", "register delivery", "join delivery",
                    "delivery personnel"):
        dp = get_delivery_person(phone)
        if dp and dp["status"] == "approved":
            return (
                "✅ You are already a registered delivery agent.\n\n"
                "Reply *my deliveries* to see pending deliveries in your area.\n\n"
                "_Reply *0* for the main menu._"
            )
        if dp and dp["status"] == "pending":
            return "⏳ Your delivery agent application is still under review. We'll notify you soon."
        set_session(phone, "del_reg_name")
        return (
            "🚚 *Delivery Agent Registration*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "What is your *full name*?\n\n"
            "_Reply *0* to cancel._"
        )

    if msg_text in ("my deliveries", "pending deliveries"):
        dp = get_delivery_person(phone)
        if not dp or dp["status"] != "approved":
            return (
                "❌ You are not a registered delivery agent.\n\n"
                "Text *delivery agent* to register.\n\n"
                "_Reply *0* for the main menu._"
            )
        orders = get_delivery_orders(dp["service_area"])
        if not orders:
            return (
                f"📭 No pending deliveries in *{dp['service_area']}* right now.\n\n"
                "_Reply *0* for the main menu._"
            )
        lines = [f"🚚 *Pending Deliveries — {dp['service_area']}:*\n"]
        for r in orders:
            lines.append(
                f"• *{r['reference']}*\n"
                f"  Item   : {r['product_name']}\n"
                f"  Address: {r['delivery_address']}\n"
                f"  Buyer  : {r['buyer_phone']}\n"
            )
        contact = get_setting("contact_phone", "")
        lines.append(f"\n_Contact admin to be assigned: {contact}_")
        return "\n".join(lines)

    if msg_text in ("issue", "dispute", "problem", "complaint"):
        set_session(phone, "ctx_dispute_type", {})
        return (
            "🆘 *Report an Issue*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "What is the issue?\n\n"
            "1️⃣  — Item not received\n"
            "2️⃣  — Wrong item delivered\n"
            "3️⃣  — Item damaged or defective\n"
            "4️⃣  — Service not rendered\n"
            "5️⃣  — Other\n\n"
            "_Reply *0* to cancel._"
        )

    if msg_text == "my disputes":
        disputes = get_buyer_disputes(phone)
        if not disputes:
            return "✅ You have no open disputes.\n\n_Reply *0* for the main menu._"
        lines = ["🆘 *Your Disputes:*\n"]
        for d in disputes:
            icon = {"open": "🔴", "in_review": "🟡", "resolved": "🟢"}.get(d["status"], "•")
            lines.append(f"{icon} *{d['reference']}* — {d['issue_type']}\n    Status: {d['status'].title()}\n")
        lines.append("_Reply *0* for the main menu._")
        return "\n".join(lines)

    # ── Newsletter ────────────────────────────────────────────────────────────
    if msg_text == "subscribe":
        newsletter_subscribe(phone)
        return (
            "✅ *You're subscribed to T-Tech Connect deals!* 🎉\n\n"
            "You'll receive curated deals and new listings when they go live.\n\n"
            "Reply *unsubscribe* anytime to opt out.\n\n"
            "_Reply *0* for the main menu._"
        )

    if msg_text == "unsubscribe":
        newsletter_unsubscribe(phone)
        return (
            "✅ *Unsubscribed* — you won't receive promotional messages.\n\n"
            "Reply *subscribe* anytime to opt back in.\n\n"
            "_Reply *0* for the main menu._"
        )

    # ── Search ────────────────────────────────────────────────────────────────
    if msg_text.startswith("search "):
        query = msg_text[7:].strip()
        if len(query) < 2:
            return "Please enter at least *2 characters* to search.\nExample: *search laptop*"
        results = search_products(query)
        if results:
            product_data = [_to_dict(r) for r in results[:5]]
            set_session(phone, "ctx_results", {"products": product_data, "back": "buyer"})
            return format_numbered_products(product_data, title=f"🔍 *Results for \"{query}\":*")
        # NLP fallback — suggest a service category if it looks like a service request
        intent = detect_service_intent(query)
        if intent:
            services = get_services_by_category(intent)
            if services:
                set_session(phone, "ctx_svc_results", {"services": services})
                return (
                    f"😕 No products found for *{query}*.\n\n"
                    f"💡 Did you mean a *service*? We found providers in *{intent}*:\n\n"
                    + format_service_list(services, title=f"🔧 *{intent}:*")
                )
        return (
            f"😕 No results for *{query}*.\n\n"
            "Try a different keyword or reply *2* to find a service.\n\n"
            "_Reply *0* for the main menu._"
        )

    if msg_text.startswith("notify "):
        pid_str = msg_text[7:].strip()
        if pid_str.isdigit():
            product = get_product_by_id(int(pid_str))
            if product:
                add_to_waitlist(phone, product["id"])
                return f"🔔 We'll notify you when *{product['name']}* is back in stock. ✅\n\n_Reply *0* for the main menu._"
        return "❌ Invalid product ID."

    # ── NLP intent detection — free text ──────────────────────────────────────
    if len(msg_text) > 8:
        intent = detect_service_intent(msg_text)
        if intent:
            services = get_services_by_category(intent)
            if services:
                set_session(phone, "ctx_svc_results", {"services": services})
                return (
                    f"💡 It sounds like you need *{intent}*!\n\n"
                    + format_service_list(services, title=f"🔧 *{intent} Providers:*")
                )

    return DEFAULT_RESPONSE


# ── Flask routes ──────────────────────────────────────────────────────────────

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        mode      = request.args.get("hub.mode")
        token     = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return challenge, 200
        return "Forbidden", 403

    # Validate Meta's HMAC signature — rejects spoofed requests
    if not verify_webhook_signature(request):
        print("[SECURITY] Webhook signature mismatch — rejected")
        return "Forbidden", 403

    data = request.get_json(silent=True) or {}

    if data.get("object") == "whatsapp_business_account":
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                if "messages" not in value:
                    continue
                msg = value["messages"][0]
                if msg.get("type") != "text":
                    continue

                message_id   = msg.get("id", "")
                sender_phone = msg["from"]
                msg_text     = msg["text"]["body"].strip().lower()

                if message_id in _seen_message_ids:
                    continue
                _seen_message_ids.add(message_id)
                if len(_seen_message_ids) > 1000:
                    _seen_message_ids.clear()

                if is_rate_limited(sender_phone):
                    send_whatsapp_message(
                        sender_phone,
                        "⚠️ You're sending messages too quickly. Please wait a moment."
                    )
                    continue

                log_message(sender_phone, msg_text)
                mark_message_read(message_id)
                print(f"[IN] {sender_phone}: {msg_text}")

                try:
                    reply = handle_message(sender_phone, msg_text)
                except Exception as e:
                    print(f"[ERROR] {e}")
                    reply = "⚠️ Something went wrong. Reply *reset* to restart."

                send_whatsapp_message(sender_phone, reply)

    return jsonify({"status": "ok"}), 200


@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route("/product/<int:product_id>")
def product_detail_page(product_id):
    product = get_product_by_id(product_id)
    if not product or product["status"] != "approved":
        return "<h2 style='font-family:sans-serif;text-align:center;margin-top:60px'>Product not found.</h2>", 404
    product  = dict(product)
    reviews  = get_product_reviews(product_id, limit=5)
    avg, cnt = get_product_avg_rating(product_id)
    image_url = f"/uploads/{product['image_path']}" if product.get("image_path") else None
    wa_number = WA_BUSINESS_NUMBER or ADMIN_PHONE
    wa_link   = f"https://wa.me/{wa_number}?text=I+want+to+buy+{product['name'].replace(' ', '+')}"
    return render_template(
        "product_detail.html",
        product=product,
        image_url=image_url,
        reviews=reviews,
        avg_rating=avg,
        review_count=cnt,
        wa_link=wa_link,
    )


@app.route("/list-product", methods=["GET", "POST"])
def list_product():
    token = request.args.get("token", "")
    row   = validate_token(token)
    if not row:
        return "<h2>This link is invalid or has expired.</h2>", 403

    prod_rate = float(get_setting("commission_rate", "10"))
    svc_rate  = float(get_setting("service_commission_rate", "10"))

    if request.method == "GET":
        return render_template(
            "list_product.html",
            token=token, error=None,
            prod_rate=prod_rate, svc_rate=svc_rate,
        )

    # ── Parse multiple items from form arrays ─────────────────────────────────
    names        = request.form.getlist("item_name")
    categories   = request.form.getlist("item_category")
    prices_raw   = request.form.getlist("item_price")
    qtys_raw     = request.form.getlist("item_qty")
    descriptions = request.form.getlist("item_desc")
    types        = request.form.getlist("item_type")
    image_files  = request.files.getlist("item_image")

    if not names:
        return render_template(
            "list_product.html",
            token=token, error="Please add at least one item.",
            prod_rate=prod_rate, svc_rate=svc_rate,
        )

    seller      = get_seller(row["phone"])
    seller_name = seller["business_name"] if seller else row["phone"]
    submitted   = []
    errors      = []

    for i, name in enumerate(names):
        name = name.strip()
        if not name:
            errors.append(f"Item {i+1}: name is required.")
            continue

        category = categories[i].strip() if i < len(categories) else ""
        if not category:
            errors.append(f"Item {i+1}: category is required.")
            continue

        try:
            price = float(prices_raw[i])
            if price <= 0:
                raise ValueError
        except (ValueError, IndexError):
            errors.append(f"Item {i+1}: valid price required.")
            continue

        item_type = types[i] if i < len(types) else "product"
        image_path = None
        if i < len(image_files) and image_files[i].filename:
            image_path = save_image(image_files[i])

        desc = descriptions[i].strip() if i < len(descriptions) else ""

        if item_type == "service":
            # List as a service (no quantity)
            svc_id = add_service(
                title=name,
                category=category,
                description=desc,
                price_type="fixed",
                price=price,
                service_area="Zimbabwe",
                provider_phone=row["phone"],
                provider_name=seller["name"] if seller else "",
                provider_business=seller["business_name"] if seller else "",
            )
            comm = round(price * svc_rate / 100, 2)
            notify_admin(
                f"🔧 *New Service Pending #{svc_id}*\n\n"
                f"Title    : {name}\n"
                f"Category : {category}\n"
                f"Price    : ${price:.2f}  |  Commission: ${comm:.2f}\n"
                f"Seller   : {seller_name}\n\n"
                f"➡ *approve service {svc_id}* or *reject service {svc_id} <reason>*"
            )
            submitted.append({"name": name, "type": "service",
                               "price": price, "commission": comm, "id": svc_id})
        else:
            # List as a product
            try:
                qty = int(qtys_raw[i])
                if qty < 1:
                    qty = 1
            except (ValueError, IndexError):
                qty = 1

            product_id, comm = add_product(
                name=name, category=category, price=price,
                stock_qty=qty, description=desc,
                image_path=image_path, listed_by=row["phone"],
            )
            img_note = "🖼️ Image attached." if image_path else "📷 No image."
            notify_admin(
                f"📦 *New Product Pending #{product_id}*\n\n"
                f"Product  : {name}\n"
                f"Category : {category}\n"
                f"Price    : ${price:.2f} × {qty}  |  Commission: ${comm:.2f}\n"
                f"Seller   : {seller_name}  |  {img_note}\n\n"
                f"➡ *approve {product_id}* or *reject {product_id} <reason>*"
            )
            submitted.append({"name": name, "type": "product",
                               "price": price, "qty": qty, "commission": comm, "id": product_id})

    if errors and not submitted:
        return render_template(
            "list_product.html",
            token=token, error=" | ".join(errors),
            prod_rate=prod_rate, svc_rate=svc_rate,
        )

    mark_token_used(token)

    total_commission = sum(s["commission"] for s in submitted)
    return render_template(
        "success.html",
        submitted=submitted,
        total_commission=total_commission,
        seller_name=seller_name,
        partial_errors=errors,
    )


@app.route("/register", methods=["GET", "POST"])
def register_seller_web():
    if request.method == "GET":
        return render_template("register_seller.html",
                               success=False, error=None,
                               form={}, field_errors={})

    name          = request.form.get("name", "").strip()
    business_name = request.form.get("business_name", "").strip()
    phone_local   = request.form.get("phone_local", "").strip()
    country_code  = request.form.get("country_code", "263").strip()
    location      = request.form.get("location", "").strip()
    description   = request.form.get("description", "").strip()

    form = {
        "name": name, "business_name": business_name,
        "phone_local": phone_local, "country_code": country_code,
        "location": location, "description": description,
    }
    field_errors = {}

    if not name:
        field_errors["name"] = "Full name is required."
    if not business_name:
        field_errors["business_name"] = "Business name is required."
    if not location:
        field_errors["location"] = "Please select your city."

    # Normalise phone → international format (e.g. 263771234567)
    # Strip spaces, dashes, leading + so we work with digits only
    cleaned = phone_local.strip().replace(" ", "").replace("-", "").lstrip("+")
    # Remove country code if the user accidentally included it
    if cleaned.startswith(country_code):
        cleaned = cleaned[len(country_code):]
    # Remove any remaining leading zero (local format)
    cleaned = cleaned.lstrip("0")
    phone   = country_code + cleaned
    if not cleaned or not phone.isdigit() or len(phone) < 9:
        field_errors["phone"] = "Please enter a valid WhatsApp number."

    # Validate KYC uploads (both required)
    id_file      = request.files.get("id_photo")
    selfie_file  = request.files.get("selfie_photo")
    if not id_file or not id_file.filename:
        field_errors["id_photo"] = "Please upload a photo of your ID / passport."
    if not selfie_file or not selfie_file.filename:
        field_errors["selfie_photo"] = "Please upload a selfie holding your ID."

    if field_errors:
        return render_template("register_seller.html",
                               success=False, error=None,
                               form=form, field_errors=field_errors)

    existing = get_seller(phone)
    if existing and existing["status"] == "approved":
        return render_template("register_seller.html",
                               success=False,
                               error="This number is already registered and approved. "
                                     "Message us on WhatsApp to list your products.",
                               form=form, field_errors={})

    # Save KYC photos
    id_photo_path     = save_image(id_file)
    selfie_photo_path = save_image(selfie_file)

    if not id_photo_path:
        field_errors["id_photo"] = "Invalid file — use JPG, PNG or WEBP under 5 MB."
    if not selfie_photo_path:
        field_errors["selfie_photo"] = "Invalid file — use JPG, PNG or WEBP under 5 MB."
    if field_errors:
        return render_template("register_seller.html",
                               success=False, error=None,
                               form=form, field_errors=field_errors)

    register_seller(phone, name, business_name, location,
                    id_photo=id_photo_path, selfie_photo=selfie_photo_path)

    # Notify admin with text + KYC photos via WhatsApp
    notify_admin(
        f"📋 *New Seller Registration (Web)*\n\n"
        f"Name     : {name}\n"
        f"Business : {business_name}\n"
        f"Phone    : {phone}\n"
        f"Location : {location}\n"
        + (f"Sells    : {description[:200]}\n" if description else "")
        + f"\n📎 KYC photos follow below.\n\n"
        f"➡ *approve seller {phone}* or *reject seller {phone}*"
    )
    if ADMIN_PHONE:
        if id_photo_path:
            send_whatsapp_image(
                ADMIN_PHONE,
                f"{BASE_URL}/uploads/{id_photo_path}",
                caption=f"🪪 ID / Passport — {name} ({business_name})",
            )
        if selfie_photo_path:
            send_whatsapp_image(
                ADMIN_PHONE,
                f"{BASE_URL}/uploads/{selfie_photo_path}",
                caption=f"🤳 Selfie with ID — {name} | Phone: {phone}",
            )

    return render_template("register_seller.html",
                           success=True,
                           submitted_name=name,
                           submitted_business=business_name,
                           form={}, field_errors={})


# ── Web admin panel ───────────────────────────────────────────────────────────

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "ttech2024")

def admin_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect("/admin/login")
        return f(*args, **kwargs)
    return decorated


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect("/admin")
        return render_template("admin_login.html", error="Incorrect password.")
    if session.get("admin_logged_in"):
        return redirect("/admin")
    return render_template("admin_login.html", error=None)


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect("/admin/login")


@app.route("/admin")
@admin_required
def admin_dashboard():
    stats = get_admin_stats()
    return render_template("admin_dashboard.html", stats=stats, base_url=BASE_URL)


# ── Admin JSON API ─────────────────────────────────────────────────────────────

@app.route("/admin/api/stats")
@admin_required
def api_admin_stats():
    s = get_admin_stats()
    s["pending_services"] = len(get_pending_services())
    return jsonify(s)


@app.route("/admin/api/sellers")
@admin_required
def api_sellers():
    sellers = [dict(r) for r in get_all_sellers_admin()]
    for s in sellers:
        s["id_photo_url"]     = f"/uploads/{s['id_photo']}"     if s.get("id_photo")     else None
        s["selfie_photo_url"] = f"/uploads/{s['selfie_photo']}" if s.get("selfie_photo") else None
    return jsonify(sellers)


@app.route("/admin/api/products")
@admin_required
def api_admin_products():
    rows = [dict(r) for r in get_all_products_admin(limit=100)]
    for r in rows:
        r["image_url"] = f"/uploads/{r['image_path']}" if r.get("image_path") else None
    return jsonify(rows)


@app.route("/admin/api/services")
@admin_required
def api_admin_services():
    from db import get_connection
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM services ORDER BY created_at DESC LIMIT 100"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/admin/api/orders")
@admin_required
def api_admin_orders():
    rows = [dict(r) for r in get_recent_orders_admin(limit=100)]
    return jsonify(rows)


@app.route("/admin/api/enquiries")
@admin_required
def api_admin_enquiries():
    prop = [dict(r) for r in get_property_enquiries(limit=50)]
    svc  = [dict(r) for r in get_service_enquiries(limit=50)]
    return jsonify({"property": prop, "service": svc})


@app.route("/admin/api/delivery")
@admin_required
def api_admin_delivery():
    from db import get_connection
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM delivery_personnel ORDER BY registered_at DESC"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/admin/api/audit")
@admin_required
def api_admin_audit():
    return jsonify(get_audit_log(limit=100))


@app.route("/admin/api/settings", methods=["GET"])
@admin_required
def api_get_settings():
    keys = [
        "commission_rate", "service_commission_rate", "accommodation_commission_rate",
        "contact_phone", "contact_email", "contact_website", "contact_location",
        "auto_post_facebook", "newsletter_enabled", "paynow_enabled",
    ]
    return jsonify({k: get_setting(k, "") for k in keys})


@app.route("/admin/api/settings", methods=["POST"])
@admin_required
def api_save_settings():
    data = request.json or {}
    for key, value in data.items():
        set_setting(key, str(value))
    log_admin_action("web_admin", "update_settings", detail=", ".join(data.keys()))
    return jsonify({"ok": True, "message": "Settings saved."})


@app.route("/admin/api/seller/approve", methods=["POST"])
@admin_required
def api_approve_seller():
    phone = (request.json or {}).get("phone", "")
    msg   = _approve_seller(phone)
    return jsonify({"ok": True, "message": msg})


@app.route("/admin/api/seller/reject", methods=["POST"])
@admin_required
def api_reject_seller_route():
    body   = request.json or {}
    phone  = body.get("phone", "")
    reason = body.get("reason", "")
    msg    = _reject_seller(phone, reason)
    return jsonify({"ok": True, "message": msg})


@app.route("/admin/api/seller/suspend", methods=["POST"])
@admin_required
def api_suspend_seller_route():
    phone = (request.json or {}).get("phone", "")
    msg   = _suspend_seller(phone)
    return jsonify({"ok": True, "message": msg})


@app.route("/admin/api/product/approve", methods=["POST"])
@admin_required
def api_approve_product_route():
    pid = (request.json or {}).get("id")
    msg = _approve_product(pid)
    return jsonify({"ok": True, "message": msg})


@app.route("/admin/api/product/reject", methods=["POST"])
@admin_required
def api_reject_product_route():
    body   = request.json or {}
    pid    = body.get("id")
    reason = body.get("reason", "Does not meet listing requirements.")
    msg    = _reject_product(pid, reason)
    return jsonify({"ok": True, "message": msg})


@app.route("/admin/api/product/remove", methods=["POST"])
@admin_required
def api_remove_product_route():
    pid = (request.json or {}).get("id")
    msg = _remove_product(pid)
    return jsonify({"ok": True, "message": msg})


@app.route("/admin/api/service/approve", methods=["POST"])
@admin_required
def api_approve_service_route():
    sid = (request.json or {}).get("id")
    svc = get_service(int(sid)) if sid else None
    if not svc:
        return jsonify({"ok": False, "message": "Service not found."})
    set_service_status(int(sid), "approved")
    log_admin_action("web_admin", "approve_service", "service", sid, svc["title"])
    if svc.get("provider_phone"):
        send_whatsapp_message(
            svc["provider_phone"],
            f"🎉 Your service *{svc['title']}* is now *live* on T-Tech Connect!\n\n"
            "Customers can now find and book your service. 🔧\n\n"
            "_Reply *0* for the main menu._"
        )
    return jsonify({"ok": True, "message": f"'{svc['title']}' approved and live."})


@app.route("/admin/api/service/reject", methods=["POST"])
@admin_required
def api_reject_service_route():
    body   = request.json or {}
    sid    = body.get("id")
    reason = body.get("reason", "Does not meet listing requirements.")
    svc    = get_service(int(sid)) if sid else None
    if not svc:
        return jsonify({"ok": False, "message": "Service not found."})
    set_service_status(int(sid), "rejected", reason)
    log_admin_action("web_admin", "reject_service", "service", sid, reason)
    if svc.get("provider_phone"):
        send_whatsapp_message(
            svc["provider_phone"],
            f"❌ Your service *{svc['title']}* was not approved.\n\n"
            f"Reason: _{reason}_\n\n"
            "Please update and try again from the Sell menu.\n\n"
            "_Reply *0* for the main menu._"
        )
    return jsonify({"ok": True, "message": f"'{svc['title']}' rejected."})


@app.route("/admin/api/order/status", methods=["POST"])
@admin_required
def api_update_order_status():
    body     = request.json or {}
    order_id = body.get("id")
    status   = body.get("status", "")
    if status not in ("confirmed", "fulfilled", "cancelled"):
        return jsonify({"ok": False, "message": "Invalid status."})
    update_order_status(order_id, status)
    log_admin_action("web_admin", f"order_{status}", "order", order_id)
    order = get_order(order_id)
    if order and order["buyer_phone"]:
        msgs = {
            "confirmed":  "✅ Your order has been confirmed and is being processed.",
            "fulfilled":  "📦 Your order has been fulfilled! Thank you for shopping with T-Tech Connect.",
            "cancelled":  "❌ Your order has been cancelled. Contact us for more information.",
        }
        send_whatsapp_message(
            order["buyer_phone"],
            msgs[status] + "\n\n_Reply *0* for the main menu._"
        )
    return jsonify({"ok": True, "message": f"Order #{order_id} marked as {status}."})


@app.route("/admin/api/delivery/approve", methods=["POST"])
@admin_required
def api_approve_delivery_route():
    phone = (request.json or {}).get("phone", "")
    dp    = get_delivery_person(phone)
    if not dp:
        return jsonify({"ok": False, "message": "Agent not found."})
    set_delivery_person_status(phone, "approved")
    log_admin_action("web_admin", "approve_delivery", "delivery_personnel", phone, dp["name"])
    send_whatsapp_message(
        phone,
        f"🎉 *Congratulations, {dp['name']}!*\n\n"
        "Your delivery agent application has been *approved*! 🚚\n\n"
        "Reply *my deliveries* to see pending deliveries in your area.\n\n"
        "_Reply *0* for the main menu._"
    )
    return jsonify({"ok": True, "message": f"{dp['name']} approved."})


@app.route("/admin/api/delivery/reject", methods=["POST"])
@admin_required
def api_reject_delivery_route():
    phone = (request.json or {}).get("phone", "")
    dp    = get_delivery_person(phone)
    if not dp:
        return jsonify({"ok": False, "message": "Agent not found."})
    set_delivery_person_status(phone, "rejected")
    log_admin_action("web_admin", "reject_delivery", "delivery_personnel", phone, dp["name"])
    send_whatsapp_message(
        phone,
        "❌ Your delivery agent application was not approved.\n\n"
        f"📧 {get_setting('contact_email', '')}\n"
        "_Reply *0* for the main menu._"
    )
    return jsonify({"ok": True, "message": f"{dp['name']} rejected."})


@app.route("/admin/api/broadcast", methods=["POST"])
@admin_required
def api_broadcast_route():
    body    = request.json or {}
    target  = body.get("target", "sellers")
    message = body.get("message", "").strip()
    if not message:
        return jsonify({"ok": False, "message": "Message cannot be empty."})
    phones  = get_seller_phone_list() if target == "sellers" else get_all_user_phones()
    full    = f"📢 *T-Tech Connect*\n\n{message}\n\n_Reply *0* for the main menu._"
    sent    = sum(1 for p in phones if send_whatsapp_message(p, full))
    log_admin_action("web_admin", "broadcast", detail=f"Sent to {sent} {target}")
    return jsonify({"ok": True, "message": f"Broadcast sent to {sent} {target}."})


@app.route("/admin/analytics")
@admin_required
def analytics_web():
    s    = get_analytics_summary(days=7)
    rows = s["revenue_by_day"]
    days = [r["day"] for r in rows]
    rev  = [r["revenue"] for r in rows]
    top  = s["top_products"]
    cats = s["top_service_cats"]
    peak = s["peak_hours"]

    def bar(value, max_val, width=20):
        filled = int((value / max_val * width)) if max_val else 0
        return "█" * filled + "░" * (width - filled)

    max_rev = max((r["revenue"] for r in rows), default=1) or 1

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>T-Tech Connect — Analytics</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: 'Segoe UI', sans-serif; background: #f0f2f5; color: #1a1a1a; }}
    .header {{ background: #075e54; color: #fff; padding: 24px 32px; }}
    .header h1 {{ font-size: 22px; }} .header p {{ font-size: 14px; opacity:.8; margin-top:4px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 16px; padding: 24px 32px 0; }}
    .card {{ background:#fff; border-radius:12px; padding:20px; box-shadow:0 2px 8px rgba(0,0,0,.07); }}
    .card .label {{ font-size:12px; color:#6b7280; text-transform:uppercase; letter-spacing:.05em; }}
    .card .value {{ font-size:28px; font-weight:700; color:#075e54; margin-top:6px; }}
    .section {{ background:#fff; border-radius:12px; margin:16px 32px; padding:24px; box-shadow:0 2px 8px rgba(0,0,0,.07); }}
    .section h2 {{ font-size:16px; margin-bottom:16px; color:#374151; }}
    .bar-row {{ display:flex; align-items:center; gap:12px; margin-bottom:10px; font-size:13px; }}
    .bar-label {{ width:120px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:#6b7280; }}
    .bar {{ font-family:monospace; color:#075e54; letter-spacing:1px; }}
    .bar-val {{ color:#374151; font-weight:600; min-width:60px; text-align:right; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th {{ text-align:left; padding:8px 12px; background:#f9fafb; color:#6b7280; font-weight:600; font-size:12px; text-transform:uppercase; }}
    td {{ padding:10px 12px; border-top:1px solid #f3f4f6; }}
    .footer {{ text-align:center; padding:24px; color:#9ca3af; font-size:12px; }}
  </style>
</head>
<body>
  <div class="header">
    <h1>T-Tech Connect — Analytics Dashboard</h1>
    <p>Last 7 days · Updated live</p>
  </div>

  <div class="grid">
    <div class="card"><div class="label">Revenue</div><div class="value">${s['total_revenue']:.2f}</div></div>
    <div class="card"><div class="label">Orders</div><div class="value">{s['total_orders']}</div></div>
    <div class="card"><div class="label">New Users</div><div class="value">{s['new_users']}</div></div>
    <div class="card"><div class="label">New Listings</div><div class="value">{s['new_listings']}</div></div>
    <div class="card"><div class="label">New Services</div><div class="value">{s['new_services']}</div></div>
    <div class="card"><div class="label">Open Disputes</div><div class="value">{s['open_disputes']}</div></div>
    <div class="card"><div class="label">Subscribers</div><div class="value">{s['newsletter_count']}</div></div>
  </div>

  <div class="section">
    <h2>📈 Revenue by Day</h2>
    {''.join(f'<div class="bar-row"><span class="bar-label">{r["day"]}</span><span class="bar">{bar(r["revenue"], max_rev)}</span><span class="bar-val">${r["revenue"]:.2f}</span></div>' for r in rows) or '<p style="color:#9ca3af">No revenue data yet.</p>'}
  </div>

  <div class="section">
    <h2>🏆 Top Products</h2>
    <table>
      <tr><th>#</th><th>Product</th><th>Orders</th><th>Revenue</th></tr>
      {''.join(f'<tr><td>{i+1}</td><td>{p["name"]}</td><td>{p["cnt"]}</td><td>${p["revenue"]:.2f}</td></tr>' for i, p in enumerate(top)) or '<tr><td colspan="4" style="color:#9ca3af;text-align:center">No orders yet.</td></tr>'}
    </table>
  </div>

  <div class="section">
    <h2>🔧 Top Service Categories</h2>
    {''.join(f'<div class="bar-row"><span class="bar-label">{c["category"]}</span><span class="bar-val">{c["enquiries"]} enquiries</span></div>' for c in cats) or '<p style="color:#9ca3af">No service enquiries yet.</p>'}
  </div>

  <div class="section">
    <h2>⏰ Peak Hours</h2>
    {''.join(f'<div class="bar-row"><span class="bar-label">{h["hour"]:02d}:00</span><span class="bar-val">{h["hits"]} messages</span></div>' for h in peak) or '<p style="color:#9ca3af">No data yet.</p>'}
  </div>

  <div class="footer">T-Tech Connect · Admin Dashboard · Refresh to update</div>
</body>
</html>"""
    return html


@app.route("/paynow/result", methods=["POST"])
def paynow_result():
    """Paynow sends payment confirmation here."""
    data = request.form
    print(f"[PAYNOW RESULT] {dict(data)}")
    # Paynow sends: reference, paynowreference, amount, status, hash
    status = data.get("status", "").lower()
    ref    = data.get("reference", "")
    if status == "paid":
        notify_admin(f"💰 *Paynow Payment Confirmed*\nRef: {ref}\nAmount: ${data.get('amount', '?')}")
    return "OK", 200


@app.route("/admin/audit")
def audit_log_view():
    """Simple audit log viewer."""
    logs = get_audit_log(limit=50)
    rows = "".join(
        f"<tr><td>{l['created_at']}</td><td>{l['action']}</td>"
        f"<td>{l['target_type']} {l['target_id']}</td><td>{l['detail']}</td></tr>"
        for l in logs
    )
    return f"""<html><head><title>Audit Log</title>
    <style>body{{font-family:sans-serif;padding:24px}}table{{width:100%;border-collapse:collapse;font-size:13px}}
    th,td{{padding:8px 12px;border:1px solid #e5e7eb;text-align:left}}th{{background:#f9fafb}}</style></head>
    <body><h2>Admin Audit Log</h2>
    <table><tr><th>Time</th><th>Action</th><th>Target</th><th>Detail</th></tr>{rows}</table></body></html>"""


if __name__ == "__main__":
    app.run(port=5000)
