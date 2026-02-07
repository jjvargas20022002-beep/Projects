from flask import Flask, render_template, request, redirect, url_for, session
import gspread
from google.oauth2.service_account import Credentials
import os

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "secret_key_temporal")

# =====================
# GOOGLE SHEETS CONFIG
# =====================
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

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
sheet = gc.open_by_key(os.environ["SPREADSHEET_ID"])

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
# LOGIN
# =====================
USERS = {
    "vtp76066116": "Fbb@12.2025",
    "vtp62146884": "Fbb@12.2025",
    "vtp72925383": "Fbb@02.2026"
}

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
    return "".join(text.upper().split()) if text else ""

def find_col(headers, expected_name):
    expected = normalize(expected_name)
    for i, h in enumerate(headers):
        if expected in normalize(h):
            return i
    return None

def find_col_exact(headers, expected_name):
    for i, h in enumerate(headers):
        if h.strip().upper() == expected_name.upper():
            return i
    return None

# =====================
# LOGIN ROUTES
# =====================
@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "").strip()
        if username in USERS and USERS[username] == password:
            session["user"] = username
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
def index():
    if "user" not in session:
        return redirect(url_for("login"))

    tabs = [ws.title for ws in sheet.worksheets()]
    selected_tab = request.args.get("tab", tabs[0])
    last_tab = request.args.get("last_tab", "")
    selected_filter1 = request.args.get("filter1", "").strip()
    selected_filter2 = request.args.get("filter2", "").strip()

    # reset filtros al cambiar tab
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
    status_idx = find_col(headers, "STATUS")

    # configurar filtros según tab
    if selected_tab in BRANCH_TABS:
        col1_name, col2_name = "BRANCH", "CONTRATA"
        use_filter2 = True
    elif selected_tab == SINGLE_BRANCH_TAB:
        col1_name, col2_name = "BRANCH", None
        use_filter2 = False
    else:
        col1_name, col2_name = "SITE", "Reporte de Contrata"
        use_filter2 = True

    col1_idx = find_col(headers, col1_name)

    # ⚡ corrección mínima aquí:
    col2_idx = find_col_exact(headers, col2_name) if col2_name else None

    # =====================
    # APLICAR FILTROS
    # =====================
    def matches(cell_value, filter_value):
        return normalize(cell_value) == normalize(filter_value)

    rows_after_f1 = [
        r for r in rows_all
        if len(r) > col1_idx and (not selected_filter1 or matches(r[col1_idx], selected_filter1))
    ]

    filtered_rows = [
        r for r in rows_after_f1
        if not (use_filter2 and col2_idx is not None and selected_filter2) or matches(r[col2_idx], selected_filter2)
    ]

    filtered_count = len(filtered_rows)

    # =====================
    # DROPDOWNS
    # =====================
    filters1 = sorted({r[col1_idx] for r in rows_all if col1_idx is not None and len(r) > col1_idx and r[col1_idx].strip()})
    filters2 = sorted({r[col2_idx] for r in rows_after_f1 if use_filter2 and col2_idx is not None and len(r) > col2_idx and r[col2_idx].strip()})

    # =====================
    # COORDENADAS PARA MAPA
    # =====================
    coords_info = []
    show_map_column = coord_idx is not None and selected_tab not in ["CANCELADOS", SINGLE_BRANCH_TAB]

    if show_map_column:
        for r in filtered_rows:
            try:
                lat, lng = map(float, r[coord_idx].replace(" ", "").split(",", 1))
                coords_info.append({
                    "lat": lat,
                    "lng": lng,
                    "caja": r[caja_idx] if caja_idx is not None else "",
                    "cuenta": r[cuenta_idx] if cuenta_idx is not None else "",
                    "status": r[status_idx] if status_idx is not None else ""
                })
            except:
                pass

    # =====================
    # TABLA
    # =====================
    hidden_idxs = {i for i, h in enumerate(headers) if "LINK" in h.upper()}
    if coord_idx is not None:
        hidden_idxs.add(coord_idx)

    visible_headers = [h for i, h in enumerate(headers) if i not in hidden_idxs]

    rows_with_links = []
    for r in filtered_rows:
        visible_row = [c for i, c in enumerate(r) if i not in hidden_idxs]
        link = coord_to_link(r[coord_idx]) if coord_idx is not None else None
        rows_with_links.append((visible_row, link))

    return render_template(
        "index.html",
        tabs=tabs,
        selected_tab=selected_tab,
        last_tab=selected_tab,
        headers=visible_headers,
        rows_with_links=rows_with_links,
        filters1=filters1,
        filters2=filters2,
        selected_filter1=selected_filter1,
        selected_filter2=selected_filter2,
        total_rows=total_rows,
        filtered_count=filtered_count,
        coords_info=coords_info,
        has_coords=show_map_column,
        is_branch_tab=selected_tab in BRANCH_TABS or selected_tab == SINGLE_BRANCH_TAB,
        show_map_column=show_map_column,
        use_filter2=use_filter2,
    )

if __name__ == "__main__":
    app.run(debug=True)
