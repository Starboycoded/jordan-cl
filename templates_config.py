# ══════════════════════════════════════════════════════
# JORDAN v5.3 — TEMPLATE CONFIGURATIONS
# Commerce | Booking | Lead Gen | Support
# Each template = different business behaviour, not just
# different colours. Same engine, different flows.
# ══════════════════════════════════════════════════════

TEMPLATES = {

    # ── COMMERCE ──────────────────────────────────────
    "commerce": {
        "name":        "Online Store",
        "emoji":       "🛍️",
        "description": "Sell products through WhatsApp",
        "tagline":     "Everything you need, delivered",
        "flow":        "commerce",
        "primary":     "#25D366",
        "bg":          "#07070e",
        "card_bg":     "#0f1a14",
        "border":      "#1a3020",
        "categories":  ["Fashion", "Electronics", "Beauty", "Food", "Gifts", "Other"],
        "checkout_extras": [],
        "dashboard_tabs": ["products", "orders", "customers", "broadcast"],
        "ai_persona": """You are Jordan, a friendly WhatsApp sales assistant.
Help customers browse products, answer questions about items, and guide them through ordering.
Keep responses short and conversational — this is WhatsApp, not email.
Always use the customer's name if you know it. Be warm, not robotic.""",
        "greeting": "Hi! 👋 Welcome to our store. What are you looking for today?",
    },

    # ── FASHION sub-type (commerce variant) ──────────
    "fashion": {
        "name":        "Fashion Store",
        "emoji":       "👗",
        "description": "Clothing, shoes, bags, accessories",
        "tagline":     "Style delivered to your door",
        "flow":        "commerce",
        "primary":     "#C9A84C",
        "bg":          "#0d0800",
        "card_bg":     "#150e00",
        "border":      "#2a1f00",
        "categories":  ["Dresses", "Tops", "Bottoms", "Shoes", "Bags", "Accessories"],
        "checkout_extras": [
            {"key": "size",  "question": "What size do you need? (XS / S / M / L / XL / XXL)"},
            {"key": "color", "question": "Any colour preference? (or reply 'as shown')"},
        ],
        "dashboard_tabs": ["products", "orders", "customers", "broadcast"],
        "ai_persona": """You are Jordan, a stylish fashion assistant on WhatsApp.
You love helping customers find the perfect outfit and always give honest style advice.
Ask about occasion (casual, work, event) to make better recommendations.
Mention sizing, fabric, and what to pair items with. Be enthusiastic but not pushy.""",
        "greeting": "Hey! 👗 Welcome. Looking for something specific, or shall I show you what's trending?",
    },

    # ── BEAUTY sub-type ────────────────────────────
    "beauty": {
        "name":        "Beauty & Skincare",
        "emoji":       "💄",
        "description": "Skincare, makeup, haircare, wellness",
        "tagline":     "Your glow, delivered",
        "flow":        "commerce",
        "primary":     "#E8A0BF",
        "bg":          "#0d0008",
        "card_bg":     "#150010",
        "border":      "#2a001a",
        "categories":  ["Skincare", "Makeup", "Haircare", "Fragrances", "Body Care", "Wellness"],
        "checkout_extras": [
            {"key": "skin_type", "question": "What's your skin type? (oily / dry / combination / sensitive)"},
            {"key": "concern",   "question": "Any skin concern? (acne, dark spots, anti-aging, hydration)"},
        ],
        "dashboard_tabs": ["products", "orders", "customers", "broadcast"],
        "ai_persona": """You are Jordan, a knowledgeable beauty advisor on WhatsApp.
Ask about skin type and concerns before recommending skincare products.
Mention key ingredients and what they do. Be warm, inclusive and honest.
Usage tips matter: tell customers when to apply, how to layer, what to avoid.""",
        "greeting": "Hi! 💄 I'm your beauty advisor. Tell me your skin concern and I'll find the perfect match!",
    },

    # ── FOOD sub-type ──────────────────────────────
    "food": {
        "name":        "Food & Restaurant",
        "emoji":       "🍱",
        "description": "Meals, snacks, drinks, groceries",
        "tagline":     "Fresh food, fast delivery",
        "flow":        "commerce",
        "primary":     "#FF6B35",
        "bg":          "#0d0500",
        "card_bg":     "#150900",
        "border":      "#2a1200",
        "categories":  ["Meals", "Snacks", "Drinks", "Pastries", "Combos", "Groceries"],
        "checkout_extras": [
            {"key": "spice_level",   "question": "Spice level? (mild / medium / hot / extra hot)"},
            {"key": "delivery_time", "question": "Preferred delivery time? (ASAP or specific time e.g. 2pm)"},
        ],
        "dashboard_tabs": ["products", "orders", "customers", "broadcast"],
        "ai_persona": """You are Jordan, a friendly food concierge on WhatsApp.
Make food sound delicious. Ask about dietary needs when relevant.
Suggest add-ons and combos naturally. Mention estimated delivery time.
Be fast and efficient — hungry customers don't want to wait.""",
        "greeting": "Hey! 🍱 Hungry? Tell me what you're in the mood for and I'll sort you out!",
    },

    # ── ELECTRONICS sub-type ──────────────────────
    "electronics": {
        "name":        "Electronics & Gadgets",
        "emoji":       "⚡",
        "description": "Phones, laptops, accessories, gadgets",
        "tagline":     "Tech that works for you",
        "flow":        "commerce",
        "primary":     "#25D366",
        "bg":          "#07070e",
        "card_bg":     "#0f1a14",
        "border":      "#1a3020",
        "categories":  ["Phones", "Laptops", "Audio", "Accessories", "Gaming", "Smart Home"],
        "checkout_extras": [
            {"key": "warranty", "question": "Would you like to add a warranty? (yes / no)"},
        ],
        "dashboard_tabs": ["products", "orders", "customers", "broadcast"],
        "ai_persona": """You are Jordan, a knowledgeable electronics specialist on WhatsApp.
Be precise about specs, compatibility, and key features. Ask about use case.
Compare options honestly — if something isn't the best fit, say so.
Mention warranties and after-sales support when relevant.""",
        "greeting": "Hey! ⚡ Looking for something specific or need a recommendation? Tell me what you need it for.",
    },

    # ── BOOKING ────────────────────────────────────
    "booking": {
        "name":        "Booking & Appointments",
        "emoji":       "📅",
        "description": "Salons, clinics, consultants, photographers, tutors",
        "tagline":     "Book your appointment in seconds",
        "flow":        "booking",
        "primary":     "#6366F1",
        "bg":          "#07070f",
        "card_bg":     "#0f0f1a",
        "border":      "#1e1e3a",
        "categories":  ["Hair", "Nails", "Facial", "Massage", "Consultation", "Session", "Other"],
        "checkout_extras": [],
        "dashboard_tabs": ["services", "appointments", "customers", "availability"],
        "ai_persona": """You are Jordan, a friendly booking assistant on WhatsApp.
Help customers book appointments quickly and smoothly.
Be clear about available services, durations, and prices.
Confirm every booking detail before finalising. Be warm and professional.""",
        "greeting": "Hi! 📅 Welcome. What service would you like to book today?",
        "booking_config": {
            "time_slots":      ["9:00 AM", "10:00 AM", "11:00 AM", "12:00 PM",
                                "1:00 PM", "2:00 PM", "3:00 PM", "4:00 PM", "5:00 PM"],
            "days_ahead":      14,     # How many days ahead customers can book
            "slot_duration":   60,     # Default slot duration in minutes
            "advance_notice":  2,      # Minimum hours notice required
        },
    },

    # ── LEAD GEN ───────────────────────────────────
    "lead_gen": {
        "name":        "Lead Generation",
        "emoji":       "🔥",
        "description": "Real estate, insurance, agencies, solar, digital marketing",
        "tagline":     "Turn WhatsApp chats into qualified leads",
        "flow":        "lead_gen",
        "primary":     "#F59E0B",
        "bg":          "#0d0900",
        "card_bg":     "#150f00",
        "border":      "#2a1e00",
        "categories":  [],
        "checkout_extras": [],
        "dashboard_tabs": ["leads", "pipeline", "customers", "broadcast"],
        "ai_persona": """You are Jordan, a professional lead qualification assistant on WhatsApp.
Your job is to have a friendly conversation that naturally collects key information.
Never feel like a form. Feel like a helpful advisor genuinely trying to understand their needs.
Qualify leads by understanding their budget, timeline, location, and specific requirement.
Always be respectful — even unqualified leads may refer others.""",
        "greeting": "Hi! 👋 Thanks for reaching out. I'd love to understand what you're looking for so I can help. What brings you here today?",
        "lead_fields": [
            {"key": "name",      "question": "Great! First, what's your name?"},
            {"key": "location",  "question": "And where are you based? (city or area)"},
            {"key": "budget",    "question": "Do you have a budget range in mind?"},
            {"key": "timeline",  "question": "When are you looking to move forward?"},
            {"key": "interest",  "question": "Tell me more about exactly what you're looking for."},
        ],
    },

    # ── SUPPORT ────────────────────────────────────
    "support": {
        "name":        "Customer Support",
        "emoji":       "💬",
        "description": "Schools, churches, companies, NGOs, government",
        "tagline":     "Instant answers, 24/7",
        "flow":        "support",
        "primary":     "#0EA5E9",
        "bg":          "#07090f",
        "card_bg":     "#0f1218",
        "border":      "#1a2030",
        "categories":  [],
        "checkout_extras": [],
        "dashboard_tabs": ["faqs", "conversations", "customers"],
        "ai_persona": """You are Jordan, a helpful support assistant on WhatsApp.
Answer questions accurately based on the knowledge base provided.
If you don't know something, say so honestly and offer to escalate to a human.
Be friendly, clear and concise. No jargon. No corporate speak.""",
        "greeting": "Hi! 💬 How can I help you today? Ask me anything!",
    },

    # ── GENERAL fallback ──────────────────────────
    "general": {
        "name":        "General Business",
        "emoji":       "🏢",
        "description": "General retail and commerce",
        "tagline":     "Everything you need",
        "flow":        "commerce",
        "primary":     "#25D366",
        "bg":          "#07070e",
        "card_bg":     "#0f1a14",
        "border":      "#1a3020",
        "categories":  ["Products", "Services", "Bundles"],
        "checkout_extras": [],
        "dashboard_tabs": ["products", "orders", "customers", "broadcast"],
        "ai_persona": """You are Jordan, a helpful WhatsApp assistant.
Be friendly, clear, and concise. Help customers find what they need and complete their goals.""",
        "greeting": "Hi! 👋 How can I help you today?",
    },
}

# ── Commerce-type templates (use commerce flow) ────
COMMERCE_TEMPLATES = {"commerce", "fashion", "beauty", "food", "electronics", "general"}
BOOKING_TEMPLATES  = {"booking"}
LEADGEN_TEMPLATES  = {"lead_gen"}
SUPPORT_TEMPLATES  = {"support"}


def get_template(name: str) -> dict:
    return TEMPLATES.get(name, TEMPLATES["general"])

def get_flow(name: str) -> str:
    """Return which conversation flow to use for this template."""
    return get_template(name).get("flow", "commerce")

def get_ai_persona(name: str) -> str:
    return get_template(name).get("ai_persona", TEMPLATES["general"]["ai_persona"])

def get_checkout_extras(name: str) -> list:
    return get_template(name).get("checkout_extras", [])

def get_storefront_theme(name: str) -> dict:
    t = get_template(name)
    return {
        "primary": t.get("primary", "#25D366"),
        "bg":      t.get("bg",      "#07070e"),
        "card_bg": t.get("card_bg", "#0f1a14"),
        "border":  t.get("border",  "#1a3020"),
        "tagline": t.get("tagline", ""),
        "emoji":   t.get("emoji",   "🛍️"),
    }

def get_business_types() -> list:
    """Return selectable business types for onboarding."""
    return [
        {"key": "commerce",    "name": "Online Store",           "emoji": "🛍️", "desc": "Sell products on WhatsApp"},
        {"key": "fashion",     "name": "Fashion & Clothing",     "emoji": "👗", "desc": "Clothes, shoes, bags, accessories"},
        {"key": "beauty",      "name": "Beauty & Skincare",      "emoji": "💄", "desc": "Skincare, makeup, haircare"},
        {"key": "food",        "name": "Food & Restaurant",      "emoji": "🍱", "desc": "Meals, drinks, delivery"},
        {"key": "electronics", "name": "Electronics & Gadgets",  "emoji": "⚡", "desc": "Phones, laptops, accessories"},
        {"key": "booking",     "name": "Booking & Appointments", "emoji": "📅", "desc": "Salons, clinics, consultants"},
        {"key": "lead_gen",    "name": "Lead Generation",        "emoji": "🔥", "desc": "Real estate, insurance, agencies"},
        {"key": "support",     "name": "Customer Support",       "emoji": "💬", "desc": "FAQs, info, escalation"},
    ]
