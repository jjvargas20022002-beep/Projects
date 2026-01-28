from flask import Flask, render_template, request
import pandas as pd

app = Flask(__name__)

SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/1eaNxCpm8JF1JcZS3_ldwMRINGYFaW6RsQQWybvRi_P8/export?format=csv&gid=36214359"

TABS_SITE_ONLY = {
    "LI1 TGI",
    "LI2 DIJUSA",
    "LI2 ERAM",
    "LI3 INTER",
    "LI4 TGI",
    "LI4 SMP",
    "LI7 MARCOS",
    "LI4 BROKERS"
}

TABS_NO_MAP = {"CANCELADOS", "ONLINE LIMA"}

@app.route("/")
def index():
    df = pd.read_csv(SHEET_CSV_URL)

    # TAB seleccionado
    tabs = sorted(df["TAB"].dropna().unique())
    selected_tab = request.args.get("tab", tabs[0])

    df_tab = df[df["TAB"] == selected_tab]

    # MAP LINK desde Coordenadas
    if "Coordenadas" in df_tab.columns and selected_tab not in TABS_NO_MAP:
        df_tab["MAP_LINK"] = df_tab["Coordenadas"].apply(
            lambda x: f"https://www.google.com/maps?q={x}"
            if pd.notna(x) and "," in str(x)
            else ""
        )
    else:
        df_tab["MAP_LINK"] = ""

    # Filtros
    show_branch = selected_tab not in TABS_SITE_ONLY
    show_contrata = selected_tab not in TABS_SITE_ONLY

    branches = sorted(df_tab["BRANCH"].dropna().unique()) if show_branch and "BRANCH" in df_tab.columns else []
    contratas = sorted(df_tab["CONTRATA"].dropna().unique()) if show_contrata and "CONTRATA" in df_tab.columns else []

    selected_branch = request.args.get("branch")
    selected_contrata = request.args.get("contrata")

    if selected_branch:
        df_tab = df_tab[df_tab["BRANCH"] == selected_branch]

    if selected_contrata:
        df_tab = df_tab[df_tab["CONTRATA"] == selected_contrata]

    headers = [c for c in df_tab.columns if c not in ["Coordenadas", "MAP_LINK"]]
    rows = df_tab.to_dict("records")

    return render_template(
        "index.html",
        tabs=tabs,
        selected_tab=selected_tab,
        branches=branches,
        contratas=contratas,
        selected_branch=selected_branch,
        selected_contrata=selected_contrata,
        show_branch=show_branch,
        show_contrata=show_contrata,
        headers=headers,
        rows=rows
    )

if __name__ == "__main__":
    app.run(debug=True)