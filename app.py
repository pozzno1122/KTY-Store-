from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from bakong_khqr import KHQR
import requests
import hashlib
import hmac
import time
import json
import os

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# ការកំណត់ Bakong & Telegram Bot
BAKONG_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJkYXRhIjp7ImlkIjoiYzYxMWEyYTY2YzUxNDNlNSJ9LCJpYXQiOjE3ODkzMTA4MzMsImV4cCI6MTc5NzA4NjgzM30.TId975LLnYAV3D4BUuJJWxuRU_A4dyyVW28lxNEwwYs"
BAKONG_ID = "topup_kty@bkrt"

TG_BOT_TOKEN = "8681603461:AAHTBdVpAVAMxaDF7pZfiSwn9SPrN6w7kqM"
TG_GROUP_ID = "-1005852775918"
ADMIN_USERNAME = "ktyofficial169"

khqr = KHQR(BAKONG_TOKEN)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, 'store_data.json')

def send_telegram_group(text):
    try:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": TG_GROUP_ID,
            "text": text,
            "parse_mode": "HTML"
        }, timeout=5)
    except Exception as e:
        print("Telegram Error:", e)

def verify_telegram_auth(auth_data):
    check_hash = auth_data.get('hash')
    if not check_hash:
        return False
    data_check_arr = []
    for key, value in sorted(auth_data.items()):
        if key != 'hash' and value is not None:
            data_check_arr.append(f"{key}={value}")
    data_check_string = "\n".join(data_check_arr)
    secret_key = hashlib.sha256(TG_BOT_TOKEN.encode()).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return calculated_hash == check_hash

DEFAULT_DATA = {
    "banners": [
        "https://images.unsplash.com/photo-1542751371-adc38448a05e?auto=format&fit=crop&w=1280&q=80",
        "https://images.unsplash.com/photo-1511512578047-dfb367046420?auto=format&fit=crop&w=1280&q=80"
    ],
    "games": [
        {
            "id": "game_1",
            "name": "Roblox",
            "image": "https://upload.wikimedia.org/wikipedia/commons/thumb/3/3a/Roblox_player_icon_black.svg/512px-Roblox_player_icon_black.svg.png",
            "input1_enabled": True,
            "input1_label": "Roblox Username",
            "input1_placeholder": "បញ្ចូលឈ្មោះគណនី Roblox...",
            "input2_enabled": False,
            "input2_label": "",
            "input2_placeholder": "",
            "input_note": "⚠️ សូមពិនិត្យ Username ឱ្យបានត្រឹមត្រូវ មុននឹងធ្វើការទូទាត់ប្រាក់។"
        }
    ],
    "items": [
        {
            "id": "item_1",
            "game_id": "game_1",
            "name": "80 Robux",
            "price": 1.00,
            "image": "https://upload.wikimedia.org/wikipedia/commons/c/c7/Robux_2019_Logo_gold.svg"
        }
    ],
    "users": {},
    "orders": []
}

def load_data():
    if not os.path.exists(DATA_FILE):
        save_data(DEFAULT_DATA)
        return DEFAULT_DATA
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        d = json.load(f)
        d.setdefault("users", {})
        d.setdefault("orders", [])
        return d

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@app.route('/')
def home():
    return send_file(os.path.join(BASE_DIR, 'index.html'))

@app.route('/api/store', methods=['GET'])
def get_store():
    d = load_data()
    return jsonify({
        "banners": d["banners"],
        "games": d["games"],
        "items": d["items"]
    })

@app.route('/api/auth/telegram', methods=['POST'])
def auth_telegram():
    auth_data = request.get_json(silent=True) or {}
    if not verify_telegram_auth(auth_data):
        return jsonify({"success": False, "error": "ការផ្ទៀងផ្ទាត់គណនី Telegram មិនត្រឹមត្រូវ!"}), 401

    tg_id = str(auth_data.get("id"))
    username = auth_data.get("username", "")
    first_name = auth_data.get("first_name", "User")
    last_name = auth_data.get("last_name", "")
    full_name = f"{first_name} {last_name}".strip()
    photo_url = auth_data.get("photo_url", "")

    d = load_data()
    is_new = tg_id not in d["users"]
    d["users"][tg_id] = {
        "id": tg_id,
        "username": username,
        "first_name": full_name,
        "photo_url": photo_url,
        "joined_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    save_data(d)

    if is_new:
        msg = (
            f"🆕 <b>សមាជិកថ្មីទើបចុះឈ្មោះលើ Website!</b>\n"
            f"👤 ឈ្មោះ៖ {full_name}\n"
            f"🔗 Username៖ @{username if username else 'គ្មាន'}\n"
            f"🆔 Telegram ID៖ <code>{tg_id}</code>"
        )
        send_telegram_group(msg)

    return jsonify({"success": True, "user": d["users"][tg_id]})

# ទាញយកប្រវត្តិការទិញរបស់អតិថិជនម្នាក់ៗ
@app.route('/api/orders/history', methods=['POST'])
def get_order_history():
    payload = request.get_json(silent=True) or {}
    tg_id = str(payload.get("tg_id", ""))
    d = load_data()
    user_orders = [o for o in d["orders"] if str(o.get("tg_id")) == tg_id]
    return jsonify({"success": True, "orders": list(reversed(user_orders))})

# ទាញយកប្រវត្តិការទិញទាំងអស់សម្រាប់ Admin (@ktyofficial169)
@app.route('/api/admin/orders', methods=['POST'])
def get_all_orders_admin():
    payload = request.get_json(silent=True) or {}
    tg_id = str(payload.get("tg_id", ""))
    d = load_data()
    user = d["users"].get(tg_id)

    if not user or user.get("username", "").lower() != ADMIN_USERNAME:
        return jsonify({"success": False, "error": "គ្មានសិទ្ធិមើលទិន្នន័យនេះទេ!"}), 403

    return jsonify({"success": True, "orders": list(reversed(d["orders"]))})

@app.route('/api/store/save', methods=['POST'])
def update_store():
    payload = request.get_json(silent=True) or {}
    tg_id = str(payload.get("tg_id", ""))
    d = load_data()
    user = d["users"].get(tg_id)

    if not user or user.get("username", "").lower() != ADMIN_USERNAME:
        return jsonify({"success": False, "error": "គ្មានសិទ្ធិគ្រប់គ្រងទេ!"}), 403

    new_data = payload.get("data")
    if new_data:
        d["banners"] = new_data.get("banners", d["banners"])
        d["games"] = new_data.get("games", d["games"])
        d["items"] = new_data.get("items", d["items"])
        save_data(d)
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Invalid data"}), 400

# បង្កើត KHQR (អនុញ្ញាតទាំងអ្នកចុះឈ្មោះ និងភ្ញៀវទូទៅដែលមិនទាន់ចុះឈ្មោះ)
@app.route('/api/create-order', methods=['POST'])
def create_order():
    data = request.get_json(silent=True) or {}
    tg_id = str(data.get("tg_id", "")).strip()
    d = load_data()
    user = d["users"].get(tg_id) if tg_id else None

    item_name = str(data.get("item_name", "Game Item")).strip()
    game_name = str(data.get("game_name", "Game")).strip()
    player_info = str(data.get("player_info", "")).strip()
    price_usd = float(data.get("price", 0))

    if price_usd <= 0:
        return jsonify({"success": False, "error": "តម្លៃមិនត្រឹមត្រូវ!"}), 400

    try:
        bill_no = f"KTY-{int(time.time())}"
        qr_string = khqr.create_qr(
            account_id=BAKONG_ID,
            merchant_name="KTY TOPUP STORE",
            merchant_city="Phnom Penh",
            amount=round(price_usd, 2),
            currency="USD",
            store_label=game_name[:15],
            phone_number="855979556757",
            bill_number=bill_no,
            terminal_label=player_info[:15] if player_info else "Customer",
            static=False
        )
        md5_hash = khqr.generate_md5(qr_string)

        order_record = {
            "bill_number": bill_no,
            "md5": md5_hash,
            "tg_id": tg_id if user else "GUEST",
            "tg_username": user.get("username", "") if user else "",
            "tg_name": user.get("first_name", "ភ្ញៀវទូទៅ (Guest)") if user else "ភ្ញៀវទូទៅ (Guest)",
            "game_name": game_name,
            "item_name": item_name,
            "player_info": player_info,
            "amount": round(price_usd, 2),
            "status": "PENDING",
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        d["orders"].append(order_record)
        save_data(d)

        return jsonify({
            "success": True,
            "qr_string": qr_string,
            "md5": md5_hash,
            "amount": round(price_usd, 2),
            "bill_number": bill_no,
            "created_at": order_record["created_at"]
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ផ្ទៀងផ្ទាត់ការបង់ប្រាក់ស្វ័យប្រវត្តិ និងផ្ញើសារចូល Telegram Group
@app.route('/api/check-payment', methods=['POST'])
def check_payment():
    data = request.get_json(silent=True) or {}
    md5_hash = data.get("md5")
    if not md5_hash:
        return jsonify({"success": False, "error": "Missing MD5"}), 400

    try:
        status = khqr.check_payment(md5_hash)
        if status == "PAID":
            d = load_data()
            for o in d["orders"]:
                if o["md5"] == md5_hash:
                    if o["status"] != "PAID":
                        o["status"] = "PAID"
                        o["paid_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                        save_data(d)

                        if o["tg_id"] == "GUEST":
                            buyer_text = "ភ្ញៀវទូទៅ (មិនបានចុះឈ្មោះ)"
                        else:
                            tg_tag = f"@{o['tg_username']}" if o.get("tg_username") else o.get("tg_name")
                            buyer_text = f"{tg_tag} (<code>{o['tg_id']}</code>)"

                        msg = (
                            f"💰 <b>មានការបញ្ជាទិញថ្មី (PAID ✅)</b>\n"
                            f"━━━━━━━━━━━━━━━━━━\n"
                            f"🧾 វិក្កយបត្រ៖ <code>{o['bill_number']}</code>\n"
                            f"🎮 ហ្គេម៖ <b>{o['game_name']}</b>\n"
                            f"💎 កញ្ចប់ Item៖ <b>{o['item_name']}</b>\n"
                            f"🆔 គណនីហ្គេម៖ <code>{o['player_info']}</code>\n"
                            f"💵 ទឹកប្រាក់៖ <b>${o['amount']:.2f}</b>\n"
                            f"👤 អ្នកទិញ៖ {buyer_text}\n"
                            f"⏰ ម៉ោងបង់ប្រាក់៖ {o['paid_at']}"
                        )
                        send_telegram_group(msg)
                    return jsonify({"success": True, "status": "PAID", "order": o})

        return jsonify({"success": True, "status": status})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
