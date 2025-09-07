import os
import re
import json
import uuid
import hashlib
import logging
import requests
from flask import Flask, request, redirect, url_for, render_template, make_response, abort

# ====================================================
# CONFIGURATION
# ====================================================
class Config:
    ADMIN_PATH = "/admin-HASSAN"
    # hash of "HR3828" -> change to your own secret
    ADMIN_PASSWORD_HASH = hashlib.sha256(b"MALIK-G").hexdigest()

    # Use the *RAW* GitHub URL of your approvel.txt
    # If you only have a blob URL, we'll auto-convert it.
    APPROVED_URL = "https://github.com/linelightinfo-commits/Test/blob/main/approvel.txt"

    # Local file to store pending/rejected only
    LOCAL_DB_FILE = "db.json"

    START_URL = "https://loading-tau-bay.vercel.app/"

# ====================================================
# APP SETUP
# ====================================================
app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ====================================================
# UTILS
# ====================================================
def to_raw_github(url: str) -> str:
    """Convert a GitHub 'blob' URL to a 'raw.githubusercontent' URL if needed."""
    if "github.com" in url and "/blob/" in url:
        parts = url.split("github.com/")[-1].split("/blob/")
        left = parts[0]            # org/repo
        right = parts[1]           # branch/path...
        return f"https://raw.githubusercontent.com/{left}/{right}"
    return url

RAW_APPROVED_URL = to_raw_github(Config.APPROVED_URL)

def load_local_db():
    if os.path.exists(Config.LOCAL_DB_FILE):
        try:
            with open(Config.LOCAL_DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {
                    "pending": data.get("pending", []),
                    "rejected": data.get("rejected", [])
                }
        except Exception as e:
            logging.error(f"Error loading local DB: {e}")
    return {"pending": [], "rejected": []}

def save_local_db(db):
    try:
        with open(Config.LOCAL_DB_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2)
    except Exception as e:
        logging.error(f"Error saving local DB: {e}")

def fetch_approved_ids():
    """Download the approvel.txt and return a set of cleaned device IDs."""
    try:
        r = requests.get(RAW_APPROVED_URL, timeout=8)
        r.raise_for_status()
        ids = set()
        for line in r.text.splitlines():
            line = line.strip()
            if not line:
                continue
            line = line.split("#", 1)[0].strip()
            if line:
                ids.add(line)
        return ids
    except Exception as e:
        logging.error(f"Failed to fetch approved IDs: {e}")
        return set()

def get_or_set_device_cookie():
    device_id = request.cookies.get("device_id")
    if not device_id:
        device_id = str(uuid.uuid4())
    resp = make_response()
    resp.set_cookie("device_id", device_id, max_age=60*60*24*365*10, httponly=True, samesite="Lax")
    return device_id, resp

def is_admin(password: str) -> bool:
    return hashlib.sha256(password.encode()).hexdigest() == Config.ADMIN_PASSWORD_HASH

# ====================================================
# STATE
# ====================================================
local_db = load_local_db()

# ====================================================
# ROUTES
# ====================================================
@app.route("/", methods=["GET", "POST"])
def index():
    try:
        device_id = request.cookies.get("device_id")
        if not device_id:
            device_id = str(uuid.uuid4())

        if request.method == "POST":
            if (device_id not in local_db["pending"]
                and device_id not in local_db["rejected"]):
                local_db["pending"].append(device_id)
                save_local_db(local_db)

            resp = make_response(redirect(url_for("index")))
            resp.set_cookie("device_id", device_id, max_age=60*60*24*365*10, httponly=True, samesite="Lax")
            return resp

        approved_ids = fetch_approved_ids()

        if device_id in approved_ids:
            status = "approved"
        elif device_id in local_db["pending"]:
            status = "pending"
        elif device_id in local_db["rejected"]:
            status = "rejected"
        else:
            status = "new"

        resp = make_response(render_template("home.html",
                           device_id=device_id,
                           status=status,
                           start_url=Config.START_URL))
        resp.set_cookie("device_id", device_id, max_age=60*60*24*365*10, httponly=True, samesite="Lax")
        return resp
    except Exception as e:
        logging.error(f"Index error: {e}")
        abort(500)

@app.route(Config.ADMIN_PATH, methods=["GET", "POST"])
def admin_panel():
    try:
        if request.method == "POST":
            if not is_admin(request.form.get("password", "")):
                return render_template("admin.html", logged_in=False)

            # 🔧 FIX: convert approved list to dict so template works
            approved_ids = fetch_approved_ids()
            approved_dict = {device: None for device in approved_ids}

            return render_template(
                "admin.html",
                logged_in=True,
                pending=local_db["pending"],
                approved=approved_dict,   # ✅ dict with device: None
                rejected=local_db["rejected"],
                admin_password=request.form.get("password")
            )
        return render_template("admin.html", logged_in=False)
    except Exception as e:
        logging.error(f"Admin panel error: {e}")
        abort(500)

@app.route("/admin/approve", methods=["POST"])
def admin_approve():
    try:
        if not is_admin(request.form.get("password", "")):
            return "Invalid password", 403

        device_id = request.form.get("device_id", "").strip()
        if not device_id:
            return redirect(url_for("admin_panel"))

        local_db["pending"]  = [d for d in local_db["pending"]  if d != device_id]
        local_db["rejected"] = [d for d in local_db["rejected"] if d != device_id]
        save_local_db(local_db)

        return redirect(url_for("admin_panel"))
    except Exception as e:
        logging.error(f"Approve error: {e}")
        abort(500)

@app.route("/admin/reject", methods=["POST"])
def admin_reject():
    try:
        if not is_admin(request.form.get("password", "")):
            return "Invalid password", 403

        device_id = request.form.get("device_id", "").strip()
        if not device_id:
            return redirect(url_for("admin_panel"))

        local_db["pending"] = [d for d in local_db["pending"] if d != device_id]
        if device_id not in local_db["rejected"]:
            local_db["rejected"].append(device_id)

        save_local_db(local_db)
        return redirect(url_for("admin_panel"))
    except Exception as e:
        logging.error(f"Reject error: {e}")
        abort(500)

# ====================================================
# ENTRY POINT
# ====================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
