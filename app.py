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
    "ONLINE LIMA",
    "PENDIENTES ODN",
]

# =====================
# UTILS
# =====================
def coord_to_link(value):
    try:
        lat, lng = map(float, value.split(","))
        return f"https://www.google.com/maps?q={lat},{lng}"
    except:
        return None

# =====================
# ROUTES
# =====================
@app.route("/")
def index():
    tabs = [ws.title for ws in sheet.worksheets()]
    selected_tab = request.args.get("tab", tabs[0])

    ws = sheet.worksheet(selected_tab)
    data = ws.get_all_values()

    headers = data[0]
    rows_all = data[1:]

    def col(name):
        return headers.index(name) if name in headers else None

    coord_idx = next((i for i, h in enumerate(headers) if "COORD" in h.upper()), None)

    # ===== COLUMNAS PARA FILTROS
    if selected_tab in BRANCH_TABS:
        col1_name, col2_name = "BRANCH", "CONTRATA"
    else:
        col1_name, col2_name = "SITE", "REPORTE CONTRATA"

    col1_idx = col(col1_name)
    col2_idx = col(col2_name)

    # ===== VALORES DE FILTROS
    filters1 = sorted({r[col1_idx] for r in rows_all if col1_idx is not None and r[col1_idx]})
    filters2 = sorted({r[col2_idx] for r in rows_all if col2_idx is not None and r[col2_idx]})

    selected_filter1 = request.args.get("filter1", "")
    selected_filter2 = request.args.get("filter2", "")

    # ===== FILTRADO DE FILAS
    filtered_rows = []
    for r in rows_all:
        if col1_idx is not None and selected_filter1 and r[col1_idx] != selected_filter1:
            continue
        if col2_idx is not None and selected_filter2 and r[col2_idx] != selected_filter2:
            continue
        filtered_rows.append(r)

    # ===== MAPA: SOLO COORDENADAS FILTRADAS
    all_coords = []
    if coord_idx is not None:
        for r in filtered_rows:
            if len(r) > coord_idx:
                try:
                    lat, lng = map(float, r[coord_idx].split(","))
                    all_coords.append({"lat": lat, "lng": lng})
                except:
                    pass

    # ===== HEADERS SIN COLUMNA COORD
    visible_headers = (
        headers[:coord_idx] + headers[coord_idx + 1 :]
        if coord_idx is not None
        else headers
    )

    # ===== FILAS + LINK MAPA
    rows_with_links = []
    for r in filtered_rows:
        row_visible = r[:coord_idx] + r[coord_idx + 1 :] if coord_idx is not None else r
        link = coord_to_link(r[coord_idx]) if coord_idx is not None else None
        rows_with_links.append((row_visible, link))

    return render_template(
        "index.html",
        tabs=tabs,
        selected_tab=selected_tab,
        headers=visible_headers,
        rows_with_links=rows_with_links,
        has_coords=coord_idx is not None,
        all_coords=all_coords,
        is_branch_tab=selected_tab in BRANCH_TABS,
        filters1=filters1,
        filters2=filters2,
        selected_filter1=selected_filter1,
        selected_filter2=selected_filter2,
    )

if __name__ == "__main__":
    app.run(debug=True)