from flask import Flask, request

app = Flask(__name__)

@app.route("/")
def home():
    return "Fastlane callback server is running."

@app.route("/callback")
def callback():
    code = request.args.get("code")
    state = request.args.get("state")

    if code:
        return f"""
        <h1>Fastlane Authorization Received</h1>
        <p>Authorization code received successfully.</p>
        <p>State: {state}</p>
        """
    else:
        return """
        <h1>Fastlane Callback</h1>
        <p>No authorization code was received.</p>
        """

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
