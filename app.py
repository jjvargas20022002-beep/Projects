from flask import Flask, render_template, request
import gspread
from google.oauth2.service_account import Credentials
import os
import re

app = Flask(__name__)

# =====================
# GOOGLE SHEETS CONFIG
# =====================
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")

creds = Credentials.from_service_account_info(
    {
        "type": "service_account",
        "project_id": os.environ.get("GCP_PROJECT_ID"),
        "private_key_id": os.environ.get("GCP_PRIVATE_KEY_ID"),
        "private_key": os.environ.get("GCP_PRIVATE_KEY").replace("\\n", "\n"),
        "client_email": os.environ.get("GCP_CLIENT_EMAIL"),
        "client_id": os.environ.get("GCP_CLIENT_ID"),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url": os.environ.get("GCP_CLIENT_CERT_URL"),
    },
    scopes=SCOPES,
)

gc = gspread.authorize(creds)
sheet = gc.open_by_key(SPREADSHEET_ID)

# =====================
# UTILS
# =====================
def coord_to_link(value):
    if not value:
        return None
    value = str(value).strip()
    value = re.sub(r"\s+", "", value)
    if "," not in value:
        return None
    try:
        lat, lon = value.split(",", 1)
        float(lat)
        float(lon)
        return f"https://www.google.com/maps?q={lat},{lon}"
    except:
        return None

def col_index(headers, name_list):
    """Busca el índice de la primera columna que coincida con algún nombre"""
    for i, h in enumerate(headers):
        for name in name_list:
            if name.upper() in h.upper():
                return i
    return None

# =====================
# CONFIGURACIÓN FILTROS POR TAB
# =====================
BRANCH_TABS = [
    "GARANTIAS LIMA",
    "GARANTIAS PROVINCIA",
    "FUERA DE GARANTÍA PROVINCIA",
    "CANCELADOS",
    "ONLINE LIMA",
    "PENDIENTES ODN"
]

# =====================
# ROUTES
# =====================
@app.route("/")
def index():
    # Tabs
    tabs = [ws.title for ws in sheet.worksheets()]
    selected_tab = request.args.get("tab")
    if not selected_tab or selected_tab not in tabs:
        selected_tab = tabs[0]

    ws = sheet.worksheet(selected_tab)
    data = ws.get_all_values()
    if not data or len(data) < 2:
        return render_template(
            "index.html",
            tabs=tabs,
            selected_tab=selected_tab,
            headers=[],
            rows_with_links=[],
            filters1=[],
            filters2=[],
            selected_filter1="",
            selected_filter2="",
            coord_idx=None,
            is_branch_tab=False,
        )

    headers = data[0]
    rows = data[1:]

    # Determinar qué filtros usar según TAB
    is_branch_tab = selected_tab in BRANCH_TABS
    if is_branch_tab:
        filter1_name_list = ["BRANCH"]
        filter2_name_list = ["CONTRATA"]
    else:
        filter1_name_list = ["SITE"]
        filter2_name_list = ["Reporte de Contrata"]

    filter1_idx = col_index(headers, filter1_name_list)
    filter2_idx = col_index(headers, filter2_name_list)
    coord_idx = col_index(headers, ["COORD", "GPS", "UBIC"])

    # Reiniciar filtros al cambiar de TAB
    selected_filter1 = request.args.get("filter1", "")
    selected_filter2 = request.args.get("filter2", "")

    if selected_filter1 and filter1_idx is not None:
        rows = [r for r in rows if len(r) > filter1_idx and r[filter1_idx] == selected_filter1]

    if selected_filter2 and filter2_idx is not None:
        rows = [r for r in rows if len(r) > filter2_idx and r[filter2_idx] == selected_filter2]

    # Obtener opciones únicas para desglosables
    filters1 = sorted({r[filter1_idx] for r in data[1:] if filter1_idx is not None and len(r) > filter1_idx}) if filter1_idx is not None else []
    filters2 = sorted({r[filter2_idx] for r in data[1:] if filter2_idx is not None and len(r) > filter2_idx}) if filter2_idx is not None else []

    # Agregar links de coordenadas
    rows_with_links = []
    for r in rows:
        link = coord_to_link(r[coord_idx]) if coord_idx is not None and len(r) > coord_idx else None
        rows_with_links.append((r, link))

    return render_template(
        "index.html",
        tabs=tabs,
        selected_tab=selected_tab,
        headers=headers,
        rows_with_links=rows_with_links,
        filters1=filters1,
        filters2=filters2,
        selected_filter1=selected_filter1,
        selected_filter2=selected_filter2,
        coord_idx=coord_idx,
        is_branch_tab=is_branch_tab,
    )

if __name__ == "__main__":
    app.run(debug=True)