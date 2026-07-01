# Hanna From Japan — Post-Purchase Guide Agent

Automatically sends a branded PDF guide (how to use, cautions, ingredients,
infographic, Hanna's personal note) to every customer right after they
purchase — pulling content live from your Shopify product metafields.

---

## How it works

1. Shopify fires the `orders/create` webhook the moment an order is placed.
2. This service receives it, verifies it's really from Shopify, and looks up
   each purchased product's `guide.*` metafields.
3. It fills those into the PDF template and renders a PDF.
4. It emails the PDF to the customer automatically.

No manual step. No app to check. It just happens.

---

## 1. Deploy the service (Render — recommended)

1. Push this folder to a new GitHub repo.
2. On [render.com](https://render.com) → New → Web Service → connect the repo.
3. Render will detect the `Dockerfile` automatically — leave build settings default.
4. Under **Environment**, add all variables from `.env.example` with your real values
   (see steps 2 and 3 below for where to get them).
5. Deploy. You'll get a URL like `https://hanna-guide-agent.onrender.com`.
6. Confirm it's alive: visit `https://hanna-guide-agent.onrender.com/health` → should show `{"status": "ok"}`.

Render's free tier sleeps after inactivity, causing a slow first request after idle
periods. For a store taking real orders, the ~$7/mo "Starter" tier keeps it always-on
so guides send instantly.

---

## 2. Get your Shopify Admin API token

1. Shopify Admin → Settings → Apps and sales channels → Develop apps → Create an app.
2. Configure Admin API scopes: `read_products`, `read_orders`.
3. Install the app, copy the **Admin API access token** (starts with `shpat_`).
4. Put it in `SHOPIFY_ADMIN_TOKEN`.

---

## 3. Register the webhook

In the same custom app (or via Shopify Admin → Settings → Notifications → Webhooks),
create a webhook:

- **Event:** Order creation
- **URL:** `https://<your-render-url>/webhook/orders-create`
- **Format:** JSON

Shopify will show you a **webhook signing secret** — put it in `SHOPIFY_WEBHOOK_SECRET`.
This is what the agent uses to confirm requests are genuinely from Shopify.

---

## 4. Set up email sending

This uses [Resend](https://resend.com) (simple, generous free tier, good deliverability).

1. Sign up, verify your sending domain (`hannafromjapan.com`).
2. Create an API key → put it in `RESEND_API_KEY`.
3. Set `FROM_EMAIL` to an address on your verified domain, e.g. `hanna@hannafromjapan.com`.

Prefer SendGrid or Postmark instead? Swap the `send_guide_email()` function in
`app.py` — same idea, different API call.

---

## 5. Fill in your product metafields

For each product, go to the product page in Shopify Admin → Metafields section,
and fill in whichever apply:

**BeautyDNA / skincare products:**
- `Guia — Como usar`
- `Guia — Cuidados`
- `Guia — Ingredientes`

**Any product (beauty or general):**
- `Guia — Infográfico` (upload your designed image)
- `Guia — Sobre o produto` (for non-beauty items — general description)
- `Guia — Garantia`
- `Guia — Prazo de entrega`
- `Guia — Dica da Hanna` (optional personal touch)

The PDF automatically shows only the sections that have content — no blank
sections ever appear. A skincare product with all 3 beauty fields filled gets
the full skincare layout; a JDM accessory with just "Sobre o produto" and
"Garantia" gets a simpler general layout. Same template, adapts per product.

---

## 6. Test it

1. Fill in metafields for one real product.
2. Place a real (or test) order for that product on your store.
3. Within a few seconds, the guide PDF should land in the order email's inbox.
4. Check the Render service logs if it doesn't — most issues are a missing/wrong
   environment variable.

---

## Files in this project

| File | Purpose |
|---|---|
| `app.py` | The Flask service — webhook handler, Shopify queries, PDF render, email send |
| `templates/guide_template.html` | The PDF design (Jinja2 — same look Claude built with you) |
| `static/sakura.svg` | The background pattern used on every page |
| `Dockerfile` | Packages the app with WeasyPrint's system dependencies |
| `requirements.txt` | Python dependencies |
| `.env.example` | List of required environment variables |

---

## Extending this later

- **Multiple images per product:** add more `file_reference` metafields the same way.
- **Non-beauty categories with different sections:** the template already supports
  mixed sections per product — add more `guide.*` metafields and matching
  `{% if %}` blocks in `guide_template.html` as needed.
- **Order-level attachments (invoice, etc.):** just add another PDF/attachment in
  `send_guide_email()`.
