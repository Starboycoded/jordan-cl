-- ══════════════════════════════════════════════════════
-- JORDAN v5 — SUPABASE SCHEMA
-- Run this in your Supabase SQL editor
-- ══════════════════════════════════════════════════════


-- CLIENTS (one row per business)
CREATE TABLE clients (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug            TEXT UNIQUE NOT NULL,          -- e.g. "tech_squad", "fashionhub"
    business_name   TEXT NOT NULL,
    whatsapp_number TEXT,                          -- their WA number shown to customers
    merchant_phone  TEXT,                          -- owner's personal WA (gets order notifications)
    phone_number_id TEXT,                          -- Meta Phone Number ID
    wa_token        TEXT,                          -- Meta access token (per-client later)
    greeting        TEXT DEFAULT 'Welcome! How can I help you today?',
    template        TEXT DEFAULT 'general',        -- fashion | beauty | electronics | food | general
    currency        TEXT DEFAULT 'NGN',
    ai_model        TEXT DEFAULT 'claude-haiku-4-5',  -- haiku (default) | claude-sonnet-4-6 (premium)
    active          BOOLEAN DEFAULT TRUE,
    welcome_msg     TEXT,                            -- Custom welcome message
    bank_details    TEXT,                            -- Payment/bank info for invoices
    biz_hours       TEXT,                            -- Business hours for support
    created_at      TIMESTAMPTZ DEFAULT NOW()
);


-- PRODUCTS (per client)
CREATE TABLE products (
    id          BIGSERIAL PRIMARY KEY,
    client_id   UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    description TEXT,
    price       NUMERIC(12,2) NOT NULL,
    stock       INTEGER DEFAULT 0,
    image_url   TEXT,
    category    TEXT,
    active      BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);


-- CUSTOMERS (per client)
CREATE TABLE customers (
    id          BIGSERIAL PRIMARY KEY,
    client_id   UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    phone       TEXT NOT NULL,
    name        TEXT,
    address     TEXT,
    total_spend NUMERIC(12,2) DEFAULT 0,
    order_count INTEGER DEFAULT 0,
    last_seen   TIMESTAMPTZ DEFAULT NOW(),
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(client_id, phone)
);


-- ORDERS
CREATE TABLE orders (
    id          BIGSERIAL PRIMARY KEY,
    client_id   UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    order_ref   TEXT NOT NULL,                     -- e.g. ORD-20250530-0001
    customer_id BIGINT REFERENCES customers(id),
    phone       TEXT NOT NULL,
    items       JSONB NOT NULL,                    -- [{product_id, name, qty, price}]
    total       NUMERIC(12,2) NOT NULL,
    address     TEXT,
    status      TEXT DEFAULT 'pending',            -- pending | confirmed | awaiting_payment | paid | processing | delivered | cancelled
