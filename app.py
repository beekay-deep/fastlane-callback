from flask import Flask, request
import os
import time
import hmac
import hashlib
import urllib.parse
import urllib.request
import json

app = Flask(__name__)

API_URL = "https://api-sg.aliexpress.com/rest/auth/token/create"
API_NAME = "/auth/token/create"


def generate_sign(params, app_secret):
    # Sort parameter names in ASCII order
    sorted_keys = sorted(params.keys())

    # Build the string to sign
    sign_string = API_NAME

    for key in sorted_keys:
        value = params[key]
        sign_string += key + value

    # HMAC-SHA256 using the App Secret
    digest = hmac.new(
        app_secret.encode("utf-8"),
        sign_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest().upper()

    return digest


@app.route("/")
def home():
    return "Fastlane callback server is running."


@app.route("/callback")
def callback():
    code = request.args.get("code")

    if not code:
        return """
        <h1>Fastlane Callback</h1>
        <p>No authorization code was received.</p>
        """

    app_key = os.environ.get("ALIEXPRESS_APP_KEY")
    app_secret = os.environ.get("ALIEXPRESS_APP_SECRET")

    if not app_key or not app_secret:
        return """
        <h1>Fastlane Error</h1>
        <p>AliExpress credentials are not configured.</p>
        """, 500

    timestamp = str(int(time.time() * 1000))

    params = {
        "app_key": app_key,
        "code": code,
        "sign_method": "sha256",
        "timestamp": timestamp
    }

    sign = generate_sign(params, app_secret)
    params["sign"] = sign

    query_string = urllib.parse.urlencode(params)
    token_url = API_URL + "?" + query_string

    try:
        with urllib.request.urlopen(token_url, timeout=30) as response:
            response_body = response.read().decode("utf-8")

        token_data = json.loads(response_body)

        # Do not display access or refresh tokens in the browser.
        return """
        <h1>Fastlane Authorization Successful</h1>
        <p>AliExpress authorization code was exchanged successfully.</p>
        <p>Token response received from AliExpress.</p>
        """

    except Exception as error:
        print("AliExpress token request failed:", str(error))

        return """
        <h1>Fastlane Token Error</h1>
        <p>Fastlane received the authorization code, but the token request failed.</p>
        """, 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
