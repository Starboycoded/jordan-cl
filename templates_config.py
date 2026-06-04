# ══════════════════════════════════════════════════════
# JORDAN v5.2 — TEMPLATE CONFIGURATIONS
# Fashion | Beauty | Electronics | Food | General
# ══════════════════════════════════════════════════════

TEMPLATES = {

    "fashion": {
        "name":         "Fashion",
        "emoji":        "👗",
        "description":  "Clothing, shoes, bags, accessories",
        "tagline":      "Style delivered to your door",
        "primary":      "#C9A84C",      # Gold
        "accent":       "#1a0a00",      # Dark brown
        "bg":           "#0d0800",
        "card_bg":      "#150e00",
        "border":       "#2a1f00",
        "categories":   ["Dresses", "Tops", "Bottoms", "Shoes", "Bags", "Accessories", "Sets"],
        "checkout_extras": [
            {"key": "size",  "question": "What size do you need? (XS/S/M/L/XL/XXL)"},
            {"key": "color", "question": "Any color preference? (or reply 'as shown')"}
        ],
        "ai_persona": """You are Jordan, a stylish and enthusiastic fashion consultant.
You have great taste and love helping customers find the perfect outfit.
- Use fashion-forward language: "gorgeous", "stunning", "perfect for your wardrobe"
- Always ask about occasion (casual, work, event) to give better recommendations
- Mention outfit combinations and styling tips
- Be encouraging and body-positive
- When describing products, paint a picture: fabric feel, how it fits, what to pair it with
- Upsell naturally: "This pairs beautifully with our [product]"
""",
        "greeting": "Welcome! 👗 I'm Jordan, your personal fashion assistant. Looking for something specific, or shall I show you what's trending?"
    },

    "beauty": {
        "name":         "Beauty",
        "emoji":        "💄",
        "description":  "Skincare, makeup, haircare, wellness",
        "tagline":      "Your glow, delivered",
        "primary":      "#E8A0BF",      # Pink
        "accent":       "#1a0010",
        "bg":           "#0d0008",
        "card_bg":      "#150010",
        "border":       "#2a001a",
        "categories":   ["Skincare", "Makeup", "Haircare", "Fragrances", "Nail Care", "Body Care", "Wellness"],
        "checkout_extras": [
            {"key": "skin_type", "question": "What's your skin type? (oily / dry / combination / normal / sensitive)"},
            {"key": "concern",   "question": "Any specific skin concern? (e.g. acne, dark spots, anti-aging, hydration)"}
        ],
        "ai_persona": """You are Jordan, a knowledgeable and warm beauty advisor.
You genuinely care about helping customers find products that work for their skin and lifestyle.
- Ask about skin type and concerns before recommending skincare
- Mention key ingredients and what they do (e.g. "This has niacinamide which reduces dark spots")
- Be warm, encouraging and inclusive — beauty is for everyone
- Share usage tips: "Apply this at night for best results"
- Be honest — don't oversell, build trust
- Use language like "your skin will love this", "perfect for your concern"
""",
        "greeting": "Hi beautiful! 💄 I'm Jordan, your beauty advisor. Are you looking for skincare, makeup, or something else? Tell me what you need and I'll find the perfect match for you!"
    },

    "electronics": {
        "name":         "Electronics",
        "emoji":        "⚡",
        "description":  "Phones, gadgets, accessories, computers",
        "tagline":      "Tech that works for you",
        "primary":      "#25D366",      # Green (WhatsApp native)
        "accent":       "#07070e",
        "bg":           "#07070e",
        "card_bg":      "#0f1a14",
        "border":       "#1a3020",
        "categories":   ["Phones", "Laptops", "Accessories", "Audio", "Smart Home", "Gaming", "Cameras"],
        "checkout_extras": [
            {"key": "warranty", "question": "Would you like to add a warranty? (yes / no)"},
        ],
        "ai_persona": """You are Jordan, a knowledgeable and precise electronics specialist.
You know your specs and help customers make informed buying decisions.
- Be factual and accurate — mention specs, compatibility, and key features
- Ask about use case: "Is this for work, gaming, or general use?"
- Compare options when relevant: "The X is better for battery life, Y for performance"
- Mention compatibility where relevant (e.g. iPhone vs Android accessories)
- Be helpful about warranties and after-sales support
- Don't oversell — if something isn't the best fit, say so and suggest the right product
- Use technical terms but always explain them simply
""",
        "greeting": "Hey! ⚡ I'm Jordan, your tech advisor. What are you looking for today? Tell me what you need it for and I'll point you to the right product."
    },

    "food": {
        "name":         "Food",
        "emoji":        "🍱",
        "description":  "Meals, snacks, drinks, groceries",
        "tagline":      "Fresh food, fast delivery",
        "primary":      "#FF6B35",      # Orange
        "accent":       "#0d0500",
        "bg":           "#0d0500",
        "card_bg":      "#150900",
        "border":       "#2a1200",
        "categories":   ["Meals", "Snacks", "Drinks", "Groceries", "Pastries", "Proteins", "Combos"],
        "checkout_extras": [
            {"key": "spice_level", "question": "Spice level preference? (mild / medium / hot / extra hot)"},
            {"key": "delivery_time", "question": "Preferred delivery time? (ASAP / specific time, e.g. 2pm)"}
        ],
        "ai_persona": """You are Jordan, a friendly and enthusiastic food concierge.
You make food sound absolutely delicious and help customers order exactly what they'll love.
- Use appetizing language: "freshly made", "hot and ready", "bursting with flavor"
- Ask about dietary preferences when relevant (vegetarian, allergies, spice level)
- Suggest combo deals or add-ons naturally: "Want to add a drink to that?"
- Be fast and efficient — food customers want quick responses
- Mention estimated delivery time proactively
- Be cheerful and create excitement around the food
""",
        "greeting": "Hey foodie! 🍱 I'm Jordan. Hungry? Let me help you order something amazing. What are you in the mood for today?"
    },

    "general": {
        "name":         "General",
        "emoji":        "🛍️",
        "description":  "General retail and commerce",
        "tagline":      "Everything you need, delivered",
        "primary":      "#25D366",
        "accent":       "#07070e",
        "bg":           "#07070e",
        "card_bg":      "#0f1a14",
        "border":       "#1a3020",
        "categories":   ["Products", "Services", "Bundles", "Offers"],
        "checkout_extras": [],
        "ai_persona": """You are Jordan, a helpful and professional sales assistant.
You help customers find what they need and make the ordering process smooth.
- Be friendly, clear, and concise
- Understand what the customer needs before recommending
- Be honest about stock, pricing, and delivery
- Guide customers through the ordering process step by step
""",
        "greeting": "Hi there! 👋 I'm Jordan, your shopping assistant. How can I help you today?"
    }
}


def get_template(template_name: str) -> dict:
    """Return template config, defaulting to general."""
    return TEMPLATES.get(template_name, TEMPLATES["general"])


def get_template_names() -> list:
    return list(TEMPLATES.keys())


def get_ai_persona(template_name: str) -> str:
    return get_template(template_name).get("ai_persona", TEMPLATES["general"]["ai_persona"])


def get_checkout_extras(template_name: str) -> list:
    """Return extra checkout questions for this template."""
    return get_template(template_name).get("checkout_extras", [])


def get_storefront_theme(template_name: str) -> dict:
    """Return CSS color variables for this template's storefront."""
    t = get_template(template_name)
    return {
        "primary": t.get("primary", "#25D366"),
        "bg":      t.get("bg",      "#07070e"),
        "card_bg": t.get("card_bg", "#0f1a14"),
        "border":  t.get("border",  "#1a3020"),
        "tagline": t.get("tagline", ""),
        "emoji":   t.get("emoji",   "🛍️"),
    }
