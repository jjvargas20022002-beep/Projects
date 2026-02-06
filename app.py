from flask import Flask, render_template, request, redirect, url_for, session
import gspread
from google.oauth2.service_account import Credentials
from werkzeug.security import check_password_hash
from functools import wraps
import os

# =====================
# APP CONFIG
# =====================
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "super-secret-key")

# =====================
# AUTH USERS
# =====================
def load_users():
    users = {}
    raw = os.environ.get("AUTH_USERS", "")
    for pair in raw.split(","):
        if "=" in pair:
            u, h = pair.split("=", 1)
            users[u.strip()] = h.strip()
    return users

USERS = load_users()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

# =====================
# GOOGLE SHEETS CONFIG
# =====================
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

def get_sheet():
    creds = Credentials.from_service_account_info(
        {
            "type": "service_account",
            "project_id": os.environ["GCP_PROJECT_ID"],
            "private_key_id": os.environ["GCP_PRIVATE_KEY_ID"],
            "private_key": os.environ["GCP_PRIVATE_KEY"].replace("\\n", "\n"),
            "client_email": os.environ["GCP_CLIENT_EMAIL"],
            "client_id": os.environ["GCP_CLIENT_ID"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": os.environ["GCP_CLIENT_CERT_URL"],
        },
        scopes=SCOPES,
    )
    gc = gspread.authorize(creds)
    return gc.open_by_key(os.environ["SPREADSHEET_ID"])

# =====================
# CONFIG
# =====================
BRANCH_TABS = [
    "GARANTIAS LIMA",
    "GARANTIAS PROVINCIA",
    "FUERA DE GARANTÍA PROVINCIA",
    "CANCELADOS",
    "PENDIENTES ODN",
]

SINGLE_BRANCH_TAB = "ONLINE LIMA"

STATUS_FROM_ODN_TABS = [
    "GARANTIAS LIMA",
    "LI1 TGI",
    "LI2 DIJUSA",
    "LI2 ERAM",
    "LI3 INTER",
    "LI4 TGI",
    "LI4 BROKERS",
    "LI7 MARCOS",
]

# =====================
# UTILS
# =====================
def coord_to_link(value):
    try:
        lat, lng = map(float, value.replace(" ", "").split(",", 1))
        return f"https://www.google.com/maps?q={lat},{lng}"
    except:
        return None

def normalize(text):
    return text.upper().replace(" ", "").replace("_", "").replace("DE", "")

def find_col(headers, expected_name):
    expected = normalize(expected_name)
    for i, h in enumerate(headers):
        if expected == normalize(h) or expected in normalize(h):
            return i
    return None

def find_col_exact(headers, expected_name):
    for i, h in enumerate(headers):
        if h.strip().upper() == expected_name.upper():
            return i
    return None

# =====================
# ESTADO DESDE PENDIENTES ODN
# =====================
def get_box_status():
    status_map = {}
    try:
        sheet = get_sheet()
        ws = sheet.worksheet("PENDIENTES ODN")
        data = ws.get_all_values()

        headers = data[0]
        rows = data[1:]

        caja_idx = find_col_exact(headers, "CAJA")
        status_idx = find_col(headers, "STATUS DE LA CAJA")

        for r in rows:
            if caja_idx is not None and status_idx is not None:
                if len(r) > max(caja_idx, status_idx):
                    estado = r[status_idx].strip().lower()
                    if estado in ["reparado", "en plan"]:
                        status_map[r[caja_idx].strip()] = estado.title()
    except:
        pass

    return status_map

# =====================
# LOGIN
# =====================
@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        user = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if user in USERS and check_password_hash(USERS[user], password):
            session["user"] = user
            return redirect(url_for("index"))
        else:
            error = "Usuario o contraseña incorrectos"

    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# =====================
# MAIN ROUTE
# =====================
@app.route("/")
@login_required
def index():
    sheet = get_sheet()
    tabs = [ws.title for ws in sheet.worksheets()]

    selected_tab = request.args.get("tab", tabs[0])
    last_tab = request.args.get("last_tab", "")
    selected_filter1 = request.args.get("filter1", "")
    selected_filter2 = request.args.get("filter2", "")

    if last_tab != selected_tab:
        selected_filter1 = ""
        selected_filter2 = ""

    ws = sheet.worksheet(selected_tab)
    data = ws.get_all_values()

    headers = data[0]
    rows_all = data[1:]
    total_rows = len(rows_all)

    coord_idx = find_col(headers, "COORDENADAS")
    caja_idx = find_col_exact(headers, "CAJA")
    cuenta_idx = find_col(headers, "CUENTA")
    status_idx = find_col(headers, "STATUS DE LA CAJA")

    filtered_rows = rows_all

    if selected_filter1:
        filtered_rows = [r for r in filtered_rows if selected_filter1 in r]

    if selected_filter2:
        filtered_rows = [r for r in filtered_rows if selected_filter2 in r]

    # =====================
    # MAP DATA (CRITICAL FIX)
    # =====================
    coords_info = []

    for r in filtered_rows:
        if coord_idx is not None and len(r) > coord_idx:
            link = coord_to_link(r[coord_idx])
            if link:
                coords_info.append({
                    "coord": r[coord_idx],
                    "link": link,
                    "caja": r[caja_idx] if caja_idx is not None and len(r) > caja_idx else "",
                    "cuenta": r[cuenta_idx] if cuenta_idx is not None and len(r) > cuenta_idx else "",
                    "status": r[status_idx] if status_idx is not None and len(r) > status_idx else "",
                })

    # 🔴 NUNCA permitir None
    if coords_info is None:
        coords_info = []

    return render_template(
        "index.html",
        tabs=tabs,
        selected_tab=selected_tab,
        last_tab=selected_tab,
        headers=headers,
        rows=filtered_rows,
        total_rows=total_rows,
        filter1=selected_filter1,
        filter2=selected_filter2,
        coords_info=coords_info,
        user=session.get("user"),
    )

# =====================
# RUN LOCAL
# =====================
if __name__ == "__main__":
    app.run(debug=True)
