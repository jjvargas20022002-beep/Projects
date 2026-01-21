from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return """
    <html>
        <head>
            <title>Mi Web</title>
            <style>
                body {
                    background: #0f172a;
                    color: #e5e7eb;
                    font-family: Arial;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                }
                h1 {
                    font-size: 3rem;
                }
            </style>
        </head>
        <body>
            <h1>Python corriendo en web 🚀</h1>
        </body>
    </html>
    """

# 🔵 IMPORTANTE: sin debug
if __name__ == "__main__":
    app.run()
