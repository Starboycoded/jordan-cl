-- ══════════════════════════════════════════════════════
-- JORDAN v5.4 — SUPABASE QUICK FIXES
-- Run these one by one in Supabase SQL Editor
-- ══════════════════════════════════════════════════════

-- 1. FIX: Token tracking (replaces the missing RPC)
--    Run this to create the increment_tokens function
CREATE OR REPLACE FUNCTION increment_tokens(
    p_client_id UUID,
    p_date DATE,
    p_tokens INTEGER
) RETURNS void AS $$
BEGIN
    INSERT INTO token_log (client_id, date, tokens)
    VALUES (p_client_id, p_date, p_tokens)
    ON CONFLICT (client_id, date)
    DO UPDATE SET tokens = token_log.tokens + EXCLUDED.tokens;
END;
$$ LANGUAGE plpgsql;


-- 2. FIX: Set merchant phone for TechSquad
--    Replace the number with your actual WhatsApp number
UPDATE clients
SET merchant_phone = '2348012345678'   -- ← change this to your number
WHERE slug = 'tech_squad';


-- 3. FIX: Add modules_config column if missing
ALTER TABLE clients ADD COLUMN IF NOT EXISTS modules_config JSONB DEFAULT '{}';


-- 4. FIX: Add admin_secret column if missing
--    (allows per-client login secrets)
ALTER TABLE clients ADD COLUMN IF NOT EXISTS admin_secret TEXT;


-- 5. CHECK: Verify your clients table has all required columns
SELECT
    id, slug, business_name, template, plan,
    merchant_phone, phone_number_id, active,
    modules_config, feature_flags
FROM clients
WHERE active = TRUE;
