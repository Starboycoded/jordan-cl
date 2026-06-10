# ══════════════════════════════════════════════════════
# JORDAN v5.3 — CODEDLABS ADMIN PANEL
# Platform owner controls:
#   - View all clients
#   - Assign / change plans
#   - Override feature flags
#   - Set usage limits
#   - Suspend / reactivate clients
#   - View platform-wide stats
# Route: /codedlabs?secret=ADMIN_SECRET
# ══════════════════════════════════════════════════════

import os
import json
import logging
from flask import Blueprint, request, jsonify
import database as db_layer
from subscriptions import PLANS, can

logger      = logging.getLogger(__name__)
admin_panel = Blueprint("admin_panel", __name__)
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "CodedLabs2025")


def _auth(req) -> bool:
    from flask import session as flask_session
    if flask_session.get("logged_in") and flask_session.get("is_admin"):
        return True
    return (req.args.get("secret") == ADMIN_SECRET or
            req.headers.get("X-Admin-Secret") == ADMIN_SECRET)


# ─────────────────────────────────────────────────────
# PLATFORM DASHBOARD  (HTML)
# ─────────────────────────────────────────────────────

@admin_panel.route("/codedlabs")
def platform_dashboard():
    from flask import session as flask_session
    if not _auth(request) and not (flask_session.get("logged_in") and flask_session.get("is_admin")):
        from flask import redirect
        return redirect("/login")

    clients  = db_layer.get_all_clients()
    secret   = ADMIN_SECRET
    plan_opts = "".join(
        f'<option value="{k}">{v["name"]} — NGN {v["price_ngn"]:,}/mo</option>'
        for k, v in PLANS.items() if k != "internal"
    )

    rows = ""
    for c in clients:
        plan  = c.get("plan", "starter")
        slug  = c.get("slug", "")
        name  = c.get("business_name", slug)
        tmpl  = c.get("template", "general")
        active = "✅" if c.get("active") else "❌"
        rows += f"""<tr>
          <td><strong>{name}</strong><br><small style="color:#666">{slug}</small></td>
          <td>{tmpl}</td>
          <td><span class="badge p-{plan}">{plan.title()}</span></td>
          <td>{active}</td>
          <td>
            <button class="btn-sm" onclick="editClient('{c['id']}','{slug}','{plan}',{json.dumps(c.get('feature_flags') or {})})">
              Edit
            </button>
            <a href="/admin/{slug}?secret={secret}" target="_blank" class="btn-sm">Dashboard →</a>
          </td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CodedLabs — Jordan Admin</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{--bg:#07070e;--s:#10101a;--b:#1c1c2a;--g:#25D366;--text:#dde;--m:#555;--red:#ef4444;--warn:#f59e0b}}
body{{font-family:'DM Sans',sans-serif;background:var(--bg);color:var(--text);min-height:100vh}}
header{{background:var(--s);border-bottom:1px solid var(--b);padding:15px 28px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:10}}
header h1{{font-size:16px;font-weight:700}}
.tag{{font-size:10px;background:rgba(37,211,102,.15);color:var(--g);padding:3px 10px;border-radius:20px;font-weight:600;margin-left:8px}}
.wrap{{max-width:1200px;margin:0 auto;padding:24px 20px 60px}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:24px}}
.stat{{background:var(--s);border:1px solid var(--b);border-radius:12px;padding:16px}}
.stat-n{{font-size:24px;font-weight:700;margin-bottom:2px}}
.stat-l{{font-size:10px;color:var(--m);text-transform:uppercase;letter-spacing:.7px}}
.card{{background:var(--s);border:1px solid var(--b);border-radius:14px;overflow:hidden;margin-bottom:20px}}
.card-head{{padding:12px 18px;border-bottom:1px solid var(--b);font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:var(--m)}}
.tbl-wrap{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{padding:10px 14px;text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.7px;color:var(--m);font-weight:600;border-bottom:1px solid var(--b)}}
td{{padding:10px 14px;border-top:1px solid var(--b);vertical-align:middle}}
tr:hover td{{background:rgba(255,255,255,.015)}}
.badge{{padding:3px 10px;border-radius:20px;font-size:10px;font-weight:700}}
.p-starter{{background:rgba(255,255,255,.07);color:#aaa}}
.p-growth{{background:rgba(59,130,246,.15);color:#3b82f6}}
.p-premium{{background:rgba(168,85,247,.15);color:#a855f7}}
.p-enterprise{{background:rgba(245,158,11,.15);color:#f59e0b}}
.p-internal{{background:rgba(37,211,102,.15);color:var(--g)}}
.btn-sm{{background:var(--b);border:1px solid #2a2a3a;color:var(--text);padding:5px 12px;border-radius:6px;font-size:11px;cursor:pointer;font-family:inherit;text-decoration:none;display:inline-block;transition:all .15s;margin-right:4px}}
.btn-sm:hover{{border-color:var(--g);color:var(--g)}}
.btn{{background:var(--g);color:#000;border:none;padding:10px 22px;border-radius:8px;font-weight:700;font-size:13px;cursor:pointer;font-family:inherit}}
.btn:hover{{opacity:.85}}
.overlay{{position:fixed;inset:0;background:rgba(0,0,0,.75);opacity:0;pointer-events:none;transition:opacity .3s;z-index:100;display:flex;align-items:center;justify-content:center;padding:16px}}
.overlay.on{{opacity:1;pointer-events:all}}
.modal{{background:var(--s);border:1px solid var(--b);border-radius:18px;width:100%;max-width:480px;padding:24px;transform:translateY(20px);transition:transform .3s}}
.overlay.on .modal{{transform:translateY(0)}}
.field{{margin-bottom:14px}}
label{{display:block;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:var(--m);margin-bottom:6px}}
.inp{{width:100%;background:#0b0b15;border:1px solid var(--b);border-radius:10px;color:var(--text);padding:11px 13px;font-family:inherit;font-size:13px;outline:none;transition:border-color .2s}}
.inp:focus{{border-color:var(--g)}}
textarea.inp{{resize:vertical;min-height:80px;font-size:12px}}
.modal-head{{display:flex;align-items:center;justify-content:space-between;margin-bottom:18px}}
.modal-title{{font-size:16px;font-weight:700}}
.modal-close{{background:none;border:none;color:var(--m);font-size:20px;cursor:pointer}}
.modal-footer{{display:flex;gap:10px;margin-top:20px}}
.modal-footer button{{flex:1}}
.btn-ghost{{background:var(--b);color:var(--text);border:1px solid #2a2a3a}}
#result{{font-size:12px;color:var(--g);margin-top:10px;min-height:16px}}
</style></head><body>
<header>
  <div><h1>⚡ Jordan Platform<span class="tag">CodedLabs Admin</span></h1></div>
  <span style="font-size:12px;color:var(--m)">{len(clients)} clients</span>
</header>
<div class="wrap">
  <div class="stats">
    <div class="stat"><div class="stat-n" style="color:var(--g)">{len(clients)}</div><div class="stat-l">Total Clients</div></div>
    <div class="stat"><div class="stat-n" style="color:#3b82f6">{sum(1 for c in clients if c.get("plan") == "growth")}</div><div class="stat-l">Growth</div></div>
    <div class="stat"><div class="stat-n" style="color:#a855f7">{sum(1 for c in clients if c.get("plan") == "premium")}</div><div class="stat-l">Premium</div></div>
    <div class="stat"><div class="stat-n" style="color:#f59e0b">{sum(1 for c in clients if c.get("plan") == "enterprise")}</div><div class="stat-l">Enterprise</div></div>
    <div class="stat"><div class="stat-n" style="color:var(--m)">{sum(1 for c in clients if not c.get("active"))}</div><div class="stat-l">Suspended</div></div>
  </div>

  <div class="card">
    <div class="card-head">All Clients</div>
    <div class="tbl-wrap">
      <table>
        <thead><tr><th>Business</th><th>Template</th><th>Plan</th><th>Active</th><th>Actions</th></tr></thead>
        <tbody>{rows if rows else '<tr><td colspan="5" style="text-align:center;color:#555;padding:30px">No clients yet</td></tr>'}</tbody>
      </table>
    </div>
  </div>
</div>

<!-- Edit Client Modal -->
<div class="overlay" id="ov" onclick="closeModal(event)">
<div class="modal">
  <div class="modal-head">
    <span class="modal-title">Edit Client</span>
    <button class="modal-close" onclick="document.getElementById('ov').classList.remove('on')">✕</button>
  </div>
  <input type="hidden" id="edit_id">
  <div class="field">
    <label>Plan</label>
    <select class="inp" id="edit_plan">{plan_opts}
      <option value="internal">Internal (CodedLabs)</option>
    </select>
  </div>
  <div class="field">
    <label>Feature Flag Overrides <span style="font-weight:400;text-transform:none">(JSON — overrides plan defaults)</span></label>
    <textarea class="inp" id="edit_flags" placeholder='{{"broadcast": true, "max_products": 100}}'></textarea>
  </div>
  <div class="field">
    <label>Active</label>
    <select class="inp" id="edit_active">
      <option value="true">Active</option>
      <option value="false">Suspended</option>
    </select>
  </div>
  <div class="modal-footer">
    <button class="btn-ghost btn" onclick="document.getElementById('ov').classList.remove('on')">Cancel</button>
    <button class="btn" onclick="saveClient()">Save Changes</button>
  </div>
  <div id="result"></div>
</div>
</div>

<script>
const SECRET='{secret}';
function editClient(id, slug, plan, flags){{
  document.getElementById('edit_id').value=id;
  document.getElementById('edit_plan').value=plan;
  document.getElementById('edit_flags').value=Object.keys(flags).length?JSON.stringify(flags,null,2):'';
  document.getElementById('ov').classList.add('on');
}}
function closeModal(e){{if(e.target===document.getElementById('ov'))document.getElementById('ov').classList.remove('on');}}
async function saveClient(){{
  const id=document.getElementById('edit_id').value;
  const plan=document.getElementById('edit_plan').value;
  const active=document.getElementById('edit_active').value==='true';
  let flags={{}};
  try{{const raw=document.getElementById('edit_flags').value.trim();if(raw)flags=JSON.parse(raw);}}
  catch(e){{document.getElementById('result').textContent='Invalid JSON in feature flags.';return;}}
  try{{
    const r=await fetch('/api/admin/clients/'+id,{{
      method:'PUT',
      headers:{{'Content-Type':'application/json','X-Admin-Secret':SECRET}},
      body:JSON.stringify({{plan,feature_flags:flags,active}})
    }});
    const d=await r.json();
    document.getElementById('result').textContent=d.success?'Saved ✅':'Failed: '+(d.error||'');
    if(d.success)setTimeout(()=>location.reload(),800);
  }}catch(e){{document.getElementById('result').textContent='Request failed.';}}
}}
</script>
</body></html>"""


# ─────────────────────────────────────────────────────
# ADMIN API  (used by the platform dashboard)
# ─────────────────────────────────────────────────────

@admin_panel.route("/api/admin/clients/<client_id>", methods=["PUT"])
def admin_update_client(client_id: str):
    if not _auth(request):
        return jsonify({"error": "Unauthorized"}), 403

    body    = request.json or {}
    allowed = {"plan", "feature_flags", "active", "plan_expires_at",
                "business_name", "template", "merchant_phone"}
    updates = {k: v for k, v in body.items() if k in allowed}

    if not updates:
        return jsonify({"error": "No valid fields"}), 400

    try:
        db_layer.db().table("clients").update(updates).eq("id", client_id).execute()
        logger.info(f"[Admin] Client {client_id} updated: {list(updates.keys())}")
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"[Admin] update_client: {e}")
        return jsonify({"error": str(e)}), 500


@admin_panel.route("/api/admin/clients", methods=["GET"])
def admin_list_clients():
    if not _auth(request):
        return jsonify({"error": "Unauthorized"}), 403
    clients = db_layer.get_all_clients()
    # Strip sensitive fields before returning
    safe = [{k: v for k, v in c.items() if k not in ("wa_token",)} for c in clients]
    return jsonify({"clients": safe})


@admin_panel.route("/api/admin/stats", methods=["GET"])
def admin_stats():
    if not _auth(request):
        return jsonify({"error": "Unauthorized"}), 403
    try:
        clients   = db_layer.get_all_clients()
        plan_dist = {}
        for c in clients:
            p = c.get("plan", "starter")
            plan_dist[p] = plan_dist.get(p, 0) + 1
        return jsonify({
            "total_clients": len(clients),
            "active":        sum(1 for c in clients if c.get("active")),
            "by_plan":       plan_dist,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
