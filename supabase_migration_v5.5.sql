-- ══════════════════════════════════════════════════════
    -- JORDAN v5.5 — MIGRATION: Settings & Onboarding Columns
    -- Run this in Supabase SQL Editor
    -- Adds missing columns for settings dashboard and onboarding
    -- ══════════════════════════════════════════════════════

    -- 1. Add settings columns (used by onboarding Step 4 & settings dashboard)
    ALTER TABLE clients ADD COLUMN IF NOT EXISTS welcome_msg  TEXT;
    ALTER TABLE clients ADD COLUMN IF NOT EXISTS bank_details TEXT;
    ALTER TABLE clients ADD COLUMN IF NOT EXISTS biz_hours    TEXT;

    -- 2. Verify all columns exist
    SELECT column_name, data_type
    FROM information_schema.columns
    WHERE table_name = 'clients'
      AND column_name IN ('welcome_msg', 'bank_details', 'biz_hours', 'modules_config', 'plan', 'feature_flags', 'admin_secret');
    
