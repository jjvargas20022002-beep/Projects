import requests
import pandas as pd
from urllib.parse import quote
from flask import Flask, render_template, request

app = Flask(__name__)

# =====================
# CONFIGURACIÓN
# =====================
SHEET_ID = "1eaNxCpm8JF1JcZS3_ldwMRINGYFaW6RsQQWybvRi_P8"
API_KEY = "AIzaSyBbU7VsAR3M3VADQ3aFxBVto86M1k6EMuY"

TABS = [
    "GARANTIAS LIMA",
    "ONLINE LIMA",
    "GARANTIAS PROVINCIA",
    "FUERA DE GARANTÍA PROVINCIA",
    "CANCELADOS",
    "PENDIENTES ODN"   # 🆕 NUEVO TAB
]

all_rows = pd.DataFrame()

# =====================
# CARGAR SHEET
# =====================
def load_sheet(sheet_name):
    global all_rows

    encoded_name = quote(sheet_name)
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/{encoded_name}?key={API_KEY}"
    data = requests.get(url).json()

    if "values" not in data or len(data["values"]) < 2:
        all_rows = pd.DataFrame()
        return

    headers = data["values"][0]
    rows = data["values"][1:]
    all_rows = pd.DataFrame(rows, columns=headers)

# =====================
# WEB
# =====================
@app.route("/", methods=["GET"])
def index():
    tab = request.args.get("tab", TABS[0])
    branch = request.args.get("branch", "ALL")
    contrata = request.args.get("contrata", "ALL")

    load_sheet(tab)

    if all_rows.empty:
        return render_template(
            "index.html",
            tabs=TABS,
            branches=["ALL"],
            contratas=["ALL"],
            selected_tab=tab,
            selected_branch=branch,
            selected_contrata=contrata,
            headers=[],
            rows=[],
            coord_col=""
        )

    df = all_rows.copy()

    # =====================
    # COLUMNAS
    # =====================
    branch_col = "BRANCH"
    contrata_col = "CONTRATA"
    coord_col = "COORDENADAS"

    # =====================
    # FILTROS
    # =====================
    if branch != "ALL" and branch_col in df.columns:
        df = df[df[branch_col] == branch]

    if contrata != "ALL" and contrata_col in df.columns:
        df = df[df[contrata_col] == contrata]

    # =====================
    # DESPLEGABLES DINÁMICOS
    # =====================
    branches = ["ALL"]
    if branch_col in all_rows.columns:
        branches += sorted(all_rows[branch_col].dropna().unique().tolist())

    contratas = ["ALL"]
    if contrata_col in all_rows.columns:
        contratas += sorted(all_rows[contrata_col].dropna().unique().tolist())

    # =====================
    # COORDENADAS → GOOGLE MAPS
    # =====================
    def coord_to_link(value):
        if pd.isna(value):
            return ""
        value = str(value).strip()
        if "," in value:
            return f"https://www.google.com/maps?q={value}"
        return value

    if coord_col in df.columns:
        df[coord_col] = df[coord_col].apply(coord_to_link)

    return render_template(
        "index.html",
        tabs=TABS,
        branches=branches,
        contratas=contratas,
        selected_tab=tab,
        selected_branch=branch,
        selected_contrata=contrata,
        headers=df.columns.tolist(),
        rows=df.values.tolist(),
        coord_col=coord_col
    )

if __name__ == "__main__":
    app.run()


