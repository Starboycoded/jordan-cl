# Jordan — AI-Powered WhatsApp Commerce OS

> Turn any WhatsApp number into a full-stack sales, booking, and support assistant. Built for African businesses. Multi-tenant by design.

**Built by [CodedLabs](https://www.oasis.codes)** | Lagos, Nigeria

---

## What Jordan Does

Jordan is a WhatsApp-native business operating system. A business plugs in their WhatsApp number and immediately gets:

- 🛍️ **AI Sales Assistant** — Handles product browsing, cart, checkout, and order confirmation. All inside WhatsApp.
- 📅 **Booking System** — Salons, clinics, consultants. Customers book appointments through chat.
- 🔥 **Lead Generation** — Real estate, agencies. Conversational forms that qualify prospects naturally.
- 💬 **Support Layer** — FAQ auto-answers, human handoff, business hours, issue tracking.
- 📊 **Web Dashboard** — Manage products, orders, appointments, leads, and settings.
- 👥 **Multi-Tenant** — One deployment serves unlimited businesses. Each with their own products, customers, and AI persona.

Customers never leave WhatsApp. Business owners manage everything from a web dashboard. Jordan sits in between, powered by Claude AI.

---

## Who It's For

| Template | Use Case | Flow |
|----------|----------|------|
| Commerce / Fashion / Beauty / Food / Electronics | Online stores selling physical products | Product catalogue → Cart → Checkout → Order tracking |
| Salon / Clinic | Service-based businesses | Service selection → Date/time picker → Booking confirmation |
| Real Estate / Agency | Lead qualification | Conversational lead capture → Pipeline management |
| Support | Customer service | FAQ knowledge base → Human handoff |

---

## Architecture

```
Customer (WhatsApp)
      │
      ▼
Meta Cloud API (webhook)
      │
      ▼
Jordan (Flask + Gunicorn on Render)
  ├── Message Router (support → commerce → booking → leadgen → AI fallback)
  ├── AI Engine (Anthropic Claude — Haiku/Sonnet)
  ├── Module System (commerce, booking, leadgen, support)
  ├── Subscription Engine (Starter / Growth / Premium / Enterprise)
  └── Web Dashboard (product admin, orders, analytics, settings)
      │
      ▼
Supabase (PostgreSQL + Storage)
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3, Flask, Gunicorn |
| Database | Supabase (PostgreSQL) |
| AI | Anthropic Claude (Haiku + Sonnet) |
| Messaging | Meta WhatsApp Cloud API v20.0 |
| Storage | Supabase Storage (product images) |
| Hosting | Render |
| Auth | Flask sessions + per-client admin secrets |

---

## Quick Start

### Prerequisites

- Python 3.10+
- A Supabase project
- A Meta WhatsApp Business App (with permanent token)
- An Anthropic API key

### Setup

```bash
# 1. Clone
git clone https://github.com/Starboycoded/jordan-cl.git
cd jordan-cl

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set up Supabase
#    - Create a Supabase project
#    - Run supabase_schema.sql in the SQL Editor
#    - Run supabase_fixes.sql for additional functions and columns
#    - Run supabase_migration_v5.5.sql for the latest columns

# 4. Configure environment
cp env.example .env
# Fill in your actual values

# 5. Run
python core_system.py
```

### Deploy to Render

The repo includes `render.yaml` and `Procfile` for one-click Render deployment. See [SETUP.md](SETUP.md) for the full production deployment guide.

---

## Project Structure

```
jordan-cl/
├── core_system.py          # Main Flask app (webhook, APIs, routes)
├── router.py               # Message routing engine
├── ai_engine.py            # Anthropic Claude integration
├── database.py             # Supabase data layer
├── whatsapp.py             # Meta Cloud API handler
├── merchant.py             # Merchant notifications & commands
├── subscriptions.py        # Plan-based feature gating
├── storage.py              # Supabase Storage (images)
├── availability.py         # Booking slot availability
├── templates_config.py     # Industry template configurations
├── onboarding.py           # New client onboarding wizard
├── product_dashboard.py    # Client product/order dashboard
├── admin_panel.py          # CodedLabs admin panel
├── auth.py                 # Session-based authentication
├── modules/
│   ├── __init__.py          # Module registry & template→module mapping
│   ├── commerce.py          # Product catalogue, cart, checkout, orders
│   ├── booking.py           # Service selection, date/time, booking flow
│   ├── leadgen.py           # Lead capture, qualification, pipeline
│   └── support.py           # FAQ, human handoff, contact info
├── templates/              # Jinja2 HTML templates
├── supabase_schema.sql     # Core database schema
├── supabase_fixes.sql      # Functions & column additions
├── supabase_migration_v5.5.sql  # Latest column additions
├── requirements.txt        # Python dependencies
├── env.example             # Environment variable template
├── render.yaml             # Render deployment config
├── Procfile                # Process file for hosting
├── runtime.txt             # Python version for hosting
└── SETUP.md                # Full deployment guide
```

---

## Subscription Tiers

| Plan | Price (₦/month) | Key Features |
|------|----------------|--------------|
| **Starter** | ₦15,000 | Single flow, 50 products, basic analytics |
| **Growth** | ₦35,000 | CRM, broadcasts, 200 products |
| **Premium** | ₦75,000 | AI FAQ, voice notes, advanced analytics, unlimited |
| **Enterprise** | Custom | White label, multi-user, priority support |

---

## What Needs Upgrading

### 🔴 Immediate
- **Meta Business Verification** — Get verified for permanent API access. Current test tokens expire every 24 hours and limit you to 3 users. Without this, Jordan cannot go to production.
- **Run supabase_migration_v5.5.sql** — Adds `welcome_msg`, `bank_details`, `biz_hours` columns that the settings dashboard needs.
- **Get 2-3 real paying clients** — TechSquad is a test. Until someone pays, Jordan is a side project.

### 🟡 Short-Term
- **Redis session cache** — Current in-memory cache won't scale past one server instance. When you add more clients, sessions will get inconsistent.
- **Payment integration** — Right now orders generate an invoice with bank details. Integrate Paystack or Flutterwave so customers can pay inside WhatsApp.
- **Error monitoring** — Add Sentry or Slack alerts for production incidents. Currently failures are just logged.

### 🟢 Medium-Term
- **Self-serve onboarding** — Right now every new client needs manual DB setup. Build the full onboarding flow so businesses sign up without you.
- **Analytics charts** — Dashboard shows numbers but no visual trends. Add simple charts for revenue, order volume, customer growth.
- **Multi-language** — Yoruba, Hausa, French for West African expansion.

### 🔵 Long-Term
- **Ghana expansion** — Identical market dynamics, plug-and-play. Just need a Ghanaian phone number and payment integration.
- **White-label** — Enterprise clients get their own branded bot with no CodedLabs mention.
- **Template marketplace** — Let third parties build and sell industry-specific templates.

---

**Built with ❤️ in Lagos, Nigeria.**
