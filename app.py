from flask import Flask, request, jsonify, send_file, Response
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
            "image": "https://cdn-icons-png.flaticon.com/512/686/686589.png",
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
            "image": "https://cdn-icons-png.flaticon.com/512/616/616490.png"
        }
    ],
    "accounts": [],
    "users": {},
    "orders": []
}

def load_data():
    if not os.path.exists(DATA_FILE):
        save_data(DEFAULT_DATA)
        return DEFAULT_DATA
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        d = json.load(f)
        d.setdefault("accounts", [])
        d.setdefault("users", {})
        d.setdefault("orders", [])
        return d

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@app.route('/')
def home():
    return send_file(os.path.join(BASE_DIR, 'index.html'))

# ទាញយកទិន្នន័យហាង (លាក់ព័ត៌មានសម្ងាត់គណនីហ្គេមមិនឱ្យភ្ញៀវឃើញមុនទិញ)
@app.route('/api/store', methods=['GET'])
def get_store():
    d = load_data()
    safe_accounts = []
    for acc in d.get("accounts", []):
        safe_accounts.append({
            "id": acc["id"],
            "title": acc["title"],
            "game_name": acc["game_name"],
            "price": acc["price"],
            "stock": acc["stock"],
            "description": acc.get("description", ""),
            "images": acc.get("images", [])
        })
    return jsonify({
        "banners": d["banners"],
        "games": d["games"],
        "items": d["items"],
        "accounts": safe_accounts
    })

# Upload រូបភាពទៅផ្ទុកនៅលើ Telegram Cloud ផ្ទាល់ (ជៀសវាងគាំង Server)
@app.route('/api/upload-tg-image', methods=['POST'])
def upload_tg_image():
    tg_id = str(request.form.get("tg_id", ""))
    d = load_data()
    user = d["users"].get(tg_id)

    if not user or user.get("username", "").lower() != ADMIN_USERNAME:
        return jsonify({"success": False, "error": "គ្មានសិទ្ធិ Upload រូបភាពទេ!"}), 403

    if 'photo' not in request.files:
        return jsonify({"success": False, "error": "មិនមានរូបភាពទេ!"}), 400

    photo_file = request.files['photo']
    try:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendPhoto"
        files = {'photo': (photo_file.filename, photo_file.stream, photo_file.mimetype)}
        data = {
            'chat_id': TG_GROUP_ID,
            'caption': '🖼️ รូបភាពស្តុកគណនីហ្គេម (Telegram Cloud Storage)',
            'disable_notification': True
        }
        res = requests.post(url, files=files, data=data, timeout=20).json()
        if res.get("ok"):
            # យក file_id ដែលមានទំហំធំជាងគេ
            file_id = res["result"]["photo"][-1]["file_id"]
            return jsonify({"success": True, "file_id": file_id})
        else:
            return jsonify({"success": False, "error": res.get("description", "Telegram Upload Failed")}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# បង្ហាញរូបភាពពី Telegram Cloud ដោយប្រើ file_id
@app.route('/api/tg-image/<file_id>', methods=['GET'])
def serve_tg_image(file_id):
    try:
        info_res = requests.get(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getFile?file_id={file_id}", timeout=10).json()
        if not info_res.get("ok"):
            return "Image not found", 404
        file_path = info_res["result"]["file_path"]
        file_url = f"https://api.telegram.org/file/bot{TG_BOT_TOKEN}/{file_path}"
        img_res = requests.get(file_url, timeout=15)
        return Response(img_res.content, mimetype=img_res.headers.get('Content-Type', 'image/jpeg'))
    except Exception as e:
        return str(e), 500

# ទាញយកទិន្នន័យគណនីពេញលេញ (រួមទាំង Gmail/Pass) សម្រាប់តែ Admin ពេលចុចកែ
@app.route('/api/admin/accounts', methods=['POST'])
def get_admin_accounts():
    payload = request.get_json(silent=True) or {}
    tg_id = str(payload.get("tg_id", ""))
    d = load_data()
    user = d["users"].get(tg_id)
    if not user or user.get("username", "").lower() != ADMIN_USERNAME:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
    return jsonify({"success": True, "accounts": d.get("accounts", [])})

# បន្ថែម ឬ កែប្រែ គណនីហ្គេមសម្រាប់លក់
@app.route('/api/admin/account/save', methods=['POST'])
def save_admin_account():
    payload = request.get_json(silent=True) or {}
    tg_id = str(payload.get("tg_id", ""))
    d = load_data()
    user = d["users"].get(tg_id)
    if not user or user.get("username", "").lower() != ADMIN_USERNAME:
        return jsonify({"success": False, "error": "គ្មានសិទ្ធិគ្រប់គ្រងទេ!"}), 403

    acc_data = payload.get("account")
    if not acc_data:
        return jsonify({"success": False, "error": "ទិន្នន័យមិនត្រឹមត្រូវ"}), 400

    acc_id = acc_data.get("id")
    existing_idx = next((i for i, a in enumerate(d["accounts"]) if a["id"] == acc_id), -1)

    new_acc = {
        "id": acc_id or f"acc_{int(time.time())}",
        "title": str(acc_data.get("title", "")).strip(),
        "game_name": str(acc_data.get("game_name", "")).strip(),
        "price": round(float(acc_data.get("price", 0)), 2),
        "stock": int(acc_data.get("stock", 1)),
        "description": str(acc_data.get("description", "")).strip(),
        "acc_login": str(acc_data.get("acc_login", "")).strip(),
        "acc_password": str(acc_data.get("acc_password", "")).strip(),
        "images": acc_data.get("images", [])[:10]
    }

    if existing_idx != -1:
        d["accounts"][existing_idx] = new_acc
    else:
        d["accounts"].append(new_acc)

    save_data(d)
    return jsonify({"success": True})

# លុបគណនីហ្គេម
@app.route('/api/admin/account/delete', methods=['POST'])
def delete_admin_account():
    payload = request.get_json(silent=True) or {}
    tg_id = str(payload.get("tg_id", ""))
    acc_id = payload.get("acc_id")
    d = load_data()
    user = d["users"].get(tg_id)
    if not user or user.get("username", "").lower() != ADMIN_USERNAME:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    d["accounts"] = [a for a in d["accounts"] if a["id"] != acc_id]
    save_data(d)
    return jsonify({"success": True})

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

@app.route('/api/orders/history', methods=['POST'])
def get_order_history():
    payload = request.get_json(silent=True) or {}
    tg_id = str(payload.get("tg_id", ""))
    d = load_data()
    user_orders = [o for o in d["orders"] if str(o.get("tg_id")) == tg_id]
    return jsonify({"success": True, "orders": list(reversed(user_orders))})

@app.route('/api/admin/orders', methods=['POST'])
def get_all_orders_admin():
    payload = request.get_json(silent=True) or {}
    tg_id = str(payload.get("tg_id", ""))
    d = load_data()
    user = d["users"].get(tg_id)
    if not user or user.get("username", "").lower() != ADMIN_USERNAME:
        return jsonify({"success": False, "error": "Unauthorized"}), 403
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

# បង្កើត KHQR (គាំទ្រទាំងការទិញ Item និងការទិញគណនីហ្គេម)
@app.route('/api/create-order', methods=['POST'])
def create_order():
    data = request.get_json(silent=True) or {}
    tg_id = str(data.get("tg_id", "")).strip()
    order_type = data.get("order_type", "ITEM") # "ITEM" ឬ "ACCOUNT"
    d = load_data()
    user = d["users"].get(tg_id) if tg_id else None

    if order_type == "ACCOUNT":
        acc_id = data.get("account_id")
        acc = next((a for a in d["accounts"] if a["id"] == acc_id), None)
        if not acc:
            return jsonify({"success": False, "error": "រកមិនឃើញគណនីហ្គេមនេះទេ!"}), 404
        if acc["stock"] <= 0:
            return jsonify({"success": False, "error": "គណនីហ្គេមនេះអស់ស្តុកហើយ!"}), 400

        game_name = acc["game_name"]
        item_name = acc["title"]
        player_info = "ទិញគណនីហ្គេម (Auto Delivery)"
        price_usd = float(acc["price"])
    else:
        acc_id = ""
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
            terminal_label=item_name[:15],
            static=False
        )
        md5_hash = khqr.generate_md5(qr_string)

        order_record = {
            "bill_number": bill_no,
            "md5": md5_hash,
            "order_type": order_type,
            "account_id": acc_id,
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
            "bill_number": bill_no
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ផ្ទៀងផ្ទាត់ការបង់ប្រាក់ + ប្រគល់គណនីហ្គេមភ្លាមៗ + ផ្ញើសារចូល Group
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

                        # បើជាការទិញគណនីហ្គេម ទាញយក Gmail/Pass និងកាត់ស្តុក
                        if o.get("order_type") == "ACCOUNT":
                            acc = next((a for a in d["accounts"] if a["id"] == o.get("account_id")), None)
                            if acc:
                                o["delivered_login"] = acc.get("acc_login", "")
                                o["delivered_password"] = acc.get("acc_password", "")
                                if acc["stock"] > 0:
                                    acc["stock"] -= 1

                        save_data(d)

                        if o["tg_id"] == "GUEST":
                            buyer_text = "ភ្ញៀវទូទៅ (Guest)"
                        else:
                            tg_tag = f"@{o['tg_username']}" if o.get("tg_username") else o.get("tg_name")
                            buyer_text = f"{tg_tag} (<code>{o['tg_id']}</code>)"

                        if o.get("order_type") == "ACCOUNT":
                            msg = (
                                f"🔐 <b>លក់គណនីហ្គេមជោគជ័យ (PAID ✅)</b>\n"
                                f"━━━━━━━━━━━━━━━━━━\n"
                                f"🧾 វិក្កយបត្រ៖ <code>{o['bill_number']}</code>\n"
                                f"🎮 ហ្គេម៖ <b>{o['game_name']}</b>\n"
                                f"🏷️ ឈ្មោះគណនី៖ <b>{o['item_name']}</b>\n"
                                f"💵 ទឹកប្រាក់៖ <b>${o['amount']:.2f}</b>\n"
                                f"👤 អ្នកទិញ៖ {buyer_text}\n"
                                f"📧 User/Gmail៖ <code>{o.get('delivered_login', '')}</code>\n"
                                f"🔑 Password៖ <code>{o.get('delivered_password', '')}</code>\n"
                                f"⏰ ម៉ោងបង់ប្រាក់៖ {o['paid_at']}"
                            )
                        else:
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
