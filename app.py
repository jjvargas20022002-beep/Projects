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
# ROUTES
# =====================
@app.route("/")
def index():
    # Tabs
    tabs = [ws.title for ws in sheet.worksheets()]
    selected_tab = request.args.get("tab")
    if not selected_tab or selected_tab not in tabs:
        selected_tab = tabs[0]

    # Data
    ws = sheet.worksheet(selected_tab)
    data = ws.get_all_values()
    if not data or len(data) < 2:
        return render_template(
            "index.html",
            tabs=tabs,
            selected_tab=selected_tab,
            headers=[],
            rows_with_links=[],
            branches=[],
            contratas=[],
            selected_branch="",
            selected_contrata="",
            coord_idx=None,
        )

    headers = data[0]
    rows = data[1:]

    # Column indices
    branch_idx = col_index(headers, ["BRANCH", "SITE"])
    contrata_idx = col_index(headers, ["CONTRATA", "REPORTE"])
    coord_idx = col_index(headers, ["COORD", "GPS", "UBIC"])

    # Filtros
    selected_branch = request.args.get("branch", "")
    selected_contrata = request.args.get("contrata", "")

    if selected_branch and branch_idx is not None:
        rows = [r for r in rows if len(r) > branch_idx and r[branch_idx] == selected_branch]

    if selected_contrata and contrata_idx is not None:
        rows = [r for r in rows if len(r) > contrata_idx and r[contrata_idx] == selected_contrata]

    branches = sorted({r[branch_idx] for r in data[1:] if branch_idx is not None and len(r) > branch_idx}) if branch_idx is not None else []
    contratas = sorted({r[contrata_idx] for r in data[1:] if contrata_idx is not None and len(r) > contrata_idx}) if contrata_idx is not None else []

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
        branches=branches,
        contratas=contratas,
        selected_branch=selected_branch,
        selected_contrata=selected_contrata,
        coord_idx=coord_idx,
    )

if __name__ == "__main__":
    app.run(debug=True)