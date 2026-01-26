from flask import Flask, render_template, request
import gspread
from google.oauth2.service_account import Credentials
import os

app = Flask(__name__)

# --- Google Sheets config ---
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

@app.route("/")
def index():
    tabs = [ws.title for ws in sheet.worksheets()]

    selected_tab = request.args.get("tab", tabs[0])
    ws = sheet.worksheet(selected_tab)

    data = ws.get_all_values()
    headers = data[0]
    rows = data[1:]

    # Detectar columnas
    def col_index(name):
        return headers.index(name) if name in headers else None

    branch_idx = col_index("BRANCH")
    contrata_idx = col_index("CONTRATA")

    branches = sorted(set(r[branch_idx] for r in rows if branch_idx is not None and r[branch_idx]))
    contratas = sorted(set(r[contrata_idx] for r in rows if contrata_idx is not None and r[contrata_idx]))

    selected_branch = request.args.get("branch", "")
    selected_contrata = request.args.get("contrata", "")

    if selected_branch and branch_idx is not None:
        rows = [r for r in rows if r[branch_idx] == selected_branch]

    if selected_contrata and contrata_idx is not None:
        rows = [r for r in rows if r[contrata_idx] == selected_contrata]

    # Detectar columna de coordenadas
    coord_col = None
    for h in headers:
        if "COORD" in h.upper() or "GPS" in h.upper() or "UBIC" in h.upper():
            coord_col = h
            break

    return render_template(
        "index.html",
        tabs=tabs,
        selected_tab=selected_tab,
        headers=headers,
        rows=rows,
        branches=branches,
        contratas=contratas,
        selected_branch=selected_branch,
        selected_contrata=selected_contrata,
        coord_col=coord_col,
    )

if __name__ == "__main__":
    app.run(debug=True)
