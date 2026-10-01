from flask import Flask, request
import os
import time
import hmac
import hashlib
import urllib.parse
import urllib.request
import json
import psycopg2

app = Flask(__name__)

API_URL = "https://api-sg.aliexpress.com/rest/auth/token/create"
API_NAME = "/auth/token/create"


def generate_sign(params, app_secret):
    sorted_keys = sorted(params.keys())

    sign_string = API_NAME

    for key in sorted_keys:
        sign_string += key + params[key]

    digest = hmac.new(
        app_secret.encode("utf-8"),
        sign_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest().upper()

    return digest


def get_database_connection():
    return psycopg2.connect(
        os.environ["DATABASE_URL"]
    )


def find_value(data, wanted_key):
    if isinstance(data, dict):
        if wanted_key in data:
            return data[wanted_key]

        for value in data.values():
            result = find_value(value, wanted_key)
            if result is not None:
                return result

    elif isinstance(data, list):
        for item in data:
            result = find_value(item, wanted_key)
            if result is not None:
                return result

    return None


def save_tokens(token_data):
    access_token = find_value(token_data, "access_token")
    refresh_token = find_value(token_data, "refresh_token")
    expires_in = find_value(token_data, "expires_in")
    refresh_expires_in = find_value(token_data, "refresh_expires_in")
    seller_id = find_value(token_data, "seller_id")
    account_id = find_value(token_data, "account_id")
    user_id = find_value(token_data, "user_id")

    if not access_token or not refresh_token:
        return False

    connection = get_database_connection()

    try:
        cursor = connection.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS aliexpress_tokens (
                id SERIAL PRIMARY KEY,
                access_token TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                expires_in BIGINT,
                refresh_expires_in BIGINT,
                seller_id TEXT,
                account_id TEXT,
                user_id TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            DELETE FROM aliexpress_tokens
        """)

        cursor.execute("""
            INSERT INTO aliexpress_tokens (
                access_token,
                refresh_token,
                expires_in,
                refresh_expires_in,
                seller_id,
                account_id,
                user_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            access_token,
            refresh_token,
            expires_in,
            refresh_expires_in,
            seller_id,
            account_id,
            user_id
        ))

        connection.commit()

    finally:
        cursor.close()
        connection.close()

    return True


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

    if not os.environ.get("DATABASE_URL"):
        return """
        <h1>Fastlane Error</h1>
        <p>Database connection is not configured.</p>
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

        saved = save_tokens(token_data)

        if not saved:
            return """
            <h1>Fastlane Token Error</h1>
            <p>AliExpress responded, but no usable tokens were received.</p>
            """, 500

        return """
        <h1>Fastlane Authorization Successful</h1>
        <p>AliExpress authorization was completed successfully.</p>
        <p>Your authorization tokens have been securely stored.</p>
        """

    except Exception as error:
        print("Fastlane error:", str(error))

        return """
        <h1>Fastlane Token Error</h1>
        <p>Fastlane received the authorization code, but could not complete the token process.</p>
        """, 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
