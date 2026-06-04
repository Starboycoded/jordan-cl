# Jordan v5 — Setup Guide
**CodedLabs | WhatsApp Commerce OS**

---

## What changed from v4

| Feature | v4 | v5 |
|---|---|---|
| Database | Google Sheets | Supabase (PostgreSQL) |
| Multi-tenant | ❌ TechSquad only | ✅ Unlimited clients |
| Product API | Manual sheets | REST API + dashboard |
| Sessions | In-memory only | In-memory + DB persistence |
| Broadcast | Blocking (freezes server) | Async background thread |
| Order status update | ❌ | ✅ Via API + customer notification |
| Webhook security | ❌ No signature check | ✅ SHA256 verified |
| Meta API version | v17.0 | v20.0 |
| AI classifier | ❌ | ✅ Intent triage before AI call |

---

## Step 1 — Set up Supabase

1. Go to [supabase.com](https://supabase.com) → New Project
2. Open **SQL Editor**
3. Paste the contents of `supabase_schema.sql` and run it
4. Go to **Project Settings → API**
5. Copy your **Project URL** and **service_role key** (not anon key)

> ⚠️ Use the **service_role** key in your backend env. Never expose it on the frontend.

---

## Step 2 — Add Render Environment Variables

In your Render dashboard → Environment, add:

```
SUPABASE_URL         = https://xxxx.supabase.co
SUPABASE_KEY         = your-service-role-key
WHATSAPP_TOKEN       = your-meta-access-token
PHONE_NUMBER_ID      = 989005180973554
APP_SECRET           = your-meta-app-secret
VERIFY_TOKEN         = jordan_verify_2025
GROQ_API_KEY         = your-groq-key
ADMIN_SECRET         = CodedLabs2025
BOT_PHONE            = 15556332668
CATALOG_BASE_URL     = https://bot-test-wddr.onrender.com/shop
BANK_DETAILS         = Bank: GTBank\nAccount: 0123456789\nName: TechSquad
```

---

## Step 3 — Migrate TechSquad data

After deploying, seed TechSquad's products via the API:

```bash
curl -X POST https://your-app.onrender.com/api/tech_squad/products?secret=CodedLabs2025 \
  -H "Content-Type: application/json" \
  -d '{"name":"Product Name","price":5000,"description":"Description","stock":10}'
```

Or use the admin dashboard to add products manually.

---

## Step 4 — Update Meta webhook

In Meta for Developers → WhatsApp → Configuration:
- **Webhook URL**: `https://your-app.onrender.com/webhook`
- **Verify Token**: `jordan_verify_2025`
- Subscribe to: `messages`

---

## Step 5 — Add Supabase token increment function

Run this in Supabase SQL Editor (needed for token logging):

```sql
CREATE OR REPLACE FUNCTION increment_tokens(p_client_id UUID, p_date DATE, p_tokens INTEGER)
RETURNS void AS $$
BEGIN
  INSERT INTO token_log (client_id, date, tokens)
  VALUES (p_client_id, p_date, p_tokens)
  ON CONFLICT (client_id, date)
  DO UPDATE SET tokens = token_log.tokens + EXCLUDED.tokens;
END;
$$ LANGUAGE plpgsql;
```

---

## API Reference

### Products
```
GET    /api/{slug}/products?secret=...           List all products
POST   /api/{slug}/products?secret=...           Create product
PUT    /api/{slug}/products/{id}?secret=...      Update product
DELETE /api/{slug}/products/{id}?secret=...      Soft-delete product
```

### Orders
```
GET  /api/{slug}/orders?secret=...               List orders (add ?status=pending to filter)
PUT  /api/{slug}/orders/{ref}/status?secret=...  Update order status
     Body: {"status": "confirmed", "notify_customer": true}
```

### Clients
```
GET  /api/clients?secret=...                     List all clients
POST /api/clients?secret=...                     Create new client
PUT  /api/clients/{slug}?secret=...              Update client settings
```

### Pages
```
/shop/{slug}               Public storefront
/admin/{slug}?secret=...   Admin dashboard
/broadcast                 POST broadcast message
/ping                      Health check
/refresh?secret=...        Clear caches
```

---

## Adding a new client (business)

```bash
# 1. Create the client
curl -X POST https://your-app.onrender.com/api/clients?secret=CodedLabs2025 \
  -H "Content-Type: application/json" \
  -d '{
    "slug": "fashion_hub",
    "business_name": "Fashion Hub Lagos",
    "template": "fashion",
    "currency": "NGN",
    "phone_number_id": "their-meta-phone-id"
  }'

# 2. Add their products
curl -X POST https://your-app.onrender.com/api/fashion_hub/products?secret=CodedLabs2025 \
  -H "Content-Type: application/json" \
  -d '{"name":"Ankara Dress","price":15000,"stock":5,"category":"dresses"}'

# 3. Access their storefront
# https://your-app.onrender.com/shop/fashion_hub

# 4. Access their admin
# https://your-app.onrender.com/admin/fashion_hub?secret=CodedLabs2025
```

---

## File structure

```
jordan_v5/
├── core_system.py        # Main Flask app (routes, message processor)
├── database.py           # Supabase data layer
├── whatsapp.py           # Meta Cloud API handler
├── ai_engine.py          # Groq AI + intent classifier
├── requirements.txt      # Python dependencies
├── supabase_schema.sql   # Run once in Supabase SQL editor
├── .env.example          # Environment variable template
└── SETUP.md              # This file
```

---

## WhatsApp commands customers can use

| Command | Action |
|---|---|
| `hi` / `hello` | Welcome message |
| `MENU` | Browse all products |
| `ADD 3` | Add product #3 to cart |
| `ADD 3 x2` | Add 2x product #3 |
| `CART` | View cart |
| `CHECKOUT` | Start order |
| `TRACK` | Check order status |
| `HUMAN` | Request human agent |
| `RESUME BOT` | Return to AI after human handoff |
| `HELP` | Show all commands |

---

## Render start command

```
gunicorn core_system:app --workers 2 --timeout 120 --bind 0.0.0.0:$PORT
```
