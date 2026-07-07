-- ══════════════════════════════════════════════════════
    -- JORDAN v5.6 — MESSAGE INBOX + HUMAN HANDOFF RELAY
    -- Run this in your Supabase SQL editor
    -- ══════════════════════════════════════════════════════

    -- Messages table: logs every WhatsApp message in/out
    CREATE TABLE IF NOT EXISTS messages (
        id          BIGSERIAL PRIMARY KEY,
        client_id   UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
        phone       TEXT NOT NULL,                          -- customer's WhatsApp number
        direction   TEXT NOT NULL DEFAULT 'incoming',       -- incoming | outgoing
        message     TEXT NOT NULL,                          -- message content
        message_id  TEXT,                                   -- WhatsApp message ID (for dedup)
        sender_type TEXT DEFAULT 'customer',                -- customer | jordan | merchant
        created_at  TIMESTAMPTZ DEFAULT NOW()
    );

    -- Index for fetching conversation history fast
    CREATE INDEX IF NOT EXISTS idx_messages_client_phone 
        ON messages(client_id, phone, created_at);

    -- Index for listing all conversations per client
    CREATE INDEX IF NOT EXISTS idx_messages_client 
        ON messages(client_id, created_at DESC);

    -- Prevent duplicate webhook deliveries
    CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_dedup 
        ON messages(client_id, message_id) WHERE message_id IS NOT NULL;
    
