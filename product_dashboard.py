# ══════════════════════════════════════════════════════
# JORDAN v5.1 — PRODUCT MANAGEMENT DASHBOARD
# /dashboard/{slug} → full product CRUD + image upload
# ══════════════════════════════════════════════════════

import os
import json
import base64
from flask import Blueprint, request, jsonify, abort
import database as db_layer
import storage as store
from templates_config import get_template

dashboard = Blueprint("dashboard", __name__)

ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "CodedLabs2025")
CATALOG_BASE = os.environ.get("CATALOG_BASE_URL", "https://bot-test-wddr.onrender.com/shop")


def _auth(req) -> bool:
    return (req.args.get("secret") == ADMIN_SECRET or
            req.headers.get("X-Admin-Secret") == ADMIN_SECRET)


# ─────────────────────────────────────────────────────
# MAIN DASHBOARD PAGE
# ─────────────────────────────────────────────────────

@dashboard.route("/dashboard/<slug>")
def product_dashboard(slug: str):
    if not _auth(request):
        return _unauth()

    client = db_layer.get_client_by_slug(slug)
    if not client:
        return "Store not found.", 404

    t_cfg     = get_template(client.get("template", "general"))
    primary   = t_cfg.get("primary", "#25D366")
    cats      = json.dumps(t_cfg.get("categories", []))
    biz_name  = client.get("business_name", slug)
    currency  = client.get("currency", "NGN")
    secret    = ADMIN_SECRET
    app_url   = CATALOG_BASE.rsplit("/shop", 1)[0]

    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{biz_name} — Product Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{--bg:#07070e;--s:#10101a;--b:#1c1c2a;--g:{primary};--text:#dde;--m:#666;--red:#ef4444;--warn:#f59e0b}}
body{{font-family:'DM Sans',sans-serif;background:var(--bg);color:var(--text);min-height:100vh}}
header{{background:var(--s);border-bottom:1px solid var(--b);padding:14px 24px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:20}}
.hdr-left{{display:flex;align-items:center;gap:12px}}
header h1{{font-size:15px;font-weight:700}}
.tag{{font-size:10px;background:rgba(255,255,255,.07);color:var(--m);padding:3px 10px;border-radius:20px}}
.hdr-links{{display:flex;gap:10px}}
.hdr-btn{{background:var(--b);border:1px solid #2a2a3a;color:var(--text);padding:7px 14px;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;text-decoration:none;font-family:inherit;transition:all .15s}}
.hdr-btn:hover,.hdr-btn.active{{border-color:var(--g);color:var(--g)}}
.wrap{{max-width:1100px;margin:0 auto;padding:24px 20px 80px}}
.toolbar{{display:flex;align-items:center;gap:12px;margin-bottom:22px;flex-wrap:wrap}}
.search{{flex:1;min-width:200px;background:var(--s);border:1px solid var(--b);border-radius:10px;color:var(--text);padding:10px 14px;font-family:inherit;font-size:13px;outline:none}}
.search:focus{{border-color:var(--g)}}
select.filt{{background:var(--s);border:1px solid var(--b);border-radius:10px;color:var(--text);padding:10px 12px;font-family:inherit;font-size:13px;outline:none}}
.btn{{border:none;padding:10px 20px;border-radius:10px;font-weight:700;font-size:13px;cursor:pointer;font-family:inherit;transition:opacity .15s}}
.btn-g{{background:var(--g);color:#000}}.btn-g:hover{{opacity:.85}}
.btn-r{{background:var(--red);color:#fff}}.btn-r:hover{{opacity:.85}}
.btn-o{{background:var(--warn);color:#000}}.btn-o:hover{{opacity:.85}}
.btn-ghost{{background:var(--b);color:var(--text);border:1px solid #2a2a3a}}.btn-ghost:hover{{border-color:var(--g);color:var(--g)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px}}
.pcard{{background:var(--s);border:1px solid var(--b);border-radius:14px;overflow:hidden;transition:all .2s;position:relative}}
.pcard:hover{{border-color:var(--g);transform:translateY(-2px)}}
.pcard.inactive{{opacity:.45}}
.pcard-img{{width:100%;height:160px;object-fit:cover;display:block;background:#0b0b15;cursor:pointer}}
.pcard-img-ph{{width:100%;height:160px;display:flex;align-items:center;justify-content:center;font-size:40px;background:#0d0d18;cursor:pointer;transition:background .2s}}
.pcard-img-ph:hover{{background:#141425}}
.pcard-body{{padding:12px}}
.pcard-name{{font-size:13px;font-weight:700;margin-bottom:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.pcard-desc{{font-size:11px;color:var(--m);margin-bottom:8px;min-height:28px;line-height:1.4;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}}
.pcard-meta{{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}}
.pcard-price{{font-size:14px;font-weight:700;color:var(--g)}}
.pcard-stock{{font-size:11px;font-weight:700;padding:3px 8px;border-radius:20px}}
.stock-ok{{background:rgba(37,211,102,.1);color:#25D366}}
.stock-low{{background:rgba(245,158,11,.1);color:var(--warn)}}
.stock-out{{background:rgba(239,68,68,.1);color:var(--red)}}
.pcard-actions{{display:flex;gap:6px}}
.pcard-actions button{{flex:1;padding:7px 0;border-radius:8px;font-size:11px;font-weight:700;cursor:pointer;font-family:inherit;border:none;transition:opacity .15s}}
.act-edit{{background:var(--b);color:var(--text);border:1px solid #2a2a3a!important}}.act-edit:hover{{border-color:var(--g)!important;color:var(--g)}}
.act-del{{background:rgba(239,68,68,.1);color:var(--red)}}.act-del:hover{{background:rgba(239,68,68,.2)}}
.badge-off{{position:absolute;top:10px;left:10px;background:var(--red);color:#fff;font-size:10px;font-weight:700;padding:3px 8px;border-radius:20px}}
.badge-low{{position:absolute;top:10px;right:10px;background:var(--warn);color:#000;font-size:10px;font-weight:700;padding:3px 8px;border-radius:20px}}
/* MODAL */
.overlay{{position:fixed;inset:0;background:rgba(0,0,0,.75);opacity:0;pointer-events:none;transition:opacity .3s;z-index:100;display:flex;align-items:center;justify-content:center;padding:16px}}
.overlay.on{{opacity:1;pointer-events:all}}
.modal{{background:var(--s);border:1px solid var(--b);border-radius:18px;width:100%;max-width:500px;max-height:90vh;overflow-y:auto;padding:24px;transform:translateY(20px);transition:transform .3s}}
.overlay.on .modal{{transform:translateY(0)}}
.modal-head{{display:flex;align-items:center;justify-content:space-between;margin-bottom:20px}}
.modal-title{{font-size:16px;font-weight:700}}
.modal-close{{background:none;border:none;color:var(--m);font-size:22px;cursor:pointer;line-height:1;padding:4px}}
.field{{margin-bottom:14px}}
label.lbl{{display:block;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:var(--m);margin-bottom:6px}}
.inp{{width:100%;background:#0b0b15;border:1px solid var(--b);border-radius:10px;color:var(--text);padding:11px 13px;font-family:inherit;font-size:13px;outline:none;transition:border-color .2s}}
.inp:focus{{border-color:var(--g)}}
textarea.inp{{resize:vertical;min-height:70px}}
.inp-row{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
/* Image upload zone */
.img-zone{{border:2px dashed var(--b);border-radius:12px;padding:20px;text-align:center;cursor:pointer;transition:all .2s;position:relative;overflow:hidden}}
.img-zone:hover,.img-zone.drag{{border-color:var(--g);background:#0a1f0f}}
.img-zone input{{position:absolute;inset:0;opacity:0;cursor:pointer}}
.img-zone-preview{{width:100%;height:160px;object-fit:cover;border-radius:8px;display:none}}
.img-zone-text{{font-size:13px;color:var(--m)}}
.img-zone-icon{{font-size:32px;margin-bottom:8px}}
.toggle-row{{display:flex;align-items:center;justify-content:space-between;padding:12px 0;border-top:1px solid var(--b);margin-top:4px}}
.toggle-lbl{{font-size:13px;font-weight:600}}
.toggle{{position:relative;width:44px;height:24px}}
.toggle input{{opacity:0;width:0;height:0}}
.toggle-slider{{position:absolute;inset:0;background:#2a2a3a;border-radius:99px;cursor:pointer;transition:.2s}}
.toggle-slider::before{{content:'';position:absolute;width:18px;height:18px;left:3px;top:3px;background:#888;border-radius:50%;transition:.2s}}
.toggle input:checked+.toggle-slider{{background:var(--g)}}
.toggle input:checked+.toggle-slider::before{{transform:translateX(20px);background:#000}}
.modal-footer{{display:flex;gap:10px;margin-top:20px}}
.modal-footer button{{flex:1}}
/* Empty state */
.empty{{text-align:center;padding:60px 20px;color:var(--m)}}
.empty-icon{{font-size:48px;margin-bottom:12px}}
.empty p{{font-size:14px;margin-bottom:20px}}
/* Toast */
#toast{{position:fixed;bottom:24px;left:50%;transform:translateX(-50%) translateY(10px);background:#1a3a24;color:#e8f5ec;padding:11px 20px;border-radius:20px;font-size:13px;opacity:0;transition:all .25s;pointer-events:none;z-index:300;border:1px solid var(--g)}}
#toast.on{{opacity:1;transform:translateX(-50%) translateY(0)}}
#toast.err{{background:#2a0a0a;border-color:var(--red);color:#fca5a5}}
/* Stats bar */
.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:22px}}
.stat{{background:var(--s);border:1px solid var(--b);border-radius:12px;padding:14px 16px}}
.stat-n{{font-size:22px;font-weight:700;margin-bottom:2px}}
.stat-l{{font-size:10px;color:var(--m);text-transform:uppercase;letter-spacing:.7px}}
</style>
</head><body>

<header>
  <div class="hdr-left">
    <h1>⚡ {biz_name}</h1>
    <span class="tag">Product Dashboard</span>
  </div>
  <div class="hdr-links">
    <a href="{CATALOG_BASE}/{slug}" target="_blank" class="hdr-btn">🛍️ Storefront</a>
    <a href="/admin/{slug}?secret={secret}" target="_blank" class="hdr-btn">📊 Orders</a>
    <a href="/dashboard/{slug}/settings?secret={secret}" class="hdr-btn">⚙️ Settings</a>
  </div>
</header>

<div class="wrap">
  <div class="stats" id="statsBar">
    <div class="stat"><div class="stat-n" id="s-total" style="color:var(--g)">—</div><div class="stat-l">Products</div></div>
    <div class="stat"><div class="stat-n" id="s-active">—</div><div class="stat-l">Active</div></div>
    <div class="stat"><div class="stat-n" id="s-low" style="color:var(--warn)">—</div><div class="stat-l">Low Stock</div></div>
    <div class="stat"><div class="stat-n" id="s-out" style="color:var(--red)">—</div><div class="stat-l">Out of Stock</div></div>
  </div>

  <div class="toolbar">
    <input type="text" class="search" placeholder="🔍 Search products..." oninput="filterProducts(this.value)" id="searchBox">
    <select class="filt" onchange="filterByCategory(this.value)" id="catFilter">
      <option value="">All Categories</option>
    </select>
    <select class="filt" onchange="filterByStatus(this.value)" id="statusFilter">
      <option value="">All Status</option>
      <option value="active">Active</option>
      <option value="inactive">Inactive</option>
      <option value="low">Low Stock</option>
      <option value="out">Out of Stock</option>
    </select>
    <button class="btn btn-g" onclick="openModal()">+ Add Product</button>
  </div>

  <div class="grid" id="productsGrid">
    <div class="empty"><div class="empty-icon">📦</div><p>Loading products...</p></div>
  </div>
</div>

<!-- ADD/EDIT MODAL -->
<div class="overlay" id="modalOverlay" onclick="closeModalOutside(event)">
<div class="modal" id="modal">
  <div class="modal-head">
    <span class="modal-title" id="modalTitle">Add Product</span>
    <button class="modal-close" onclick="closeModal()">✕</button>
  </div>

  <!-- Image Upload -->
  <div class="field">
    <label class="lbl">Product Image</label>
    <div class="img-zone" id="imgZone" ondragover="onDrag(event,true)" ondragleave="onDrag(event,false)" ondrop="onDrop(event)">
      <input type="file" accept="image/*" onchange="onFileSelect(event)" id="imgInput">
      <img class="img-zone-preview" id="imgPreview" alt="preview">
      <div id="imgZoneContent">
        <div class="img-zone-icon">📷</div>
        <div class="img-zone-text">Drop image here or click to upload<br><small style="color:#444">JPG, PNG, WebP • Max 5MB</small></div>
      </div>
    </div>
    <input type="hidden" id="existingImageUrl">
  </div>

  <div class="field">
    <label class="lbl">Product Name *</label>
    <input type="text" class="inp" id="f-name" placeholder="e.g. Black Leather Bag" maxlength="100">
  </div>

  <div class="inp-row">
    <div class="field">
      <label class="lbl">Price ({currency}) *</label>
      <input type="number" class="inp" id="f-price" placeholder="0" min="0" step="0.01">
    </div>
    <div class="field">
      <label class="lbl">Stock Quantity *</label>
      <input type="number" class="inp" id="f-stock" placeholder="0" min="0">
    </div>
  </div>

  <div class="field">
    <label class="lbl">Category</label>
    <select class="inp" id="f-category">
      <option value="">Select category...</option>
    </select>
  </div>

  <div class="field">
    <label class="lbl">Description</label>
    <textarea class="inp" id="f-desc" placeholder="Short description customers will see..."></textarea>
  </div>

  <div class="toggle-row">
    <span class="toggle-lbl">Product Active (visible to customers)</span>
    <label class="toggle">
      <input type="checkbox" id="f-active" checked>
      <span class="toggle-slider"></span>
    </label>
  </div>

  <div class="modal-footer">
    <button class="btn btn-ghost" onclick="closeModal()">Cancel</button>
    <button class="btn btn-g" onclick="saveProduct()" id="saveBtn">Save Product</button>
  </div>
</div>
</div>

<!-- TOAST -->
<div id="toast"></div>

<script>
const SLUG='{slug}';
const SECRET='{secret}';
const CURRENCY='{currency}';
const CATS={cats};
const API_BASE='/api/'+SLUG;

var allProducts=[];
var editingId=null;
var selectedFile=null;
var tt;

// ── INIT ───────────────────────────────────────────
document.addEventListener('DOMContentLoaded',()=>{{
  loadProducts();
  populateCats();
}});

function populateCats(){{
  var sel=document.getElementById('catFilter');
  var fSel=document.getElementById('f-category');
  CATS.forEach(c=>{{
    sel.innerHTML+=`<option value="${{c}}">${{c}}</option>`;
    fSel.innerHTML+=`<option value="${{c}}">${{c}}</option>`;
  }});
}}

// ── LOAD ───────────────────────────────────────────
async function loadProducts(){{
  try{{
    var r=await fetch(API_BASE+'/products?secret='+SECRET);
    var d=await r.json();
    allProducts=d.products||[];
    renderProducts(allProducts);
    updateStats(allProducts);
  }}catch(e){{
    document.getElementById('productsGrid').innerHTML=
      '<div class="empty"><div class="empty-icon">⚠️</div><p>Failed to load products.</p></div>';
  }}
}}

function updateStats(prods){{
  var active=prods.filter(p=>p.active).length;
  var low=prods.filter(p=>p.active&&p.stock>0&&p.stock<=3).length;
  var out=prods.filter(p=>p.active&&p.stock<=0).length;
  document.getElementById('s-total').textContent=prods.length;
  document.getElementById('s-active').textContent=active;
  document.getElementById('s-low').textContent=low;
  document.getElementById('s-out').textContent=out;
}}

// ── RENDER ─────────────────────────────────────────
function renderProducts(prods){{
  var grid=document.getElementById('productsGrid');
  if(!prods.length){{
    grid.innerHTML='<div class="empty"><div class="empty-icon">📦</div><p>No products yet. Add your first product!</p><button class="btn btn-g" onclick="openModal()">+ Add Product</button></div>';
    return;
  }}
  grid.innerHTML=prods.map(p=>{{
    var stockClass=p.stock<=0?'stock-out':p.stock<=3?'stock-low':'stock-ok';
    var stockLabel=p.stock<=0?'Out of Stock':p.stock<=3?`Low: ${{p.stock}}`:`Stock: ${{p.stock}}`;
    var img=p.image_url
      ?`<img class="pcard-img" src="${{p.image_url}}" alt="${{p.name}}" onclick="openModal(${{p.id}})" loading="lazy">`
      :`<div class="pcard-img-ph" onclick="openModal(${{p.id}})">🛍️</div>`;
    var badges=(!p.active?'<span class="badge-off">OFF</span>':'')+(p.stock>0&&p.stock<=3?'<span class="badge-low">LOW</span>':'');
    return `<div class="pcard ${{p.active?'':'inactive'}}" id="pc${{p.id}}">
      ${{badges}}
      ${{img}}
      <div class="pcard-body">
        <div class="pcard-name" title="${{p.name}}">${{p.name}}</div>
        <div class="pcard-desc">${{p.description||'<span style="color:#333">No description</span>'}}</div>
        <div class="pcard-meta">
          <span class="pcard-price">${{CURRENCY}} ${{Number(p.price).toLocaleString()}}</span>
          <span class="pcard-stock ${{stockClass}}">${{stockLabel}}</span>
        </div>
        <div class="pcard-actions">
          <button class="act-edit" onclick="openModal(${{p.id}})">✏️ Edit</button>
          <button class="act-del" onclick="deleteProduct(${{p.id}},'${{p.name}}')">🗑️</button>
        </div>
      </div>
    </div>`;
  }}).join('');
}}

// ── FILTER ─────────────────────────────────────────
function filterProducts(q){{renderProducts(applyFilters());}}
function filterByCategory(){{renderProducts(applyFilters());}}
function filterByStatus(){{renderProducts(applyFilters());}}

function applyFilters(){{
  var q=document.getElementById('searchBox').value.toLowerCase();
  var cat=document.getElementById('catFilter').value;
  var status=document.getElementById('statusFilter').value;
  return allProducts.filter(p=>{{
    var matchQ=!q||p.name.toLowerCase().includes(q)||(p.description||'').toLowerCase().includes(q);
    var matchCat=!cat||p.category===cat;
    var matchStatus=!status||
      (status==='active'&&p.active)||
      (status==='inactive'&&!p.active)||
      (status==='low'&&p.stock>0&&p.stock<=3)||
      (status==='out'&&p.stock<=0);
    return matchQ&&matchCat&&matchStatus;
  }});
}}

// ── MODAL ──────────────────────────────────────────
function openModal(id){{
  editingId=id||null;
  selectedFile=null;
  document.getElementById('modalTitle').textContent=id?'Edit Product':'Add Product';
  document.getElementById('saveBtn').textContent=id?'Save Changes':'Add Product';

  // Reset form
  ['f-name','f-desc'].forEach(i=>document.getElementById(i).value='');
  ['f-price','f-stock'].forEach(i=>document.getElementById(i).value='');
  document.getElementById('f-active').checked=true;
  document.getElementById('f-category').value='';
  document.getElementById('imgPreview').style.display='none';
  document.getElementById('imgZoneContent').style.display='block';
  document.getElementById('existingImageUrl').value='';

  if(id){{
    var p=allProducts.find(x=>x.id===id);
    if(p){{
      document.getElementById('f-name').value=p.name||'';
      document.getElementById('f-price').value=p.price||'';
      document.getElementById('f-stock').value=p.stock||0;
      document.getElementById('f-desc').value=p.description||'';
      document.getElementById('f-active').checked=p.active!==false;
      document.getElementById('f-category').value=p.category||'';
      if(p.image_url){{
        var prev=document.getElementById('imgPreview');
        prev.src=p.image_url;prev.style.display='block';
        document.getElementById('imgZoneContent').style.display='none';
        document.getElementById('existingImageUrl').value=p.image_url;
      }}
    }}
  }}
  document.getElementById('modalOverlay').classList.add('on');
  setTimeout(()=>document.getElementById('f-name').focus(),300);
}}

function closeModal(){{document.getElementById('modalOverlay').classList.remove('on');}}
function closeModalOutside(e){{if(e.target===document.getElementById('modalOverlay'))closeModal();}}

// ── IMAGE HANDLING ─────────────────────────────────
function onDrag(e,entering){{
  e.preventDefault();
  document.getElementById('imgZone').classList[entering?'add':'remove']('drag');
}}
function onDrop(e){{
  e.preventDefault();
  document.getElementById('imgZone').classList.remove('drag');
  var f=e.dataTransfer.files[0];
  if(f&&f.type.startsWith('image/'))setFile(f);
}}
function onFileSelect(e){{
  var f=e.target.files[0];
  if(f)setFile(f);
}}
function setFile(f){{
  if(f.size>5*1024*1024){{toast('Image must be under 5MB','err');return;}}
  selectedFile=f;
  var reader=new FileReader();
  reader.onload=e=>{{
    var prev=document.getElementById('imgPreview');
    prev.src=e.target.result;prev.style.display='block';
    document.getElementById('imgZoneContent').style.display='none';
  }};
  reader.readAsDataURL(f);
}}

// ── SAVE ───────────────────────────────────────────
async function saveProduct(){{
  var name=document.getElementById('f-name').value.trim();
  var price=parseFloat(document.getElementById('f-price').value);
  var stock=parseInt(document.getElementById('f-stock').value)||0;

  if(!name){{toast('Product name is required','err');return;}}
  if(isNaN(price)||price<0){{toast('Enter a valid price','err');return;}}

  var btn=document.getElementById('saveBtn');
  btn.textContent='Saving...';btn.disabled=true;

  try{{
    // Upload image if new file selected
    var imageUrl=document.getElementById('existingImageUrl').value||'';
    if(selectedFile){{
      var uploaded=await uploadImage(selectedFile);
      if(uploaded)imageUrl=uploaded;
      else{{toast('Image upload failed — saving without image','err');}}
    }}

    var body={{
      name,price,stock,
      description:document.getElementById('f-desc').value.trim(),
      category:document.getElementById('f-category').value,
      active:document.getElementById('f-active').checked,
      image_url:imageUrl
    }};

    var url=editingId
      ?`${{API_BASE}}/products/${{editingId}}?secret=${{SECRET}}`
      :`${{API_BASE}}/products?secret=${{SECRET}}`;
    var method=editingId?'PUT':'POST';

    var r=await fetch(url,{{method,headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}});
    var d=await r.json();

    if(r.ok){{
      toast(editingId?'Product updated! ✅':'Product added! ✅');
      closeModal();
      loadProducts();
    }}else{{
      toast(d.error||'Save failed','err');
    }}
  }}catch(e){{
    toast('Something went wrong','err');
  }}finally{{
    btn.textContent=editingId?'Save Changes':'Add Product';
    btn.disabled=false;
  }}
}}

async function uploadImage(file){{
  var form=new FormData();
  form.append('image',file);
  form.append('slug',SLUG);
  var r=await fetch(`/api/${{SLUG}}/upload-image?secret=${{SECRET}}`,{{method:'POST',body:form}});
  var d=await r.json();
  return d.url||null;
}}

// ── DELETE ─────────────────────────────────────────
async function deleteProduct(id,name){{
  if(!confirm(`Delete "${{name}}"? This cannot be undone.`))return;
  try{{
    var r=await fetch(`${{API_BASE}}/products/${{id}}?secret=${{SECRET}}`,{{method:'DELETE'}});
    var d=await r.json();
    if(d.success){{toast('Product deleted','err');loadProducts();}}
    else toast('Delete failed','err');
  }}catch(e){{toast('Error deleting product','err');}}
}}

// ── TOAST ──────────────────────────────────────────
function toast(msg,type){{
  var el=document.getElementById('toast');
  el.textContent=msg;
  el.className='on'+(type==='err'?' err':'');
  clearTimeout(tt);
  tt=setTimeout(()=>el.className='',2800);
}}
</script>
</body></html>"""


# ─────────────────────────────────────────────────────
# IMAGE UPLOAD API ENDPOINT
# ─────────────────────────────────────────────────────

@dashboard.route("/api/<slug>/upload-image", methods=["POST"])
def upload_image(slug: str):
    if not _auth(request):
        return jsonify({"error": "Unauthorized"}), 403

    client = db_layer.get_client_by_slug(slug)
    if not client:
        return jsonify({"error": "Client not found"}), 404

    if "image" not in request.files:
        return jsonify({"error": "No image file provided"}), 400

    file     = request.files["image"]
    filename = file.filename or "upload.jpg"

    # Validate
    allowed_mimes = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    if file.mimetype not in allowed_mimes:
        return jsonify({"error": "Invalid file type. Use JPG, PNG, or WebP."}), 400

    file_bytes = file.read()
    if len(file_bytes) > 5 * 1024 * 1024:
        return jsonify({"error": "File too large. Max 5MB."}), 400

    url = store.upload_product_image(file_bytes, filename, slug)
    if not url:
        return jsonify({"error": "Upload failed"}), 500

    return jsonify({"url": url})


# ─────────────────────────────────────────────────────
# SETTINGS PAGE
# ─────────────────────────────────────────────────────

@dashboard.route("/dashboard/<slug>/settings")
def settings_page(slug: str):
    if not _auth(request):
        return _unauth()

    client = db_layer.get_client_by_slug(slug)
    if not client:
        return "Store not found.", 404

    secret   = ADMIN_SECRET
    app_url  = CATALOG_BASE.rsplit("/shop", 1)[0]
    biz_name = client.get("business_name", slug)
    t_cfg    = get_template(client.get("template", "general"))
    currencies = ["NGN", "GHS", "KES", "ZAR", "USD", "GBP", "EUR", "BRL", "INR", "IDR"]
    curr_opts  = "".join(
        f'<option value="{c}" {"selected" if c == client.get("currency","NGN") else ""}>{c}</option>'
        for c in currencies
    )
    templates_opts = "".join(
        f'<option value="{k}" {"selected" if k == client.get("template","general") else ""}>{v["name"]} {v["emoji"]}</option>'
        for k, v in get_template.__module__ and __import__("templates_config").TEMPLATES.items()
    )

    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Settings — {biz_name}</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
:root{{--bg:#07070e;--s:#10101a;--b:#1c1c2a;--g:#25D366;--text:#dde;--m:#666;--red:#ef4444}}
body{{font-family:'DM Sans',sans-serif;background:var(--bg);color:var(--text);min-height:100vh}}
header{{background:var(--s);border-bottom:1px solid var(--b);padding:14px 24px;display:flex;align-items:center;gap:12px;position:sticky;top:0}}
header h1{{font-size:15px;font-weight:700}}
.back{{color:var(--m);text-decoration:none;font-size:13px}}.back:hover{{color:var(--text)}}
.wrap{{max-width:600px;margin:0 auto;padding:28px 20px 60px}}
.card{{background:var(--s);border:1px solid var(--b);border-radius:16px;padding:24px;margin-bottom:20px}}
.card h2{{font-size:14px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:var(--m);margin-bottom:18px}}
.field{{margin-bottom:14px}}
label{{display:block;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:var(--m);margin-bottom:6px}}
.inp{{width:100%;background:#0b0b15;border:1px solid var(--b);border-radius:10px;color:var(--text);padding:11px 13px;font-family:inherit;font-size:13px;outline:none;transition:border-color .2s}}
.inp:focus{{border-color:var(--g)}}
textarea.inp{{resize:vertical;min-height:70px}}
.btn{{background:var(--g);color:#000;border:none;padding:12px 24px;border-radius:10px;font-weight:700;font-size:13px;cursor:pointer;font-family:inherit}}
.btn:hover{{opacity:.85}}
#result{{font-size:12px;color:var(--g);margin-top:10px;min-height:16px}}
</style></head><body>
<header>
  <a href="/dashboard/{slug}?secret={secret}" class="back">← Products</a>
  <h1>Settings — {biz_name}</h1>
</header>
<div class="wrap">
  <div class="card">
    <h2>🏪 Store Details</h2>
    <div class="field"><label>Business Name</label>
      <input class="inp" id="s-name" value="{client.get('business_name','')}">
    </div>
    <div class="field"><label>Template</label>
      <select class="inp" id="s-template">{templates_opts}</select>
    </div>
    <div class="field"><label>Currency</label>
      <select class="inp" id="s-currency">{curr_opts}</select>
    </div>
    <div class="field"><label>Greeting Message</label>
      <textarea class="inp" id="s-greeting">{client.get('greeting','')}</textarea>
    </div>
    <div class="field"><label>AI Model <span style="font-weight:400;text-transform:none">(Haiku = fast &amp; affordable · Sonnet = premium)</span></label>
      <select class="inp" id="s-model">
        <option value="claude-haiku-4-5" {"selected" if client.get('ai_model','claude-haiku-4-5')=='claude-haiku-4-5' else ''}>Claude Haiku — Default (fast, affordable)</option>
        <option value="claude-sonnet-4-6" {"selected" if client.get('ai_model')=='claude-sonnet-4-6' else ''}>Claude Sonnet — Premium (smarter, higher cost)</option>
      </select>
    </div>
    <button class="btn" onclick="save()">Save Changes</button>
    <div id="result"></div>
  </div>

  <div class="card">
    <h2>📲 WhatsApp Connection</h2>
    <div class="field"><label>Phone Number ID (Meta)</label>
      <input class="inp" id="s-phone-id" value="{client.get('phone_number_id','')}">
    </div>
    <div class="field"><label>Access Token</label>
      <input class="inp" id="s-token" type="password" placeholder="EAAxxxxxxxx..." value="{client.get('wa_token','')}">
    </div>
    <div class="field"><label>WhatsApp Number (with country code)</label>
      <input class="inp" id="s-wa-number" value="{client.get('whatsapp_number','')}">
    </div>
    <div class="field"><label>Your (Merchant) WhatsApp Number <span style="font-weight:400;text-transform:none">(receives order notifications)</span></label>
      <input class="inp" id="s-merchant-phone" value="{client.get('merchant_phone','')}">
    </div>
    <button class="btn" onclick="saveWA()">Save WhatsApp Settings</button>
    <div id="wa-result" style="font-size:12px;color:var(--g);margin-top:10px"></div>
  </div>
</div>
<script>
async function save(){{
  var r=await fetch('/api/{slug}?secret={secret}',{{
    method:'PUT',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{
      business_name:document.getElementById('s-name').value,
      template:document.getElementById('s-template').value,
      currency:document.getElementById('s-currency').value,
      greeting:document.getElementById('s-greeting').value,
      ai_model:document.getElementById('s-model').value,
      secret:'{secret}'
    }})
  }});
  document.getElementById('result').textContent=(await r.json()).success?'Saved ✅':'Failed ❌';
}}
async function saveWA(){{
  var r=await fetch('/api/{slug}?secret={secret}',{{
    method:'PUT',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{
      phone_number_id:document.getElementById('s-phone-id').value,
      wa_token:document.getElementById('s-token').value,
      whatsapp_number:document.getElementById('s-wa-number').value,
      merchant_phone:document.getElementById('s-merchant-phone').value,
      secret:'{secret}'
    }})
  }});
  document.getElementById('wa-result').textContent=(await r.json()).success?'Saved ✅':'Failed ❌';
}}
</script>
</body></html>"""


def _unauth():
    return """<!DOCTYPE html><html><head><style>
body{{background:#07070e;color:#dde;font-family:sans-serif;display:flex;align-items:center;
justify-content:center;height:100vh;flex-direction:column;gap:12px}}
</style></head><body>
<div style="font-size:40px">🔒</div>
<h2>Access Denied</h2>
<p style="color:#666">Add ?secret=YOUR_ADMIN_SECRET to the URL</p>
</body></html>""", 403


# ─────────────────────────────────────────────────────
# CLIENT SETTINGS API (used by settings page)
# ─────────────────────────────────────────────────────

@dashboard.route("/api/<slug>", methods=["PUT"])
def api_update_client_settings(slug: str):
    if not _auth(request):
        return jsonify({"error": "Unauthorized"}), 403
    client = db_layer.get_client_by_slug(slug)
    if not client:
        return jsonify({"error": "Client not found"}), 404

    body    = request.json or {}
    allowed = {"business_name", "greeting", "template", "currency",
               "phone_number_id", "wa_token", "whatsapp_number", "merchant_phone", "ai_model", "active"}
    updates = {k: v for k, v in body.items() if k in allowed}
    ok      = db_layer.update_client(str(client["id"]), updates)
    return jsonify({"success": ok})
