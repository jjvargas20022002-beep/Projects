from flask import Flask, render_template, request
import gspread
from google.oauth2.service_account import Credentials
import os
import re

app = Flask(__name__)

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
# TABs que usan Reporte de Contrata
# =====================
TABS_CON_REPORTE = {
    "LI1 TGI",
    "LI2 DIJUSA",
    "LI2 ERAM",
    "LI3 INTER",
    "LI4 TGI",
    "LI4 SMP",
    "LI7 MARCOS",
}

def coord_to_link(value):
    if not value:
        return None
    value = re.sub(r"\s+", "", str(value))
    if "," not in value:
        return None
    try:
        lat, lon = value.split(",", 1)
        float(lat); float(lon)
        return f"https://www.google.com/maps?q={lat},{lon}"
    except:
        return None


@app.route("/")
def index():
    tabs = [ws.title for ws in sheet.worksheets()]
    selected_tab = request.args.get("tab", tabs[0])

    ws = sheet.worksheet(selected_tab)
    data = ws.get_all_values()

    headers = data[0]
    rows = data[1:]

    def idx(name):
        return headers.index(name) if name in headers else None

    branch_idx = idx("BRANCH")
    contrata_idx = idx("CONTRATA")
    reporte_idx = idx("Reporte de Contrata")

    coord_idx = next(
        (i for i, h in enumerate(headers) if any(k in h.upper() for k in ["COORD", "GPS", "UBIC"])),
        None
    )

    selected_branch = request.args.get("branch", "")
    selected_contrata = request.args.get("contrata", "")
    selected_reporte = request.args.get("reporte", "")

    if selected_branch and branch_idx is not None:
        rows = [r for r in rows if r[branch_idx] == selected_branch]

    if selected_contrata and contrata_idx is not None:
        rows = [r for r in rows if r[contrata_idx] == selected_contrata]

    if selected_reporte and reporte_idx is not None:
        rows = [r for r in rows if r[reporte_idx] == selected_reporte]

    branches = sorted({r[branch_idx] for r in data[1:] if branch_idx is not None and r[branch_idx]})
    contratas = sorted({r[contrata_idx] for r in data[1:] if contrata_idx is not None and r[contrata_idx]})
    reportes = (
        sorted({r[reporte_idx] for r in data[1:] if reporte_idx is not None and r[reporte_idx]})
        if selected_tab in TABS_CON_REPORTE else []
    )

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
        coord_idx=coord_idx,
        branches=branches,
        contratas=contratas,
        reportes=reportes,
        selected_branch=selected_branch,
        selected_contrata=selected_contrata,
        selected_reporte=selected_reporte,
        show_reporte=selected_tab in TABS_CON_REPORTE,
    )
