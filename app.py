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

# =====================
# ROUTE
# =====================
@app.route("/")
def index():
    tabs = [ws.title for ws in sheet.worksheets()]

    # ====== obtener valores del formulario ======
    selected_tab = request.args.get("tab", tabs[0])
    last_tab = request.args.get("last_tab", "")
    selected_filter1 = request.args.get("filter1", "")
    selected_filter2 = request.args.get("filter2", "")

    if last_tab != selected_tab:
        selected_filter1 = ""
        selected_filter2 = ""

    # ====== obtener datos del sheet ======
    ws = sheet.worksheet(selected_tab)
    data = ws.get_all_values()
    headers = data[0]
    rows_all = data[1:]
    total_rows = len(rows_all)

    # ====== columnas especiales ======
    coord_idx = find_col(headers, "COORDENADAS")
    caja_idx = find_col(headers, "CAJA")
    cuenta_idx = find_col(headers, "CUENTA")

    # ====== columnas para filtros ======
    if selected_tab in BRANCH_TABS:
        col1_name, col2_name = "BRANCH", "CONTRATA"
    else:
        col1_name, col2_name = "SITE", "REPORTE CONTRATA"

    col1_idx = find_col(headers, col1_name)
    col2_idx = find_col(headers, col2_name)

    # ====== valores únicos para selects ======
    filters1 = sorted({r[col1_idx] for r in rows_all if col1_idx is not None and len(r) > col1_idx and r[col1_idx]})
    filters2 = sorted({r[col2_idx] for r in rows_all if col2_idx is not None and len(r) > col2_idx and r[col2_idx]})

    # ====== filtrado de filas ======
    filtered_rows = []
    for r in rows_all:
        if selected_filter1 and r[col1_idx] != selected_filter1:
            continue
        if selected_filter2 and r[col2_idx] != selected_filter2:
            continue
        filtered_rows.append(r)
    filtered_count = len(filtered_rows)

    # ====== coordenadas para mapa ======
    coords_info = []
    if coord_idx is not None:
        for r in rows_all:
            try:
                lat, lng = map(float, r[coord_idx].replace(" ", "").split(",", 1))
                caja = r[caja_idx] if caja_idx is not None and len(r) > caja_idx else ""
                cuenta = r[cuenta_idx] if cuenta_idx is not None and len(r) > cuenta_idx else ""
                coords_info.append({"lat": lat, "lng": lng, "caja": caja, "cuenta": cuenta})
            except:
                pass

    # ====== ocultar columnas ======
    hidden_idxs = set()
    if selected_tab == "PENDIENTES ODN" and caja_idx is not None:
        hidden_idxs.add(caja_idx)
    hidden_idxs |= {i for i, h in enumerate(headers) if "LINK" in h.upper()}

    # Mostrar columna MAPA si hay coordenadas
    show_map_column = coord_idx is not None

    # headers visibles
    visible_headers = [h for i, h in enumerate(headers) if i not in hidden_idxs]

    # filas con links → **revisar PENDIENTES ODN**
    rows_with_links = []
    for r in filtered_rows:
        visible_row = [c for i, c in enumerate(r) if i not in hidden_idxs]
        link = None
        if coord_idx is not None and len(r) > coord_idx and r[coord_idx].strip():
            link = coord_to_link(r[coord_idx])
        rows_with_links.append((visible_row, link))

    return render_template(
        "index.html",
        tabs=tabs,
        selected_tab=selected_tab,
        last_tab="",
        headers=visible_headers,
        rows_with_links=rows_with_links,
        filters1=filters1,
        filters2=filters2,
        selected_filter1=selected_filter1,
        selected_filter2=selected_filter2,
        total_rows=total_rows,
        filtered_count=filtered_count,
        all_coords=coords_info,
        coords_info=coords_info,
        has_coords=coord_idx is not None,
        is_branch_tab=selected_tab in BRANCH_TABS,
        show_map_column=show_map_column
    )

if __name__ == "__main__":
    app.run(debug=True)