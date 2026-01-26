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
    "CANCELADOS"
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
            rows=[]
        )

    df = all_rows.copy()

    # 🔵 Columnas clave
    branch_col = df.columns[0]      # BRANCH
    contrata_col = "CONTRATA"       # nombre exacto de la columna

    # 🔵 Filtro BRANCH
    if branch != "ALL":
        df = df[df[branch_col] == branch]

    # 🔵 Filtro CONTRATA
    if contrata != "ALL" and contrata_col in df.columns:
        df = df[df[contrata_col] == contrata]

    # 🔥 BRANCH dinámico
    branches = sorted(all_rows[branch_col].dropna().unique().tolist())
    branches.insert(0, "ALL")

    # 🔥 CONTRATA dinámico
    if contrata_col in all_rows.columns:
        contratas = sorted(all_rows[contrata_col].dropna().unique().tolist())
        contratas.insert(0, "ALL")
    else:
        contratas = ["ALL"]

    return render_template(
        "index.html",
        tabs=TABS,
        branches=branches,
        contratas=contratas,
        selected_tab=tab,
        selected_branch=branch,
        selected_contrata=contrata,
        headers=df.columns,
        rows=df.values
    )

# ⚠️ SIN debug en producción
if __name__ == "__main__":
    app.run()


