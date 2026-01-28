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

# Tabs con filtros BRANCH / CONTRATA
BRANCH_TABS = [
    "GARANTIAS LIMA",
    "GARANTIAS PROVINCIA",
    "FUERA DE GARANTÍA PROVINCIA",
    "CANCELADOS",
    "ONLINE LIMA",
    "PENDIENTES ODN",
]

@app.route("/")
def index():
    tabs = [ws.title for ws in sheet.worksheets()]

    selected_tab = request.args.get("tab")
    if not selected_tab or selected_tab not in tabs:
        selected_tab = tabs[0]

    prev_tab = request.args.get("prev_tab", "")
    tab_changed = prev_tab != selected_tab

    ws = sheet.worksheet(selected_tab)
    data = ws.get_all_values()

    headers = data[0]
    rows = data[1:]

    def col(name):
        return headers.index(name) if name in headers else None

    branch_idx = col("BRANCH")
    contrata_idx = col("CONTRATA")
    site_idx = col("SITE")
    reporte_idx = col("Reporte de Contrata")

    coord_idx = None
    for i, h in enumerate(headers):
        if any(k in h.upper() for k in ["COORD", "GPS", "UBIC"]):
            coord_idx = i
            break

    has_coords = coord_idx is not None
    is_branch_tab = selected_tab in BRANCH_TABS

    if tab_changed:
        f1 = ""
        f2 = ""
    else:
        f1 = request.args.get("filter1", "")
        f2 = request.args.get("filter2", "")

    if is_branch_tab:
        if f1 and branch_idx is not None:
            rows = [r for r in rows if len(r) > branch_idx and r[branch_idx] == f1]
        if f2 and contrata_idx is not None:
            rows = [r for r in rows if len(r) > contrata_idx and r[contrata_idx] == f2]

        filters1 = sorted({r[branch_idx] for r in data[1:] if branch_idx is not None and len(r) > branch_idx})
        filters2 = sorted({r[contrata_idx] for r in data[1:] if contrata_idx is not None and len(r) > contrata_idx})
    else:
        if f1 and site_idx is not None:
            rows = [r for r in rows if len(r) > site_idx and r[site_idx] == f1]
        if f2 and reporte_idx is not None:
            rows = [r for r in rows if len(r) > reporte_idx and r[reporte_idx] == f2]

        filters1 = sorted({r[site_idx] for r in data[1:] if site_idx is not None and len(r) > site_idx})
        filters2 = sorted({r[reporte_idx] for r in data[1:] if reporte_idx is not None and len(r) > reporte_idx})

    coords = []
    rows_clean = []

    for r in rows:
        if coord_idx is not None and len(r) > coord_idx:
            try:
                lat, lng = map(float, r[coord_idx].split(","))
                coords.append({"lat": lat, "lng": lng})
            except:
                pass
            r = r[:coord_idx] + r[coord_idx + 1 :]
        rows_clean.append(r)

    visible_headers = headers.copy()
    if coord_idx is not None:
        visible_headers.pop(coord_idx)

    return render_template(
        "index.html",
        tabs=tabs,
        selected_tab=selected_tab,
        headers=visible_headers,
        rows=rows_clean,
        filters1=filters1,
        filters2=filters2,
        selected_filter1=f1,
        selected_filter2=f2,
        is_branch_tab=is_branch_tab,
        has_coords=has_coords,
        coords=coords,
    )

if __name__ == "__main__":
    app.run(debug=True)