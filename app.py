from flask import Flask, render_template, request
import gspread
from google.oauth2.service_account import Credentials
import os

app = Flask(__name__)

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
# ROUTE
# =====================
@app.route("/")
def index():
    tabs = [ws.title for ws in sheet.worksheets()]
    selected_tab = request.args.get("tab", tabs[0])
    last_tab = request.args.get("last_tab", "")
    selected_filter1 = request.args.get("filter1", "")
    selected_filter2 = request.args.get("filter2", "")

    # 🔑 reset filtros al cambiar TAB
    if last_tab != selected_tab:
        selected_filter1 = ""
        selected_filter2 = ""

    ws = sheet.worksheet(selected_tab)
    data = ws.get_all_values()

    headers = data[0]
    rows_all = data[1:]
    total_rows = len(rows_all)

    # ===== columnas comunes =====
    coord_idx = find_col(headers, "COORDENADAS")
    caja_idx = find_col_exact(headers, "CAJA")
    cuenta_idx = find_col(headers, "CUENTA")
    status_idx = find_col(headers, "STATUS DE LA CAJA")

    # ===== definición de filtros por TAB =====
    if selected_tab in BRANCH_TABS:
        col1_name, col2_name = "BRANCH", "CONTRATA"
        use_filter2 = True
    elif selected_tab == SINGLE_BRANCH_TAB:
        col1_name, col2_name = "BRANCH", None
        use_filter2 = False
    else:
        col1_name, col2_name = "SITE", "REPORTE CONTRATA"
        use_filter2 = True

    col1_idx = find_col(headers, col1_name)
    col2_idx = find_col(headers, col2_name) if col2_name else None

    # ===== FILTRO 1 =====
    if col1_idx is not None and selected_filter1:
        rows_after_f1 = [
            r for r in rows_all
            if len(r) > col1_idx and r[col1_idx] == selected_filter1
        ]
    else:
        rows_after_f1 = rows_all

    # ===== FILTRO 2 =====
    if use_filter2 and col2_idx is not None and selected_filter2:
        filtered_rows = [
            r for r in rows_after_f1
            if len(r) > col2_idx and r[col2_idx] == selected_filter2
        ]
    else:
        filtered_rows = rows_after_f1

    # ===== opciones de filtros =====
    filters1 = sorted({
        r[col1_idx] for r in filtered_rows
        if col1_idx is not None and len(r) > col1_idx and r[col1_idx]
    })

    filters2 = []
    if use_filter2 and col2_idx is not None:
        filters2 = sorted({
            r[col2_idx] for r in rows_after_f1
            if len(r) > col2_idx and r[col2_idx]
        })

    filtered_count = len(filtered_rows)

    # ===== coordenadas =====
    coords_info = []
    if coord_idx is not None:
        for r in filtered_rows:
            try:
                lat, lng = map(float, r[coord_idx].replace(" ", "").split(",", 1))
                coords_info.append({
                    "lat": lat,
                    "lng": lng,
                    "caja": r[caja_idx] if caja_idx is not None else "",
                    "cuenta": r[cuenta_idx] if cuenta_idx is not None else "",
                    "status": r[status_idx] if status_idx is not None else "",
                })
            except:
                pass

    # ===== ocultar columnas =====
    hidden_idxs = set()

    if coord_idx is not None:
        hidden_idxs.add(coord_idx)
