"""
Hanna From Japan — Post-Purchase Guide Agent
----------------------------------------------
Listens for Shopify's `orders/create` webhook, pulls each purchased
product's "Guia — ..." metafields, renders the branded PDF guide,
and emails it to the customer automatically.

Deploy this as a small always-on web service (Render, Railway, Fly.io).
See README.md for full setup steps.
"""

import os
import hmac
import hashlib
import base64
import logging
from datetime import datetime

import requests
from flask import Flask, request, abort
from weasyprint import HTML
from jinja2 import Environment, FileSystemLoader

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("hanna-guide-agent")

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Config — set these as environment variables on your host (Render, etc.)
# ---------------------------------------------------------------------------
SHOPIFY_SHOP_DOMAIN = os.environ["SHOPIFY_SHOP_DOMAIN"]          # c6z71w-wh.myshopify.com
SHOPIFY_ADMIN_TOKEN = os.environ["SHOPIFY_ADMIN_TOKEN"]          # Admin API access token
SHOPIFY_WEBHOOK_SECRET = os.environ["SHOPIFY_WEBHOOK_SECRET"]    # From the webhook setup step
SHOPIFY_API_VERSION = os.environ.get("SHOPIFY_API_VERSION", "2025-01")

RESEND_API_KEY = os.environ["RESEND_API_KEY"]                    # or swap for SendGrid, etc.
FROM_EMAIL = os.environ.get("FROM_EMAIL", "hanna@hannafromjapan.com")
FROM_NAME = os.environ.get("FROM_NAME", "Hanna From Japan")

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
template = env.get_template("guide_template.html")

GRAPHQL_URL = f"https://{SHOPIFY_SHOP_DOMAIN}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"

METAFIELD_KEYS = [
    "how_to_use",
    "cautions",
    "ingredients_summary",
    "product_info",
    "guarantee",
    "estimated_delivery",
    "hanna_tip",
    "infographic",
]


# ---------------------------------------------------------------------------
# Webhook signature verification
# ---------------------------------------------------------------------------
def verify_webhook(data: bytes, hmac_header: str) -> bool:
    digest = hmac.new(
        SHOPIFY_WEBHOOK_SECRET.encode("utf-8"), data, hashlib.sha256
    ).digest()
    computed_hmac = base64.b64encode(digest).decode()
    return hmac.compare_digest(computed_hmac, hmac_header or "")


# ---------------------------------------------------------------------------
# Shopify Admin API — fetch product metafields by product ID
# ---------------------------------------------------------------------------
def fetch_product_guide_data(product_gid: str):
    query = """
    query ProductGuide($id: ID!) {
      product(id: $id) {
        title
        vendor
        featuredImage { url }
        metafields(namespace: "guide", first: 10) {
          nodes { key value type }
        }
      }
    }
    """
    resp = requests.post(
        GRAPHQL_URL,
        json={"query": query, "variables": {"id": product_gid}},
        headers={
            "X-Shopify-Access-Token": SHOPIFY_ADMIN_TOKEN,
            "Content-Type": "application/json",
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()["data"]["product"]
    if not data:
        return None

    mf = {m["key"]: m["value"] for m in data["metafields"]["nodes"]}

    infographic_url = None
    if mf.get("infographic"):
        # file_reference metafields store a GID; resolve to a URL separately if needed.
        # Simplest reliable approach: also store the URL as a second metafield, OR
        # resolve via a follow-up query on MediaImage. Left as a TODO hook below.
        infographic_url = resolve_file_reference_url(mf["infographic"])

    return {
        "title": data["title"],
        "vendor": data.get("vendor"),
        "image_url": (data.get("featuredImage") or {}).get("url"),
        "how_to_use": mf.get("how_to_use"),
        "cautions": mf.get("cautions"),
        "ingredients_summary": mf.get("ingredients_summary"),
        "product_info": mf.get("product_info"),
        "guarantee": mf.get("guarantee"),
        "estimated_delivery": mf.get("estimated_delivery"),
        "hanna_tip": mf.get("hanna_tip"),
        "infographic_url": infographic_url,
    }


def resolve_file_reference_url(file_gid: str):
    """file_reference metafields store a GenericFile/MediaImage GID.
    Resolve it to a public URL via a follow-up query."""
    query = """
    query ResolveFile($id: ID!) {
      node(id: $id) {
        ... on MediaImage { image { url } }
        ... on GenericFile { url }
      }
    }
    """
    resp = requests.post(
        GRAPHQL_URL,
        json={"query": query, "variables": {"id": file_gid}},
        headers={
            "X-Shopify-Access-Token": SHOPIFY_ADMIN_TOKEN,
            "Content-Type": "application/json",
        },
        timeout=15,
    )
    resp.raise_for_status()
    node = resp.json()["data"]["node"] or {}
    return node.get("url") or (node.get("image") or {}).get("url")


# ---------------------------------------------------------------------------
# Email sending (Resend — swap for SendGrid/Postmark if preferred)
# ---------------------------------------------------------------------------
def send_guide_email(to_email: str, customer_first_name: str, pdf_bytes: bytes, order_number: str):
    resp = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "from": f"{FROM_NAME} <{FROM_EMAIL}>",
            "to": [to_email],
            "subject": f"🌸 Seu guia Hanna From Japan — Pedido #{order_number}",
            "html": (
                f"<p>Oiii, {customer_first_name}! Segue em anexo o guia dos "
                f"produtos que você comprou. Beijo, Hanna 🌸</p>"
            ),
            "attachments": [
                {
                    "filename": f"hanna-guia-pedido-{order_number}.pdf",
                    "content": base64.b64encode(pdf_bytes).decode(),
                }
            ],
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Webhook endpoint
# ---------------------------------------------------------------------------
@app.route("/webhook/orders-create", methods=["POST"])
def orders_create():
    raw_body = request.get_data()
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256")

    if not verify_webhook(raw_body, hmac_header):
        logger.warning("Webhook signature verification failed")
        abort(401)

    order = request.get_json()

    customer = order.get("customer") or {}
    customer_first_name = customer.get("first_name") or "amiga"
    customer_email = order.get("email") or order.get("contact_email")
    order_number = order.get("name", "").lstrip("#") or str(order.get("order_number", ""))
    order_date = datetime.now().strftime("%d de %B de %Y")

    if not customer_email:
        logger.info("Order %s has no email, skipping guide send", order_number)
        return {"status": "skipped_no_email"}, 200

    products = []
    for line_item in order.get("line_items", []):
        product_id = line_item.get("product_id")
        if not product_id:
            continue
        product_gid = f"gid://shopify/Product/{product_id}"
        try:
            guide_data = fetch_product_guide_data(product_gid)
        except Exception:
            logger.exception("Failed to fetch guide data for product %s", product_id)
            continue
        if guide_data:
            products.append(guide_data)

    if not products:
        logger.info("Order %s has no guide-eligible products, skipping", order_number)
        return {"status": "skipped_no_guide_data"}, 200

    html_str = template.render(
        customer_first_name=customer_first_name,
        customer_email=customer_email,
        order_number=order_number,
        order_date=order_date,
        products=products,
        product_count=len(products),
    )

    pdf_bytes = HTML(string=html_str, base_url=STATIC_DIR).write_pdf()

    try:
        send_guide_email(customer_email, customer_first_name, pdf_bytes, order_number)
    except Exception:
        logger.exception("Failed to send guide email for order %s", order_number)
        return {"status": "error_sending_email"}, 500

    logger.info("Guide sent for order %s to %s", order_number, customer_email)
    return {"status": "sent"}, 200


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}, 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
