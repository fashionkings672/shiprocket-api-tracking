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

@app.route("/passbook")
def passbook():
    pages = int(request.args.get("pages", 5))
    try:
        ensure_token()
        all_entries = []
        for page in range(1, pages + 1):
            r = session.get(f"{SR_BASE}/account/details/passbook",
                            params={"per_page": 500, "page": page}, timeout=45)
            entries = r.json().get("data", [])
            if not entries:
                break
            all_entries.extend(entries)

        wb      = session.get(f"{SR_BASE}/account/details/wallet-balance", timeout=20).json()
        balance = wb.get("data", {}).get("balance") or wb.get("balance", 0)

        awb_charges = {}
        for e in all_entries:
            note = (e.get("note") or e.get("description") or e.get("remarks") or "").lower()
            amt  = abs(float(e.get("debit") or e.get("credit") or e.get("amount") or 0))
            awb  = str(e.get("awb") or e.get("awb_code") or "").strip()
            if not awb:
                m = re.search(r'\b(\d{10,16})\b', note)
                if m: awb = m.group(1)
            if not awb or amt == 0:
                continue
            if awb not in awb_charges:
                awb_charges[awb] = {"freight": 0, "cod": 0, "rto": 0, "excess_weight": 0, "other": 0, "total": 0}
            if "freight" in note or "forward" in note:
                awb_charges[awb]["freight"] += amt
            elif "cod" in note:
                awb_charges[awb]["cod"] += amt
            elif "rto" in note:
                awb_charges[awb]["rto"] += amt
            elif "weight" in note or "excess" in note:
                awb_charges[awb]["excess_weight"] += amt
            else:
                awb_charges[awb]["other"] += amt
            awb_charges[awb]["total"] = round(sum(
                v for k, v in awb_charges[awb].items() if k != "total"), 2)

        return jsonify({
            "wallet_balance":      balance,
            "transactions_fetched": len(all_entries),
            "awbs_with_charges":   len(awb_charges),
            "charges":             awb_charges
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    ensure_token()
    print("Token OK")
    app.run(host="0.0.0.0", port=8080)
