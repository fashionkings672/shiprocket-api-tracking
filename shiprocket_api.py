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

# ── Charges per AWB from orders ──────────────────────────────────
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
            # AWB is inside shipments array
            shipments = o.get("shipments") or []
            awb = ""
            freight = 0
            cod_charge = 0
            rto = 0
            excess_wt = 0

            if shipments and isinstance(shipments, list):
                s = shipments[0]
                awb = str(s.get("awb") or s.get("awb_code") or "").strip()
                freight   = float(s.get("freight_charges") or s.get("freight") or
                                  s.get("charge") or s.get("shipping_charges") or 0)
                cod_charge= float(s.get("cod_charges") or s.get("cod_charge") or 0)
                rto       = float(s.get("rto_charges") or s.get("rto_charge") or 0)
                excess_wt = float(s.get("weight_charges") or s.get("excess_weight") or 0)

            # fallback: try order-level fields
            if not awb:
                awb = str(o.get("awb_code") or o.get("awb") or
                          o.get("last_mile_awb") or "").strip()

            if not awb:
                continue

            # order-level charge fallbacks
            if freight == 0:
                freight = float(o.get("freight_charges") or o.get("other_charges") or 0)
            if cod_charge == 0:
                cod_val = o.get("cod")
                if isinstance(cod_val, dict):
                    cod_charge = float(cod_val.get("charges") or cod_val.get("amount") or 0)
                elif cod_val:
                    cod_charge = 0  # cod field is order value not charge

            # total from order if still zero
            order_total = float(o.get("total") or 0)

            awb_charges[awb] = {
                "name":          o.get("customer_name", ""),
                "status":        o.get("status", ""),
                "courier":       (shipments[0].get("courier_name","") if shipments else
                                  o.get("last_mile_courier_name", "")),
                "freight":       round(freight, 2),
                "cod_charge":    round(cod_charge, 2),
                "rto":           round(rto, 2),
                "excess_weight": round(excess_wt, 2),
                "order_total":   round(order_total, 2),
                "total_charged": round(freight + cod_charge + rto + excess_wt, 2),
            }

        # expose raw shipment keys from first order for debugging
        raw_shipment_keys = []
        if all_orders and all_orders[0].get("shipments"):
            raw_shipment_keys = list(all_orders[0]["shipments"][0].keys())

        summary = {
            "freight":       round(sum(v["freight"] for v in awb_charges.values()), 2),
            "cod_charge":    round(sum(v["cod_charge"] for v in awb_charges.values()), 2),
            "rto":           round(sum(v["rto"] for v in awb_charges.values()), 2),
            "excess_weight": round(sum(v["excess_weight"] for v in awb_charges.values()), 2),
            "grand_total":   round(sum(v["total_charged"] for v in awb_charges.values()), 2),
        }

        return jsonify({
            "wallet_balance":      balance,
            "orders_fetched":      len(all_orders),
            "awbs_found":          len(awb_charges),
            "summary":             summary,
            "raw_shipment_keys":   raw_shipment_keys,
            "charges":             awb_charges
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
