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
        "private_key_id": os.environ.get("GCP_PRIVATE_KEY").replace("\\n", "\n"),
        "client_email": os.environ.get("GCP_CLIENT_EMAIL"),
        "token_uri": "https://oauth2.googleapis.com/token",
    },
    scopes=SCOPES,
)

gc = gspread.authorize(creds)
sheet = gc.open_by_key(SPREADSHEET_ID)

BRANCH_TABS = [
    "GARANTIAS LIMA",
    "GARANTIAS PROVINCIA",
    "FUERA DE GARANTÍA PROVINCIA",
    "CANCELADOS",
    "ONLINE LIMA",
    "PENDIENTES ODN",
]

def coord_to_link(value):
    try:
        lat, lng = map(float, value.split(","))
        return f"https://www.google.com/maps?q={lat},{lng}"
    except:
        return None

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

    coord_idx = next((i for i,h in enumerate(headers) if "COORD" in h.upper()), None)

    # ====== TODAS las coordenadas del TAB (sin filtros)
    all_coords = []
    if coord_idx is not None:
        for r in rows_all:
            if len(r) > coord_idx:
                try:
                    lat, lng = map(float, r[coord_idx].split(","))
                    all_coords.append({"lat": lat, "lng": lng})
                except:
                    pass

    # ====== FILTROS (solo afectan la tabla)
    prev_tab = request.args.get("prev_tab", "")
    reset = prev_tab != selected_tab

    f1 = "" if reset else request.args.get("filter1", "")
    f2 = "" if reset else request.args.get("filter2", "")

    is_branch_tab = selected_tab in BRANCH_TABS

    branch_idx = col("BRANCH")
    contrata_idx = col("CONTRATA")
    site_idx = col("SITE")
    reporte_idx = col("Reporte de Contrata")

    rows = rows_all.copy()

    if is_branch_tab:
        if f1 and branch_idx is not None:
            rows = [r for r in rows if r[branch_idx] == f1]
        if f2 and contrata_idx is not None:
            rows = [r for r in rows if r[contrata_idx] == f2]

        filters1 = sorted(set(r[branch_idx] for r in rows_all if branch_idx is not None))
        filters2 = sorted(set(r[contrata_idx] for r in rows_all if contrata_idx is not None))
    else:
        if f1 and site_idx is not None:
            rows = [r for r in rows if r[site_idx] == f1]
        if f2 and reporte_idx is not None:
            rows = [r for r in rows if r[reporte_idx] == f2]

        filters1 = sorted(set(r[site_idx] for r in rows_all if site_idx is not None))
        filters2 = sorted(set(r[reporte_idx] for r in rows_all if reporte_idx is not None))

    # ====== Tabla + links por fila
    visible_headers = headers.copy()
    if coord_idx is not None:
        visible_headers.pop(coord_idx)

    rows_with_links = []
    for r in rows:
        link = coord_to_link(r[coord_idx]) if coord_idx is not None and len(r) > coord_idx else None
        if coord_idx is not None:
            r = r[:coord_idx] + r[coord_idx+1:]
        rows_with_links.append((r, link))

    return render_template(
        "index.html",
        tabs=tabs,
        selected_tab=selected_tab,
        headers=visible_headers,
        rows_with_links=rows_with_links,
        filters1=filters1,
        filters2=filters2,
        selected_filter1=f1,
        selected_filter2=f2,
        is_branch_tab=is_branch_tab,
        has_coords=coord_idx is not None,
        all_coords=all_coords,
    )

if __name__ == "__main__":
    app.run(debug=True)