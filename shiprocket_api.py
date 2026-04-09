import os, re, time, requests
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

        wb = session.get(f"{SR_BASE}/account/details/wallet-balance", timeout=20).json()
        balance = (wb.get("data", {}).get("balance") or wb.get("balance") or 0)

        raw_sample = all_orders[0] if all_orders else {}

        awb_charges = {}
        for o in all_orders:
            awb = str(o.get("awb_code") or o.get("awb") or "").strip()
            if not awb:
                continue
            freight   = float(o.get("freight_charges") or o.get("freight_total") or
                              o.get("shipping_charges") or o.get("charge") or 0)
            cod       = float(o.get("cod_charges") or o.get("cod_charge") or
                              o.get("cod_handling_charges") or 0)
            rto       = float(o.get("rto_charges") or o.get("rto_charge") or
                              o.get("rto_freight") or 0)
            excess_wt = float(o.get("weight_charges") or o.get("excess_weight_charges") or
                              o.get("weight_discrepancy") or 0)
            total     = float(o.get("total") or o.get("total_charges") or
                              o.get("amount_charged") or 0)
            if total > 0 and freight == 0 and cod == 0 and rto == 0:
                freight = total
            awb_charges[awb] = {
                "name":          o.get("customer_name", ""),
                "status":        o.get("status", ""),
                "courier":       o.get("courier_name", ""),
                "freight":       round(freight, 2),
                "cod":           round(cod, 2),
                "rto":           round(rto, 2),
                "excess_weight": round(excess_wt, 2),
                "total":         round(freight + cod + rto + excess_wt, 2),
            }

        summary = {
            "freight":       round(sum(v["freight"] for v in awb_charges.values()), 2),
            "cod":           round(sum(v["cod"] for v in awb_charges.values()), 2),
            "rto":           round(sum(v["rto"] for v in awb_charges.values()), 2),
            "excess_weight": round(sum(v["excess_weight"] for v in awb_charges.values()), 2),
            "grand_total":   round(sum(v["total"] for v in awb_charges.values()), 2),
        }

        return jsonify({
            "wallet_balance":  balance,
            "orders_fetched":  len(all_orders),
            "awbs_found":      len(awb_charges),
            "summary":         summary,
            "raw_sample_keys": list(raw_sample.keys()) if raw_sample else [],
            "charges":         awb_charges
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
