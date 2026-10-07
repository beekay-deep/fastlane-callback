from flask import Flask, request
import os
import time
import hmac
import hashlib
import urllib.parse
import urllib.request
import json
import psycopg2
from datetime import datetime, timezone, timedelta
app = Flask(__name__)

API_URL = "https://api-sg.aliexpress.com/rest/auth/token/create"
API_NAME = "/auth/token/create"


def generate_sign(params, app_secret):
    sorted_keys = sorted(params.keys())

    sign_string = ""

    for key in sorted_keys:
        sign_string += key + params[key]

    digest = hmac.new(
        app_secret.encode("utf-8"),
        sign_string.encode("utf-8"),
        hashlib.md5
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
            CREATE TABLE IF NOT EXISTS imported_products (
                id SERIAL PRIMARY KEY,
                item_id TEXT UNIQUE NOT NULL,
                title TEXT,
                image_url TEXT,
                price TEXT,
                rating TEXT,
                orders TEXT,
                item_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

@app.route("/status")
def status():
    try:
        connection = get_database_connection()
        cursor = connection.cursor()

        cursor.execute("SELECT COUNT(*) FROM aliexpress_tokens")
        count = cursor.fetchone()[0]

        cursor.close()
        connection.close()

        if count > 0:
            return "Fastlane status: token record exists in database."
        else:
            return "Fastlane status: no token record found."

    except Exception as error:
        print("Status check failed:", str(error))
        return "Fastlane status: database check failed.", 500

@app.route("/api-test")
def api_test():
    try:
        connection = get_database_connection()
        cursor = connection.cursor()

        cursor.execute("""
            SELECT access_token
            FROM aliexpress_tokens
            ORDER BY updated_at DESC
            LIMIT 1
        """)

        row = cursor.fetchone()

        cursor.close()
        connection.close()

        if not row:
            return "Fastlane API test: no access token found.", 500

        return "Fastlane API test: stored access token found."

    except Exception as error:
        print("API test failed:", str(error))
@app.route("/product-test")
def product_test():
    try:
        connection = get_database_connection()
        cursor = connection.cursor()

        cursor.execute("""
            SELECT access_token
            FROM aliexpress_tokens
            ORDER BY updated_at DESC
            LIMIT 1
        """)

        row = cursor.fetchone()

        cursor.close()
        connection.close()

        if not row:
            return "Product test: no access token found.", 500

        access_token = row[0]

        app_key = os.environ.get("ALIEXPRESS_APP_KEY")
        app_secret = os.environ.get("ALIEXPRESS_APP_SECRET")

        if not app_key or not app_secret:
            return "Product test: AliExpress credentials are not configured.", 500

        api_name = "aliexpress.ds.product.get"

        timestamp = str(int(time.time() * 1000))

        print("AliExpress timestamp:", timestamp)

        params = {
            "app_key": app_key,
            "access_token": access_token,
            "method": api_name,
            "product_id": "1005011756447612",
            "ship_to_country": "ZA",
            "target_currency": "ZAR",
            "target_language": "en",
            "sign_method": "sha256",
            "timestamp": timestamp
        }

        sorted_keys = sorted(params.keys())

        sign_string = ""

        for key in sorted_keys:
            sign_string += key + params[key]

        digest = hmac.new(
            app_secret.encode("utf-8"),
            sign_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest().upper()

        params["sign"] = digest

        api_url = "https://api-sg.aliexpress.com/sync"

        query_string = urllib.parse.urlencode(params)

        request = urllib.request.Request(
            api_url + "?" + query_string,
            method="GET"
        )

        with urllib.request.urlopen(request, timeout=30) as response:
            response_body = response.read().decode("utf-8")

        data = json.loads(response_body)

        return "<pre>" + json.dumps(data, indent=2) + "</pre>"

    except Exception as error:
        print("Product API test failed:", str(error))
        return "Product API test failed. Check Render logs.", 500
@app.route("/import-product", methods=["POST"])
def import_product():
    try:
        item_id = request.form.get("item_id", "")
        title = request.form.get("title", "")
        image_url = request.form.get("image_url", "")
        price = request.form.get("price", "")
        rating = request.form.get("rating", "")
        orders = request.form.get("orders", "")
        item_url = request.form.get("item_url", "")

        if not item_id:
            return "Import failed: Product ID is missing.", 400

        connection = get_database_connection()
        cursor = connection.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS imported_products (
                id SERIAL PRIMARY KEY,
                item_id TEXT UNIQUE NOT NULL,
                title TEXT,
                image_url TEXT,
                price TEXT,
                rating TEXT,
                orders TEXT,
                item_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            INSERT INTO imported_products (
                item_id,
                title,
                image_url,
                price,
                rating,
                orders,
                item_url
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (item_id)
            DO UPDATE SET
                title = EXCLUDED.title,
                image_url = EXCLUDED.image_url,
                price = EXCLUDED.price,
                rating = EXCLUDED.rating,
                orders = EXCLUDED.orders,
                item_url = EXCLUDED.item_url
        """, (
            item_id,
            title,
            image_url,
            price,
            rating,
            orders,
            item_url
        ))

        connection.commit()

        cursor.close()
        connection.close()

        return f"""
        <h1>Product Imported Successfully</h1>

        <p><strong>{title}</strong></p>

        <p>Product ID: {item_id}</p>

        <p>Fastlane has saved this product.</p>

        <p>
            <a href="/product-search">
                Back to Product Search
            </a>
        </p>
        """

    except Exception as error:
        print("Product import failed:", str(error))

        return (
            "Product import failed. Check Render logs.",
            500
        )
@app.route("/imported-products")
def imported_products():
    try:
        connection = get_database_connection()
        cursor = connection.cursor()

        cursor.execute("""
            SELECT
                item_id,
                title,
                image_url,
                price,
                rating,
                orders,
                item_url
            FROM imported_products
            ORDER BY created_at DESC
        """)

        products = cursor.fetchall()

        cursor.close()
        connection.close()

        product_cards = ""

        for product in products:
            item_id, title, image_url, price, rating, orders, item_url = product

            product_cards += f"""
            <div class="product-card">

<a href="{image_url}" target="_blank">
    <img
        class="product-image"
        src="{image_url}"
        alt="{title}"
    >
</a>

                <h2>{title}</h2>

                <p>Price: {price}</p>

                <p>Rating: {rating}</p>

                <p>Orders: {orders}</p>

                <p>Product ID: {item_id}</p>

                <a href="{item_url}" target="_blank">
                    View on AliExpress
                </a>

            </div>
            """

        if not product_cards:
            product_cards = """
            <p>No products have been imported yet.</p>
            """

        return f"""
        <!DOCTYPE html>
        <html>

        <head>

            <title>Fastlane - Imported Products</title>

 <style>

    body {{
        font-family: Arial, sans-serif;
        background: #f4f6f8;
        margin: 0;
        padding: 30px;
    }}

    .header {{
        max-width: 1200px;
        margin: 0 auto 30px auto;
    }}

    .header h1 {{
        margin: 0;
        font-size: 32px;
    }}

    .header p {{
        color: #666;
        margin-top: 8px;
    }}

    .products {{
        max-width: 1200px;
        margin: auto;
        display: grid;
        grid-template-columns:
            repeat(auto-fit, minmax(280px, 1fr));
        gap: 24px;
    }}

    .product-card {{
        background: white;
        border-radius: 14px;
        overflow: hidden;
        box-shadow: 0 3px 12px rgba(0,0,0,0.08);
    }}

    .product-image {{
        width: 100%;
        height: 280px;
        object-fit: contain;
        background: white;
        display: block;
        margin: 0 auto;
    }}
    }}

    .product-info {{
        padding: 20px;
    }}

    .product-title {{
        font-size: 18px;
        line-height: 1.4;
        margin: 0 0 15px 0;
    }}

    .price {{
        font-size: 24px;
        font-weight: bold;
        margin-bottom: 12px;
    }}

    .stats {{
        display: flex;
        gap: 15px;
        margin-bottom: 18px;
        color: #555;
        font-size: 14px;
    }}

    .product-id {{
        font-size: 12px;
        color: #888;
        margin-bottom: 15px;
    }}

    .view-button {{
        display: block;
        text-align: center;
        padding: 12px;
        background: #007bff;
        color: white;
        text-decoration: none;
        border-radius: 8px;
    }}

    .view-button:hover {{
        opacity: 0.9;
    }}

    @media (max-width: 600px) {{

        body {{
            padding: 15px;
        }}

        .header h1 {{
            font-size: 26px;
        }}

    }}
    .image-lightbox {{
        display: none;
        position: fixed;
        z-index: 9999;
        left: 0;
        top: 0;
        width: 100%;
        height: 100%;
        background: rgba(0, 0, 0, 0.85);
        align-items: center;
        justify-content: center;
        padding: 20px;
        box-sizing: border-box;
    }}

    .image-lightbox img {{
        max-width: 95%;
        max-height: 90%;
        object-fit: contain;
        background: white;
        border-radius: 8px;
    }}

    .lightbox-close {{
        position: absolute;
        top: 20px;
        right: 30px;
        color: white;
        font-size: 40px;
        font-weight: bold;
        cursor: pointer;
        line-height: 1;
    }}
</style>

        </head>

<body>

    <div
        id="imageLightbox"
        class="image-lightbox"
    >
        <span
            class="lightbox-close"
            onclick="closeImageLightbox()"
        >
            &times;
        </span>

        <img
            id="lightboxImage"
            src=""
            alt="Product image"
        >
    </div>
            <h1>Fastlane - Imported Products</h1>

            <div class="products">
                {product_cards}
            </div>

        </body>

        </html>
        """

    except Exception as error:
        print("Imported products error:", str(error))

        return (
            "Could not load imported products. Check Render logs.",
            500
        )


 

 
@app.route("/product-search")
def product_search():
    try:
        keyword = request.args.get("keyword", "wall art")

        connection = get_database_connection()
        cursor = connection.cursor()

        cursor.execute("""
            SELECT access_token
            FROM aliexpress_tokens
            ORDER BY updated_at DESC
            LIMIT 1
        """)

        row = cursor.fetchone()

        cursor.close()
        connection.close()

        if not row:
            return "Product search: no access token found.", 500

        access_token = row[0]

        app_key = os.environ.get("ALIEXPRESS_APP_KEY")
        app_secret = os.environ.get("ALIEXPRESS_APP_SECRET")

        if not app_key or not app_secret:
            return "Product search: AliExpress credentials are not configured.", 500

        api_name = "aliexpress.ds.text.search"

        timestamp = str(int(time.time() * 1000))

        params = {
            "app_key": app_key,
            "access_token": access_token,
            "method": api_name,
            "keyWord": keyword,
            "local": "en_US",
            "countryCode": "ZA",
            "sortBy": "orders,desc",
            "pageSize": "20",
            "pageIndex": "1",
            "currency": "ZAR",
            "sign_method": "sha256",
            "timestamp": timestamp
        }

        sorted_keys = sorted(params.keys())

        sign_string = ""

        for key in sorted_keys:
            sign_string += key + params[key]

        digest = hmac.new(
            app_secret.encode("utf-8"),
            sign_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest().upper()

        params["sign"] = digest

        api_url = "https://api-sg.aliexpress.com/sync"

        query_string = urllib.parse.urlencode(params)
        request_url = api_url + "?" + query_string

        with urllib.request.urlopen(request_url, timeout=30) as response:
            response_body = response.read().decode("utf-8")

        data = json.loads(response_body)

        response_data = data.get(
            "aliexpress_ds_text_search_response",
            {}
        )

        response_code = response_data.get("code")

        if response_code != "00":
            return """
            <h1>Fastlane Product Search Error</h1>
            <p>AliExpress returned an error.</p>
            <pre>{}</pre>
            """.format(json.dumps(data, indent=2)), 500

        products_data = response_data.get("data", {})
        products = products_data.get("products", {})
        product_list = products.get(
            "selection_search_product",
            []
        )

        product_cards = ""

        for product in product_list:
            title = product.get(
                "title",
                "No title available"
            )

            image = product.get(
                "itemMainPic",
                ""
            )

            price = product.get(
                "salePriceFormat",
                "Price unavailable"
            )

            rating = product.get(
                "evaluateRate",
                "N/A"
            )

            orders = product.get(
                "orders",
                "N/A"
            )

            item_url = product.get(
                "itemUrl",
                ""
            )

            item_id = product.get(
                "itemId",
                ""
            )

            if item_url.startswith("//"):
                item_url = "https:" + item_url

            product_cards += f"""
            <div class="product-card">

                <img
                    src="{image}"
                    alt="{title}"
                    class="product-image"
                >

                <div class="product-info">

                    <h3>{title}</h3>

                    <p class="rating">
                        ⭐ {rating}% &nbsp; | &nbsp; 🛒 {orders} orders
                    </p>

                    <p class="price">
                        {price}
                    </p>

                    <p class="product-id">
                        Product ID: {item_id}
                    </p>

                    <div class="buttons">

                        <a
                            href="{item_url}"
                            target="_blank"
                            class="view-button"
                        >
                            View on AliExpress
                        </a>

                         <form
    method="POST"
    action="/import-product"
    style="flex: 1;"
>

    <input
        type="hidden"
        name="item_id"
        value="{item_id}"
    >

    <input
        type="hidden"
        name="title"
        value="{title}"
    >

    <input
        type="hidden"
        name="image_url"
        value="{image}"
    >

    <input
        type="hidden"
        name="price"
        value="{price}"
    >

    <input
        type="hidden"
        name="rating"
        value="{rating}"
    >

    <input
        type="hidden"
        name="orders"
        value="{orders}"
    >

    <input
        type="hidden"
        name="item_url"
        value="{item_url}"
    >

    <button
        type="submit"
        class="import-button"
        style="width: 100%;"
    >
        Import Product
    </button>

</form>

                    </div>

                </div>

            </div>
            """

        return f"""
        <!DOCTYPE html>

        <html>

        <head>

            <title>Fastlane Product Search</title>

            <meta
                name="viewport"
                content="width=device-width, initial-scale=1"
            >

            <style>

                body {{
                    margin: 0;
                    font-family: Arial, sans-serif;
                    background: #f5f7fb;
                    color: #222;
                }}

                .header {{
                    background: #111827;
                    color: white;
                    padding: 25px;
                }}

                .header h1 {{
                    margin: 0;
                }}

                .container {{
                    max-width: 1200px;
                    margin: auto;
                    padding: 25px;
                }}

                .search-box {{
                    background: white;
                    padding: 20px;
                    border-radius: 12px;
                    margin-bottom: 25px;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
                }}

                .search-box form {{
                    display: flex;
                    gap: 10px;
                }}

                .search-box input {{
                    flex: 1;
                    padding: 14px;
                    border: 1px solid #ddd;
                    border-radius: 8px;
                    font-size: 16px;
                }}

                .search-box button {{
                    padding: 14px 22px;
                    border: none;
                    border-radius: 8px;
                    background: #2563eb;
                    color: white;
                    font-size: 16px;
                    cursor: pointer;
                }}

                .search-box button:hover {{
                    background: #1d4ed8;
                }}

                .results {{
                    display: grid;
                    grid-template-columns:
                        repeat(auto-fit, minmax(280px, 1fr));
                    gap: 20px;
                }}

                .product-card {{
                    background: white;
                    border-radius: 12px;
                    overflow: hidden;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
                }}

                .product-image {{
                    width: 100%;
                    height: 260px;
                    object-fit: cover;
                    background: #eee;
                }}

                .product-info {{
                    padding: 18px;
                }}

                .product-info h3 {{
                    font-size: 16px;
                    line-height: 1.4;
                    margin-top: 0;
                }}

                .rating {{
                    color: #555;
                    font-size: 14px;
                }}

                .price {{
                    font-size: 24px;
                    font-weight: bold;
                    margin: 12px 0;
                }}

                .product-id {{
                    color: #888;
                    font-size: 12px;
                }}

                .buttons {{
                    display: flex;
                    gap: 8px;
                    margin-top: 15px;
                }}

                .view-button,
                .import-button {{
                    flex: 1;
                    padding: 11px;
                    border-radius: 7px;
                    text-align: center;
                    text-decoration: none;
                    font-size: 13px;
                    cursor: pointer;
                }}

                .view-button {{
                    background: #e5e7eb;
                    color: #111827;
                }}

                .import-button {{
                    background: #2563eb;
                    color: white;
                    border: none;
                }}

                .view-button:hover {{
                    background: #d1d5db;
                }}

                .import-button:hover {{
                    background: #1d4ed8;
                }}

            </style>

        </head>

        <body>

            <div class="header">
                <h1>Fastlane</h1>
                <p>AliExpress Dropshipping Product Search</p>
            </div>

            <div class="container">

                <div class="search-box">

                    <form
                        method="GET"
                        action="/product-search"
                    >

                        <input
                            type="text"
                            name="keyword"
                            value="{keyword}"
                            placeholder="Search AliExpress products..."
                        >

                        <button type="submit">
                            Search
                        </button>

                    </form>

                </div>

                <h2>
                    Search results for:
                    "{keyword}"
                </h2>

                <div class="results">

                    {product_cards}

                </div>

            </div>

        </body>

        </html>
        """

    except Exception as error:
        print(
            "Product search failed:",
            str(error)
        )

        return (
            "Product search failed. Check Render logs.",
            500
        )

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
