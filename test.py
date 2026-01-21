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

BRANCHES = {
    "LIMA": ["ALL", "LI1", "LI2", "LI3", "LI4", "LI7"],
    "PROVINCIA": ["ALL", "ARE", "CUS", "CAJ", "HUN", "JUN", "LAL", "PIU", "SAN"]
}

headers = []
all_rows = pd.DataFrame()

# =====================
# CARGAR SHEET
# =====================
def load_sheet(sheet_name):
    global headers, all_rows

    encoded_name = quote(sheet_name)
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/{encoded_name}?key={API_KEY}"

    data = requests.get(url).json()

    headers = data["values"][0]
    rows = data["values"][1:]
    all_rows = pd.DataFrame(rows, columns=headers)

# =====================
# WEB
# =====================
@app.route("/", methods=["GET"])
def index():
    tab = request.args.get("tab", "GARANTIAS LIMA")
    branch = request.args.get("branch", "ALL")

    load_sheet(tab)

    df = all_rows
    if branch != "ALL":
        df = df[df[df.columns[0]] == branch]

    branches = BRANCHES["LIMA"] if "LIMA" in tab else BRANCHES["PROVINCIA"]

    return render_template(
        "index.html",
        tabs=TABS,
        branches=branches,
        selected_tab=tab,
        selected_branch=branch,
        headers=df.columns,
        rows=df.values
    )

if __name__ == "__main__":
    app.run(debug=True)
