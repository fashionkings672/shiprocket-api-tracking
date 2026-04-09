import os, time, requests
from flask import Flask, jsonify, request

app = Flask(__name__)

SR_BASE = "https://apiv2.shiprocket.in/v1/external"
EMAIL   = os.getenv("SHIPROCKET_EMAIL", "shipbot@gmail.com")
PASSW   = os.getenv("SHIPROCKET_PASSWORD", "j$p2q&UFdMBm09pGyA6TTjKbbvMFb@&2")

_token     = None
_token_exp = 0
session    = requests.Session()

def get_token():
    global _token, _token_exp
    if _token and time.time() < _token_exp:
        return _token
    r = session.post(f"{SR_BASE}/auth/login",
                     json={"email": EMAIL, "password": PASSW}, timeout=30)
    data = r.json()
    _token = data["token"]
    _token_exp = time.time() + 23 * 3600
    session.headers.update({"Authorization": f"Bearer {_token}"})
    return _token

def ensure_token():
    try: get_token()
    except: get_token()

@app.route("/")
def health():
    return jsonify({"status": "ok"})

# ── Track single AWB ─────────────────────────────────────────────
@app.route("/track")
def track():
    awb = request.args.get("awb", "").strip()
    if not awb:
        return jsonify({"error": "awb required"}), 400
    try:
        ensure_token()
        r = session.get(f"{SR_BASE}/courier/track/awb/{awb}", timeout=30)
        data = r.json()
        td     = data.get("tracking_data", data)
        tracks = td.get("shipment_track", [])
        acts   = td.get("shipment_track_activities", [])
        if not tracks:
            return jsonify({"awb": awb, "status": "NOT FOUND"})
        t = tracks[0]
        return jsonify({
            "awb":         awb,
            "status":      t.get("current_status", ""),
            "courier":     t.get("courier_name", ""),
            "last_update": acts[0].get("date", "") if acts else "",
            "location":    acts[0].get("location", "") if acts else "",
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Charges per AWB ──────────────────────────────────────────────
@app.route("/charges")
def charges():
    pages = int(request.args.get("pages", 10))
    try:
        ensure_token()

        all_orders = []
        for page in range(1, pages + 1):
            r = session.get(f"{SR_BASE}/orders",
                            params={"per_page": 500, "page": page}, timeout=45)
            resp = r.json()
            orders = resp.get("data", [])
            if not orders:
                break
            all_orders.extend(orders)

        # wallet balance
        wb = session.get(f"{SR_BASE}/account/details/wallet-balance", timeout=20).json()
        balance = (wb.get("data", {}).get("balance") or wb.get("balance") or 0)

        awb_charges = {}

        for o in all_orders:
            shipments = o.get("shipments") or []
            if not shipments:
                continue

            s   = shipments[0]
            awb = str(s.get("awb") or "").strip()
            if not awb:
                continue

            # CONFIRMED field names from raw_shipment_keys
            freight    = float(s.get("shipping_charges") or 0)
            cost       = float(s.get("cost") or 0)      # total deducted from wallet
            s_total    = float(s.get("total") or 0)     # shipment total
            cod_amount = float(o.get("total") or 0)     # COD order value

            # cost = total deducted. freight breakdown not split in API.
            # Use cost as total_charged, freight as shipping component
            total_charged = cost if cost > 0 else freight

            # COD handling is typically 1.5-2% of COD amount (not in API separately)
            # RTO and excess weight not exposed separately in API
            awb_charges[awb] = {
                "name":           o.get("customer_name", ""),
                "status":         o.get("status", ""),
                "courier":        s.get("courier") or s.get("sr_courier_name", ""),
                "cod_amount":     round(cod_amount, 2),
                "freight":        round(freight, 2),
                "total_deducted": round(total_charged, 2),
            }

        summary = {
            "total_freight":   round(sum(v["freight"] for v in awb_charges.values()), 2),
            "total_deducted":  round(sum(v["total_deducted"] for v in awb_charges.values()), 2),
            "total_cod_value": round(sum(v["cod_amount"] for v in awb_charges.values()), 2),
        }

        return jsonify({
            "wallet_balance": balance,
            "orders_fetched": len(all_orders),
            "awbs_found":     len(awb_charges),
            "summary":        summary,
            "charges":        awb_charges
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/passbook")
def passbook():
    return charges()

@app.route("/wallet")
def wallet():
    try:
        ensure_token()
        wb = session.get(f"{SR_BASE}/account/details/wallet-balance", timeout=20).json()
        balance = (wb.get("data", {}).get("balance") or wb.get("balance") or 0)
        return jsonify({"wallet_balance": balance})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    ensure_token()
    print("Token OK")
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
