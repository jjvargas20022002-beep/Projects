from flask import Flask, render_template
import pandas as pd

app = Flask(__name__)

# Tabs que SOLO usan SITE
TABS_SITE_ONLY = {
    "LI1 TGI",
    "LI2 DIJUSA",
    "LI2 ERAM",
    "LI3 INTER",
    "LI4 TGI",
    "LI4 BROKERS",
    "LI7 MARCOS"
}

@app.route("/")
def index():
    df = pd.read_csv("data.csv")

    # Asegurar columnas necesarias
    for col in ["LATITUDE", "LONGITUDE", "TAB", "SITE", "BRANCH", "CONTRATA"]:
        if col not in df.columns:
            df[col] = ""

    # Link Google Maps
    df["MAP_LINK"] = df.apply(
        lambda r: f"https://www.google.com/maps?q={r['LATITUDE']},{r['LONGITUDE']}"
        if str(r["LATITUDE"]).strip() != "" and str(r["LONGITUDE"]).strip() != ""
        else "",
        axis=1
    )

    tabs = sorted(df["TAB"].dropna().unique())
    data = {}

    for tab in tabs:
        tab_df = df[df["TAB"] == tab]

        if tab in TABS_SITE_ONLY:
            data[tab] = {
                "SITE": {
                    site: tab_df[tab_df["SITE"] == site].to_dict("records")
                    for site in sorted(tab_df["SITE"].dropna().unique())
                }
            }
        else:
            data[tab] = {
                "BRANCH": {
                    b: tab_df[tab_df["BRANCH"] == b].to_dict("records")
                    for b in sorted(tab_df["BRANCH"].dropna().unique())
                },
                "CONTRATA": {
                    c: tab_df[tab_df["CONTRATA"] == c].to_dict("records")
                    for c in sorted(tab_df["CONTRATA"].dropna().unique())
                }
            }

    return render_template("index.html", tabs=tabs, data=data)

if __name__ == "__main__":
    app.run(debug=True)
