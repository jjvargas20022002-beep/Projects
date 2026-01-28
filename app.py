from flask import Flask, render_template
import pandas as pd

app = Flask(__name__)

SHEET_URL = "https://docs.google.com/spreadsheets/d/1eaNxCpm8JF1JcZS3_ldwMRINGYFaW6RsQQWybvRi_P8/export?format=csv&gid=36214359"

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

@app.route("/")
def index():
    df = pd.read_csv(SHEET_URL)

    # 🔒 Asegurar columnas mínimas
    for col in ["TAB", "SITE", "BRANCH", "CONTRATA", "Coordenadas"]:
        if col not in df.columns:
            df[col] = ""

    # 🔗 Google Maps desde "Coordenadas"
    df["MAP_LINK"] = df["Coordenadas"].apply(
        lambda x: f"https://www.google.com/maps?q={x}"
        if pd.notna(x) and "," in str(x)
        else ""
    )

    tabs = sorted(df["TAB"].dropna().unique())
    data = {}

    for tab in tabs:
        tab_df = df[df["TAB"] == tab]

        if tab in TABS_SITE_ONLY:
            grouped = {
                "SITE": {
                    site: tab_df[tab_df["SITE"] == site].to_dict("records")
                    for site in sorted(tab_df["SITE"].dropna().unique())
                }
            }
        else:
            grouped = {}

            if "BRANCH" in tab_df.columns:
                grouped["BRANCH"] = {
                    b: tab_df[tab_df["BRANCH"] == b].to_dict("records")
                    for b in sorted(tab_df["BRANCH"].dropna().unique())
                }

            if "CONTRATA" in tab_df.columns:
                grouped["CONTRATA"] = {
                    c: tab_df[tab_df["CONTRATA"] == c].to_dict("records")
                    for c in sorted(tab_df["CONTRATA"].dropna().unique())
                }

        data[tab] = grouped

    return render_template("index.html", tabs=tabs, data=data)

if __name__ == "__main__":
    app.run(debug=True)