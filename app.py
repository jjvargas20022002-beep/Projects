from flask import Flask, render_template, request
import pandas as pd

app = Flask(__name__)

SPREADSHEET_ID = "1eaNxCpm8JF1JcZS3_ldwMRINGYFaW6RsQQWybvRi_P8"

SHEETS = {
    "LI1 TGI": "36214359",
    "LI2 DIJUSA": "123456789",
    "LI2 ERAM": "234567891",
    "LI3 INTER": "345678912",
    "LI4 TGI": "456789123",
    "LI4 SMP": "567891234",
    "LI7 MARCOS": "678912345",
    "LI4 BROKERS": "789123456",
    "CANCELADOS": "891234567",
    "ONLINE LIMA": "912345678"
}

SITE_ONLY_TABS = {
    "LI1 TGI",
    "LI2 DIJUSA",
    "LI2 ERAM",
    "LI3 INTER",
    "LI4 TGI",
    "LI4 SMP",
    "LI7 MARCOS",
    "LI4 BROKERS"
}

NO_MAP_TABS = {"CANCELADOS", "ONLINE LIMA"}

@app.route("/")
def index():
    selected_tab = request.args.get("tab", list(SHEETS.keys())[0])
    gid = SHEETS[selected_tab]

    csv_url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid={gid}"
    df = pd.read_csv(csv_url)

    df.columns = df.columns.str.strip()

    # MAPA
    if "Coordenadas" in df.columns and selected_tab not in NO_MAP_TABS:
        df["MAP_LINK"] = df["Coordenadas"].apply(
            lambda x: f"https://www.google.com/maps?q={x}"
            if pd.notna(x) and "," in str(x)
            else ""
        )
    else:
        df["MAP_LINK"] = ""

    show_branch = selected_tab not in SITE_ONLY_TABS and "BRANCH" in df.columns
    show_contrata = selected_tab not in SITE_ONLY_TABS and "CONTRATA" in df.columns

    branch = request.args.get("branch")
    contrata = request.args.get("contrata")

    if branch:
        df = df[df["BRANCH"] == branch]

    if contrata:
        df = df[df["CONTRATA"] == contrata]

    branches = sorted(df["BRANCH"].dropna().unique()) if show_branch else []
    contratas = sorted(df["CONTRATA"].dropna().unique()) if show_contrata else []

    headers = [c for c in df.columns if c not in ["Coordenadas", "MAP_LINK"]]
    rows = df.to_dict("records")

    return render_template(
        "index.html",
        tabs=SHEETS.keys(),
        selected_tab=selected_tab,
        branches=branches,
        contratas=contratas,
        selected_branch=branch,
        selected_contrata=contrata,
        show_branch=show_branch,
        show_contrata=show_contrata,
        headers=headers,
        rows=rows
    )

if __name__ == "__main__":
    app.run(debug=True)