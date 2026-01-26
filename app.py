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

    load_sheet(tab)

    if all_rows.empty:
        return render_template(
            "index.html",
            tabs=TABS,
            branches=["ALL"],
            selected_tab=tab,
            selected_branch=branch,
            headers=[],
            rows=[]
        )

    # 🔵 Filtrado por BRANCH
    df = all_rows.copy()
    branch_column = df.columns[0]

    if branch != "ALL":
        df = df[df[branch_column] == branch]

    # 🔥 BRANCH dinámico desde el Sheet
    branches = sorted(all_rows[branch_column].dropna().unique().tolist())
    branches.insert(0, "ALL")

    return render_template(
        "index.html",
        tabs=TABS,
        branches=branches,
        selected_tab=tab,
        selected_branch=branch,
        headers=df.columns,
        rows=df.values
    )

# ⚠️ IMPORTANTE: sin debug en producción
if __name__ == "__main__":
    app.run()


