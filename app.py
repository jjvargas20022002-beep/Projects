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

SPECIAL_TABS = [
    "LI1 TGI", "LI2 ERAM", "LI2 DIJUSA",
    "LI3 INTER", "LI4 BROKERS", "LI4 TGI", "LI7 MARCOS"
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
# ROUTE
# =====================
@app.route("/")
def index():
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

    # ===== columnas =====
    coord_idx = find_col(headers, "COORDENADAS")
    caja_idx = find_col_exact(headers, "CAJA")
    cuenta_idx = find_col(headers, "CUENTA")

    status_idx = find_col(headers, "STATUS DE LA CAJA")
    estado_idx = find_col(headers, "ESTADO DE CAJA")
    reporte_idx = find_col(headers, "REPORTE DE CONTRATA")

    # ===== filtros =====
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

    rows_after_f1 = rows_all if not selected_filter1 else [
        r for r in rows_all if len(r) > col1_idx and r[col1_idx] == selected_filter1
    ]

    filtered_rows = rows_after_f1 if not selected_filter2 else [
        r for r in rows_after_f1 if len(r) > col2_idx and r[col2_idx] == selected_filter2
    ]

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
                    "estado": r[estado_idx] if estado_idx is not None else "",
                    "reporte": r[reporte_idx] if reporte_idx is not None else "",
                })
            except:
                pass

    return render_template(
        "index.html",
        tabs=tabs,
        selected_tab=selected_tab,
        last_tab=selected_tab,
        headers=headers,
        rows_with_links=[],
        filters1=[],
        filters2=[],
        selected_filter1=selected_filter1,
        selected_filter2=selected_filter2,
        total_rows=total_rows,
        filtered_count=filtered_count,
        coords_info=coords_info,
        has_coords=coord_idx is not None,
        show_map_column=coord_idx is not None
    )

if __name__ == "__main__":
    app.run(debug=True)
