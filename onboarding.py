# ══════════════════════════════════════════════════════
# JORDAN v5.1 — CLIENT ONBOARDING
# /onboard → step-by-step new client setup
# ══════════════════════════════════════════════════════

import os
import re
import json
from flask import Blueprint, request, jsonify, redirect, url_for, session
import database as db_layer
from templates_config import TEMPLATES

onboarding = Blueprint("onboarding", __name__)

ADMIN_SECRET   = os.environ.get("ADMIN_SECRET", "CodedLabs2025")
CATALOG_BASE   = os.environ.get("CATALOG_BASE_URL", "https://bot-test-wddr.onrender.com/shop")


# Session-based state for onboarding
def _get_onboard_state():
    if "onboarding" not in session:
        session["onboarding"] = {}
    return session["onboarding"]


# ─────────────────────────────────────────────────────
# STEP 0: Landing page
# ─────────────────────────────────────────────────────

@onboarding.route("/onboard")
def onboard_landing():
    return _render("""
<div class="hero">
  <div class="hero-icon">⚡</div>
  <h1>Start selling on WhatsApp</h1>
  <p>Set up your AI-powered WhatsApp store in minutes. No code required.</p>
  <div class="steps-preview">
    <div class="step-dot active">1</div><div class="step-line"></div>
    <div class="step-dot">2</div><div class="step-line"></div>
    <div class="step-dot">3</div><div class="step-line"></div>
    <div class="step-dot">4</div>
  </div>
  <div class="steps-labels">
    <span>Account</span><span>Template</span><span>Products</span><span>Go Live</span>
  </div>
  <a href="/onboard/step1" class="btn-primary">Get Started →</a>
</div>
""", title="Welcome to Jordan", step=0)


# ─────────────────────────────────────────────────────
# STEP 1: Business details
# ─────────────────────────────────────────────────────

@onboarding.route("/onboard/step1", methods=["GET", "POST"])
def onboard_step1():
    if request.method == "POST":
        data     = request.form
        name     = data.get("business_name", "").strip()
        slug_raw = data.get("slug", "").strip().lower()
        currency = data.get("currency", "NGN")

        # Validate
        errors = []
        if not name or len(name) < 2:
            errors.append("Business name is required.")
        if not slug_raw:
            errors.append("Store ID is required.")

        # Sanitize slug
        slug = re.sub(r"[^a-z0-9_]", "_", slug_raw)
        if len(slug) < 2:
            errors.append("Store ID must be at least 2 characters.")

        # Check slug availability
        if not errors:
            existing = db_layer.get_client_by_slug(slug)
            if existing:
                errors.append(f"Store ID '{slug}' is already taken. Try another.")

        if errors:
            return _render(_step1_form(name, slug, currency, errors), title="Create Your Account", step=1)

        # Store in session cookie (simple approach — pass via query params for stateless)
        return redirect(f"/onboard/step2?name={_q(name)}&slug={slug}&currency={currency}")

    return _render(_step1_form(), title="Create Your Account", step=1)


# ─────────────────────────────────────────────────────
# STEP 2: Choose template
# ─────────────────────────────────────────────────────

@onboarding.route("/onboard/step2", methods=["GET", "POST"])
def onboard_step2():
    name     = request.args.get("name", "")
    slug     = request.args.get("slug", "")
    currency = request.args.get("currency", "NGN")

    if request.method == "POST":
        template = request.form.get("template", "general")
        if template not in TEMPLATES:
            template = "general"
        return redirect(f"/onboard/step3?name={_q(name)}&slug={slug}&currency={currency}&template={template}")

    from templates_config import get_business_types
    business_types = get_business_types()
    template_cards = ""
    for bt in business_types:
        key = bt["key"]
        sel = " selected" if key == "commerce" else ""
        template_cards += '<div class="tcard' + sel + '" onclick="window.pickTemplate(&#39;' + key + '&#39;, this)" data-key="' + key + '">'
        template_cards += '<div class="tcard-icon">' + bt["emoji"] + '</div>'
        template_cards += '<div class="tcard-title">' + bt["name"] + '</div>'
        template_cards += '<div class="tcard-desc">' + bt["desc"] + '</div>'
        template_cards += '</div>'

    form = """<p class="sub">Pick the template that matches your business. This pre-configures your store.</p>
<form method="POST" id="template-form">
  <input type="hidden" name="template" id="template-input" value="commerce">
  <input type="hidden" name="business_name" value="""" + name + """">
  <input type="hidden" name="slug" value="""" + slug + """">
  <div class="tcard-grid">""" + template_cards + """</div>
  <button type="submit" class="btn-primary" style="width:100%;margin-top:20px">Continue →</button>
</form>
<script>
window.pickTemplate=function(key,el){
  document.querySelectorAll('.tcard').forEach(function(c){c.classList.remove('selected');});
  el.classList.add('selected');
  document.getElementById('template-input').value=key;
};
</script>"""

    return _render(form, title="Choose Your Store Type", step=2)


# ─────────────────────────────────────────────────────
# STEP 3: Add first products (and create account)
# ─────────────────────────────────────────────────────

@onboarding.route("/onboard/step3", methods=["GET", "POST"])
def onboard_step3():
    name     = request.args.get("name", "")
    slug     = request.args.get("slug", "")
    currency = request.args.get("currency", "NGN")
    template = request.args.get("template", "general")

    if request.method == "POST":
        # Create the client record now
        existing = db_layer.get_client_by_slug(slug)
        if not existing:
            db_layer.create_client_record(
                slug          = slug,
                business_name = name,
                template      = template,
                currency      = currency
            )

        # Add submitted products
        products_json = request.form.get("products_json", "[]")
        try:
            products = json.loads(products_json)
            client   = db_layer.get_client_by_slug(slug)
            if client:
                for p in products:
                    if p.get("name") and p.get("price"):
                        db_layer.create_product(
                            client_id   = str(client["id"]),
                            name        = p["name"],
                            price       = float(p["price"]),
                            description = p.get("description", ""),
                            stock       = int(p.get("stock", 10)),
                            category    = p.get("category", "")
                        )
        except Exception as e:
            pass  # Non-blocking

        return redirect(f"/onboard/step4?slug={slug}&name={_q(name)}&template={template}")

    t_config = TEMPLATES.get(template, TEMPLATES["general"])
    cats     = json.dumps(t_config.get("categories", []))

    form = f"""
<p class="sub">Add your first products. You can always add more later from your dashboard.</p>
<div id="products-container"></div>
<button type="button" onclick="addProduct()" class="btn-secondary" style="width:100%;margin:12px 0">
  + Add Product
</button>
<form id="products-form" method="POST">
  <input type="hidden" name="products_json" id="products_json" value="[]">
  <button type="button" onclick="submitProducts()" class="btn-primary" style="width:100%">
    Save Products & Continue →
  </button>
  <a href="/onboard/step4?slug={slug}&name={_q(name)}&template={template}" 
     style="display:block;text-align:center;margin-top:12px;color:#888;font-size:13px">
    Skip for now, I'll add products later
  </a>
</form>
<script>
var CATS={cats};
var products=[];
function addProduct(){{
  var id=Date.now();
  var div=document.createElement('div');
  div.className='product-entry';
  div.id='pe_'+id;
  div.innerHTML=`
    <div class="pe-row">
      <input type="text" placeholder="Product name *" class="inp" id="name_${{id}}" required>
      <input type="number" placeholder="Price *" class="inp" id="price_${{id}}" min="0" required>
    </div>
    <div class="pe-row">
      <input type="text" placeholder="Description" class="inp" id="desc_${{id}}">
      <input type="number" placeholder="Stock qty" class="inp" id="stock_${{id}}" value="10" min="0">
    </div>
    <select class="inp" id="cat_${{id}}" style="margin-bottom:8px">
      <option value="">Select category</option>
      ${{CATS.map(c=>`<option value="${{c}}">${{c}}</option>`).join('')}}
    </select>
    <button type="button" onclick="removeProduct(${{id}})" class="btn-danger-sm">Remove</button>
  `;
  document.getElementById('products-container').appendChild(div);
  products.push(id);
}}
function removeProduct(id){{
  document.getElementById('pe_'+id).remove();
  products=products.filter(p=>p!==id);
}}
function submitProducts(){{
  var data=products.map(id=>{{
    return {{
      name:document.getElementById('name_'+id)?.value||'',
      price:document.getElementById('price_'+id)?.value||0,
      description:document.getElementById('desc_'+id)?.value||'',
      stock:document.getElementById('stock_'+id)?.value||10,
      category:document.getElementById('cat_'+id)?.value||''
    }};
  }}).filter(p=>p.name&&p.price);
  document.getElementById('products_json').value=JSON.stringify(data);
  document.getElementById('products-form').submit();
}}
// Add one product row automatically
addProduct();
</script>
"""
    return _render(form, title="Add Your Products", step=3)


# ─────────────────────────────────────────────────────
# STEP 4: Connect WhatsApp & Go Live
# ─────────────────────────────────────────────────────

@onboarding.route("/onboard/step4", methods=["GET", "POST"])
def onboard_step4():
    slug     = request.args.get("slug", "")
    name     = request.args.get("name", slug)
    template = request.args.get("template", "general")
    t_cfg    = TEMPLATES.get(template, TEMPLATES["general"])

    if request.method == "POST":
        # Save WhatsApp connection details
        phone_number_id = request.form.get("phone_number_id", "").strip()
        wa_token        = request.form.get("wa_token", "").strip()
        wa_number       = request.form.get("wa_number", "").strip()
        greeting        = request.form.get("greeting", t_cfg["greeting"]).strip()

        client = db_layer.get_client_by_slug(slug)
        if client:
            updates = {"greeting": greeting}
            if phone_number_id:
                updates["phone_number_id"] = phone_number_id
            if wa_token:
                updates["wa_token"] = wa_token
            if wa_number:
                updates["whatsapp_number"] = wa_number
            db_layer.update_client(str(client["id"]), updates)

        return redirect(f"/onboard/done?slug={slug}&name={_q(name)}")

    app_url   = os.environ.get("CATALOG_BASE_URL", "https://your-app.onrender.com/shop").rsplit("/shop", 1)[0]
    verify_tk = os.environ.get("VERIFY_TOKEN", "jordan_verify_2025")
    t_cfg     = TEMPLATES.get(template, TEMPLATES["general"])

    content = f"""
<p class="sub">Connect your WhatsApp Business account. You can skip this for now and update it from your dashboard.</p>

<div class="info-box">
  <strong>📋 Your webhook details (set in Meta for Developers)</strong><br><br>
  <div class="code-row"><span class="code-label">Webhook URL</span>
    <code>{app_url}/webhook</code></div>
  <div class="code-row"><span class="code-label">Verify Token</span>
    <code>{verify_tk}</code></div>
  <div class="code-row"><span class="code-label">Subscribe to</span>
    <code>messages</code></div>
</div>

<form method="POST" style="margin-top:20px">
  <label class="field-label">Phone Number ID <span class="hint">(from Meta → WhatsApp → API Setup)</span></label>
  <input type="text" name="phone_number_id" class="inp" placeholder="e.g. 123456789012345">

  <label class="field-label">WhatsApp Access Token <span class="hint">(Meta permanent token)</span></label>
  <input type="text" name="wa_token" class="inp" placeholder="EAAxxxxxxx...">

  <label class="field-label">WhatsApp Number <span class="hint">(with country code, no +)</span></label>
  <input type="text" name="wa_number" class="inp" placeholder="2348012345678">

  <label class="field-label">Store Greeting Message</label>
  <textarea name="greeting" class="inp" rows="3" style="resize:vertical">{t_cfg['greeting']}</textarea>

  <button type="submit" class="btn-primary" style="width:100%;margin-top:16px">
    Finish Setup →
  </button>
  <a href="/onboard/done?slug={slug}&name={_q(name)}"
     style="display:block;text-align:center;margin-top:12px;color:#888;font-size:13px">
    Skip for now
  </a>
</form>
"""
    return _render(content, title="Connect WhatsApp", step=4)


# ─────────────────────────────────────────────────────
# DONE
# ─────────────────────────────────────────────────────

@onboarding.route("/onboard/done")
def onboard_done():
    slug    = request.args.get("slug", "")
    name    = request.args.get("name", slug)
    app_url = os.environ.get("CATALOG_BASE_URL", "https://your-app.onrender.com/shop").rsplit("/shop", 1)[0]
    secret  = ADMIN_SECRET

    content = f"""
<div class="done-screen">
  <div class="done-icon">🚀</div>
  <h2>You're live, {name}!</h2>
  <p>Your WhatsApp store is ready. Here are your links:</p>

  <div class="link-cards">
    <a href="{app_url}/shop/{slug}" target="_blank" class="link-card">
      <span class="lc-icon">🛍️</span>
      <div>
        <strong>Your Storefront</strong>
        <p>{app_url}/shop/{slug}</p>
      </div>
    </a>
    <a href="{app_url}/dashboard/{slug}?secret={secret}" target="_blank" class="link-card">
      <span class="lc-icon">⚙️</span>
      <div>
        <strong>Product Dashboard</strong>
        <p>Manage products, orders, inventory</p>
      </div>
    </a>
    <a href="{app_url}/admin/{slug}?secret={secret}" target="_blank" class="link-card">
      <span class="lc-icon">📊</span>
      <div>
        <strong>Admin Panel</strong>
        <p>Orders, customers, broadcasts</p>
      </div>
    </a>
  </div>

  <div class="next-steps">
    <strong>What's next:</strong>
    <ol>
      <li>Share your storefront link on Instagram, Twitter, or with customers directly</li>
      <li>Add more products from your dashboard</li>
      <li>Test by sending a WhatsApp message to your connected number</li>
    </ol>
  </div>
</div>
"""
    return _render(content, title="You're Live!", step=5)


# ─────────────────────────────────────────────────────
# SHARED RENDERER
# ─────────────────────────────────────────────────────

def _q(s: str) -> str:
    from urllib.parse import quote
    return quote(s) if s else ""


def _render(content: str, title: str = "Jordan Setup", step: int = 0) -> str:
    step_labels  = ["", "Account", "Template", "Products", "WhatsApp", "Done"]
    progress_pct = int((step / 5) * 100)

    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — Jordan</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{--bg:#07070e;--s:#10101a;--b:#1c1c2a;--g:#25D366;--text:#dde;--m:#888;--red:#ef4444}}
body{{font-family:'DM Sans',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;display:flex;flex-direction:column;align-items:center;padding:20px 16px 60px}}
.brand{{display:flex;align-items:center;gap:8px;font-size:18px;font-weight:700;margin-bottom:32px;color:#fff}}
.brand span{{font-size:22px}}
.card{{background:var(--s);border:1px solid var(--b);border-radius:18px;padding:28px 24px;width:100%;max-width:520px}}
.progress{{width:100%;max-width:520px;margin-bottom:20px}}
.progress-bar{{background:var(--b);border-radius:99px;height:4px;overflow:hidden}}
.progress-fill{{background:var(--g);height:100%;border-radius:99px;transition:width .4s ease;width:{progress_pct}%}}
.progress-label{{font-size:11px;color:var(--m);margin-top:6px;text-align:right}}{'' if step == 0 else ''}
h1,h2{{font-size:20px;font-weight:700;margin-bottom:8px}}
.sub{{font-size:13px;color:var(--m);margin-bottom:20px;line-height:1.6}}
.inp{{width:100%;background:#0b0b15;border:1px solid var(--b);border-radius:10px;color:var(--text);padding:12px;font-family:inherit;font-size:14px;outline:none;transition:border-color .2s;margin-bottom:12px;display:block}}
.inp:focus{{border-color:var(--g)}}
textarea.inp{{resize:vertical;min-height:80px}}
.field-label{{font-size:12px;color:var(--m);margin-bottom:6px;display:block;font-weight:600;text-transform:uppercase;letter-spacing:.5px}}
.hint{{font-weight:400;text-transform:none;letter-spacing:0;opacity:.7}}
.btn-primary{{background:var(--g);color:#000;border:none;padding:14px 28px;border-radius:10px;font-weight:700;font-size:14px;cursor:pointer;font-family:inherit;text-decoration:none;display:inline-block;transition:opacity .15s}}
.btn-primary:hover{{opacity:.85}}
.btn-secondary{{background:var(--b);color:var(--text);border:1px solid #2a2a3a;padding:12px 20px;border-radius:10px;font-weight:600;font-size:13px;cursor:pointer;font-family:inherit;text-decoration:none;display:inline-block;transition:all .15s}}
.btn-secondary:hover{{border-color:var(--g);color:var(--g)}}
.btn-danger-sm{{background:none;border:1px solid var(--red);color:var(--red);padding:5px 12px;border-radius:6px;font-size:11px;cursor:pointer;font-family:inherit;margin-top:4px}}
.error{{background:#1a0000;border:1px solid var(--red);border-radius:8px;padding:10px 14px;font-size:13px;color:var(--red);margin-bottom:14px}}
.template-grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
.template-card{{cursor:pointer;position:relative}}
.template-card input{{position:absolute;opacity:0;pointer-events:none}}
.tc-inner{{background:var(--bg);border:2px solid var(--b);border-radius:12px;padding:14px;text-align:center;transition:all .2s}}
.template-card input:checked+.tc-inner{{border-color:var(--g);background:#0a1f0f}}
.tc-emoji{{font-size:28px;margin-bottom:6px}}
.tc-name{{font-size:13px;font-weight:700;margin-bottom:3px}}
.tc-desc{{font-size:11px;color:var(--m)}}
.product-entry{{background:var(--bg);border:1px solid var(--b);border-radius:12px;padding:14px;margin-bottom:12px}}
.pe-row{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
.info-box{{background:#0a1a0f;border:1px solid #1a3020;border-radius:12px;padding:16px;margin-bottom:16px;font-size:13px}}
.code-row{{display:flex;align-items:center;gap:10px;margin-top:10px}}
.code-label{{font-size:11px;color:var(--m);min-width:100px;font-weight:600;text-transform:uppercase}}
code{{background:#0b0b15;border:1px solid var(--b);border-radius:6px;padding:4px 10px;font-size:12px;color:var(--g);word-break:break-all}}
.hero{{text-align:center;padding:20px 0}}
.hero-icon{{font-size:48px;margin-bottom:16px}}
.hero h1{{font-size:24px;margin-bottom:10px}}
.hero p{{color:var(--m);font-size:14px;margin-bottom:28px;line-height:1.6}}
.steps-preview{{display:flex;align-items:center;justify-content:center;gap:0;margin-bottom:8px}}
.step-dot{{width:28px;height:28px;border-radius:50%;border:2px solid var(--b);display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;color:var(--m);background:var(--bg)}}
.step-dot.active{{border-color:var(--g);color:var(--g);background:#0a1f0f}}
.step-line{{width:32px;height:2px;background:var(--b)}}
.steps-labels{{display:flex;justify-content:space-between;font-size:10px;color:var(--m);margin-bottom:24px;padding:0 4px}}
.done-screen{{text-align:center}}
.done-icon{{font-size:56px;margin-bottom:16px}}
.done-screen h2{{font-size:22px;margin-bottom:8px}}
.done-screen p{{color:var(--m);font-size:14px;margin-bottom:24px}}
.link-cards{{display:flex;flex-direction:column;gap:10px;margin-bottom:24px}}
.link-card{{background:var(--bg);border:1px solid var(--b);border-radius:12px;padding:14px 16px;display:flex;align-items:center;gap:14px;text-decoration:none;color:var(--text);transition:border-color .2s}}
.link-card:hover{{border-color:var(--g)}}
.lc-icon{{font-size:24px}}
.link-card strong{{font-size:13px;font-weight:700;display:block;margin-bottom:3px}}
.link-card p{{font-size:11px;color:var(--m)}}
.next-steps{{background:var(--bg);border:1px solid var(--b);border-radius:12px;padding:16px;text-align:left}}
.next-steps strong{{font-size:12px;text-transform:uppercase;letter-spacing:.5px;color:var(--m);display:block;margin-bottom:10px}}
.next-steps ol{{padding-left:18px;font-size:13px;line-height:2;color:var(--m)}}
select.inp{{appearance:none}}
    .tcard-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin:16px 0}}
    .tcard{{background:var(--bg);border:2px solid var(--b);border-radius:12px;padding:14px 12px;cursor:pointer;transition:all .2s;text-align:center}}
    .tcard:hover{{border-color:var(--g);transform:translateY(-2px)}}
    .tcard.selected{{border-color:var(--g);background:rgba(20,184,166,.08);box-shadow:0 0 20px rgba(20,184,166,.1)}}
    .tcard-icon{{font-size:28px;margin-bottom:6px}}
    .tcard-title{{font-size:13px;font-weight:700;margin-bottom:3px}}
    .tcard-desc{{font-size:10px;color:var(--m);line-height:1.4}}
    .secret-box{{background:var(--bg);border:1px solid var(--b);border-radius:12px;padding:16px;margin-bottom:20px;text-align:center}}
    .secret-box strong{{display:block;font-size:12px;color:var(--m);margin-bottom:8px}}
    .secret-box code{{font-size:18px;font-weight:700;color:var(--g);background:#0a1f0f;padding:6px 14px;border-radius:8px;letter-spacing:1px}}
    .secret-box p{{font-size:11px;color:var(--m);margin-top:8px}}
    select.inp{{appearance:none}}
</style>
</head><body>
<div class="brand"><span>⚡</span> Jordan by CodedLabs</div>
{"" if step == 0 else f'''<div class="progress">
  <div class="progress-bar"><div class="progress-fill"></div></div>
  <div class="progress-label">Step {step} of 4{f" — {step_labels[step]}" if step <= 4 else " — Done"}</div>
</div>'''}
<div class="card">
  <h1>{title}</h1>
  {content}
</div>
</body></html>"""


def _step1_form(name: str = "", slug: str = "", currency: str = "NGN", errors: list = None) -> str:
    error_html = ""
    if errors:
        error_html = "<div class='error'>" + "<br>".join(errors) + "</div>"

    currencies = ["NGN", "GHS", "KES", "ZAR", "USD", "GBP", "EUR", "BRL", "INR", "IDR"]
    curr_opts  = "".join(
        f'<option value="{c}" {"selected" if c == currency else ""}>{c}</option>'
        for c in currencies
    )

    return f"""
{error_html}
<p class="sub">Tell us about your business. Your store ID will be used in your storefront URL.</p>
<form method="POST">
  <label class="field-label">Business Name</label>
  <input type="text" name="business_name" class="inp" placeholder="e.g. Fashion Hub Lagos"
         value="{name}" required autofocus>

  <label class="field-label">Store ID <span class="hint">(your-app.com/shop/this-id)</span></label>
  <input type="text" name="slug" class="inp" placeholder="e.g. fashion_hub"
         value="{slug}" pattern="[a-z0-9_]+" required
         oninput="this.value=this.value.toLowerCase().replace(/[^a-z0-9_]/g,'_')">

  <label class="field-label">Currency</label>
  <select name="currency" class="inp">{curr_opts}</select>

  <button type="submit" class="btn-primary" style="width:100%">Continue →</button>
</form>
"""

def _step2_form(name: str = "", slug: str = "", template: str = "commerce") -> str:
    import json as _json
    cats = [
        ("commerce", "🛍️", "Online Store", "Sell products on WhatsApp with cart & checkout"),
        ("food", "🍱", "Food & Restaurant", "Menu, orders, delivery management"),
        ("fashion", "👗", "Fashion & Clothing", "Clothes, shoes, bags, accessories"),
        ("beauty", "💄", "Beauty & Skincare", "Skincare, makeup, haircare"),
        ("electronics", "⚡", "Electronics", "Phones, laptops, accessories"),
        ("booking", "📅", "Booking & Appointments", "Salons, clinics, consultants"),
        ("clinic", "🏥", "Medical Clinic", "Doctor appointments, prescriptions"),
        ("salon", "💇", "Salon & Spa", "Hair, nails, beauty appointments"),
        ("consultant", "💼", "Consulting", "Professional services, coaching"),
        ("lead_gen", "🔥", "Lead Generation", "Capture & qualify potential customers"),
        ("real_estate", "🏠", "Real Estate", "Property listings, inquiries, viewings"),
        ("agency", "🎯", "Digital Agency", "Service packages, client inquiries"),
        ("support", "🎧", "Customer Support", "FAQ bot, ticket system"),
        ("general", "📦", "General Business", "Custom setup for any business"),
    ]

    cards_html = []
    for key, icon, title, desc in cats:
        sel = "selected" if key == template else ""
        cards_html.append(
            '<div class="tcard ' + sel + '" onclick="window.selectTemplate(&#39;' + 
            key + '&#39;, this)" data-key="' + key + '">'
            '<div class="tcard-icon">' + icon + '</div>'
            '<div class="tcard-title">' + title + '</div>'
            '<div class="tcard-desc">' + desc + '</div>'
            '</div>'
        )
    cards = "".join(cards_html)

    return """<p class="sub">Pick the template that best matches your business. This pre-configures your store with the right features.</p>
    <form method="POST" id="template-form">
      <input type="hidden" name="template" id="template-input" value="""" + template + """">
      <input type="hidden" name="business_name" value="""" + name + """">
      <input type="hidden" name="slug" value="""" + slug + """">
      <div class="tcard-grid">""" + cards + """</div>
      <button type="submit" class="btn-primary" style="width:100%;margin-top:20px">Continue →</button>
    </form>
    <script>
    window.selectTemplate=function(key,el){
      document.querySelectorAll('.tcard').forEach(function(c){c.classList.remove('selected');});
      el.classList.add('selected');
      document.getElementById('template-input').value=key;
    };
    </script>"""
