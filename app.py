from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS
from bakong_khqr import KHQR
import requests
import hashlib
import hmac
import time
import uuid
import json
import os

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# Bakong Token ថ្មី (មានសុពលភាពដល់ 31 Dec 2026) & គណនី ABA ទទួលប្រាក់ផ្ទាល់
BAKONG_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJkYXRhIjp7ImlkIjoiYTYwNGFhZjliNmRlNGMzNyJ9LCJpYXQiOjE3OTA5ODA1MzgsImV4cCI6MTc5ODc1NjUzOH0.JVGnd51f_4MWB3nUu_OwtEmeo9FjJgy9BypFytO053I"
ABA_ROUTING_ID = "abaakhppxxx@abaa"
ABA_ACCOUNT_NO = "010765908"
ABA_MERCHANT_DISPLAY_NAME = "KTY STORE"

TG_BOT_TOKEN = "8681603461:AAHTBdVpAVAMxaDF7pZfiSwn9SPrN6w7kqM"
TG_GROUP_ID = "-1005852775918"
ADMIN_USERNAME = "ktyofficial169"

khqr = KHQR(BAKONG_TOKEN)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, 'store_data.json')

DEFAULT_DATA = {
    "banners": [],
    "games": [],
    "items": [],
    "accounts": [],
    "users": {},
    "orders": [],
    "chats": {}
}

def crc16_ccitt(data: str) -> str:
    """គណនាកូដសុវត្ថិភាព CRC-16 សម្រាប់ KHQR"""
    crc = 0xFFFF
    for byte in data.encode('utf-8'):
        crc ^= (byte << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return f"{crc:04X}"

def build_aba_khqr(amount_usd: float, bill_no: str, nonce: str) -> str:
    """បង្កើត KHQR បាញ់ប្រាក់ចូលគណនី ABA (010765908) ដោយបង្ហាញឈ្មោះ KTY STORE"""
    raw_qr = khqr.create_qr(
        account_id=ABA_ROUTING_ID,
        merchant_name=ABA_MERCHANT_DISPLAY_NAME,
        merchant_city="Phnom Penh",
        amount=round(amount_usd, 2),
        currency="USD",
        store_label=f"KTY-{nonce}",
        phone_number="85510765908",
        bill_number=bill_no,
        terminal_label=f"T-{nonce}",
        static=False
    )
    # បញ្ចូលលេខគណនី ABA 010765908 ទៅក្នុង Tag 29 ឱ្យត្រូវតាមស្តង់ដារធនាគារ ABA
    base_tag29 = f"29{len(ABA_ROUTING_ID)+4:02d}00{len(ABA_ROUTING_ID):02d}{ABA_ROUTING_ID}"
    aba_subtags = (
        f"00{len(ABA_ROUTING_ID):02d}{ABA_ROUTING_ID}"
        f"01{len(ABA_ACCOUNT_NO):02d}{ABA_ACCOUNT_NO}"
        f"0208ABA Bank"
    )
    full_tag29 = f"29{len(aba_subtags):02d}{aba_subtags}"

    if base_tag29 in raw_qr and "6304" in raw_qr:
        updated_qr = raw_qr.replace(base_tag29, full_tag29, 1)
        qr_body = updated_qr.split("6304")[0] + "6304"
        return qr_body + crc16_ccitt(qr_body)
    return raw_qr

# ==================== ទាញយកទិន្នន័យចាស់ដែលអ្នកបានរៀបចំរួចរាល់ ====================
def load_initial_from_telegram_pinned():
    try:
        res = requests.get(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getChat?chat_id={TG_GROUP_ID}", timeout=8).json()
        if res.get("ok"):
            pinned = res["result"].get("pinned_message")
            if pinned and pinned.get("document"):
                file_id = pinned["document"]["file_id"]
                f_res = requests.get(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getFile?file_id={file_id}", timeout=8).json()
                if f_res.get("ok"):
                    file_path = f_res["result"]["file_path"]
                    raw = requests.get(f"https://api.telegram.org/file/bot{TG_BOT_TOKEN}/{file_path}", timeout=10).json()
                    if isinstance(raw, dict) and "games" in raw:
                        raw.setdefault("accounts", [])
                        raw.setdefault("users", {})
                        raw.setdefault("orders", [])
                        raw.setdefault("chats", {})
                        with open(DATA_FILE, 'w', encoding='utf-8') as f:
                            json.dump(raw, f, ensure_ascii=False, indent=2)
                        return raw
    except Exception as e:
        print("Initial load note:", e)
    return None

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                d = json.load(f)
                d.setdefault("accounts", [])
                d.setdefault("users", {})
                d.setdefault("orders", [])
                d.setdefault("chats", {})
                return d
        except Exception:
            pass
    cloud_data = load_initial_from_telegram_pinned()
    if cloud_data:
        return cloud_data
    save_data(DEFAULT_DATA)
    return DEFAULT_DATA

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

if not os.path.exists(DATA_FILE):
    load_initial_from_telegram_pinned()

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

@app.route('/')
def home():
    return send_file(os.path.join(BASE_DIR, 'index.html'))

# ==================== API ពិនិត្យឈ្មោះ និងរូបភាព Avatar របស់គណនី Roblox ====================
@app.route('/api/roblox/lookup', methods=['POST'])
def roblox_lookup():
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username", "")).strip()
    if not username:
        return jsonify({"success": False, "error": "សូមបញ្ចូល Username ជាមុនសិន!"}), 400

    try:
        u_res = requests.post(
            "https://users.roblox.com/v1/usernames/users",
            json={"usernames": [username], "excludeBannedUsers": False},
            timeout=8
        ).json()

        users_list = u_res.get("data", [])
        if not users_list:
            return jsonify({"success": False, "error": "❌ រកមិនឃើញគណនី Roblox ឈ្មោះនេះទេ!"})

        user_info = users_list[0]
        user_id = user_info["id"]
        real_username = user_info["name"]
        display_name = user_info.get("displayName", real_username)

        avatar_url = ""
        try:
            t_res = requests.get(
                f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=150x150&format=Png&isCircular=false",
                timeout=8
            ).json()
            t_data = t_res.get("data", [])
            if t_data and t_data[0].get("imageUrl"):
                avatar_url = t_data[0]["imageUrl"]
        except Exception:
            pass

        return jsonify({
            "success": True,
            "user": {
                "id": user_id,
                "username": real_username,
                "display_name": display_name,
                "avatar_url": avatar_url
            }
        })
    except Exception:
        return jsonify({"success": False, "error": "មិនអាចភ្ជាប់ទៅ Roblox API បានទេ សូមព្យាយាមម្តងទៀត!"}), 500

# ==================== API ពិនិត្យឈ្មោះគណនី MLBB & Free Fire ====================
@app.route('/api/game/lookup', methods=['POST'])
def game_lookup():
    payload = request.get_json(silent=True) or {}
    game_type = str(payload.get("game_type", "")).lower().strip()
    user_id = str(payload.get("user_id", "")).strip()
    zone_id = str(payload.get("zone_id", "")).strip()

    if not user_id:
        return jsonify({"success": False, "error": "សូមបញ្ចូល ID ហ្គេមជាមុនសិន!"}), 400

    try:
        if game_type == "mlbb":
            if not zone_id:
                return jsonify({"success": False, "error": "សូមបញ្ចូល Server / Zone ID ផង!"}), 400
            url = f"https://api.isan.eu.org/nickname/ml?id={user_id}&zone={zone_id}"
        elif game_type == "freefire":
            url = f"https://api.isan.eu.org/nickname/ff?id={user_id}"
        else:
            return jsonify({"success": False, "error": "មិនគាំទ្រហ្គេមនេះទេ!"}), 400

        res = requests.get(url, timeout=10).json()
        if res.get("success") and res.get("name"):
            return jsonify({
                "success": True,
                "nickname": res["name"],
                "user_id": user_id,
                "zone_id": zone_id
            })
        else:
            return jsonify({"success": False, "error": "❌ រកមិនឃើញគណនីនេះទេ! សូមពិនិត្យ ID ឡើងវិញ។"})
    except Exception:
        return jsonify({"success": False, "error": "⚠️ ប្រព័ន្ធឆែកឈ្មោះកំពុងរវល់ ប៉ុន្តែអ្នកអាចបន្តទិញបានធម្មតា។"}), 500

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

@app.route('/api/upload-tg-image', methods=['POST'])
def upload_tg_image():
    if 'photo' not in request.files:
        return jsonify({"success": False, "error": "មិនមានរូបភាពទេ!"}), 400
    photo_file = request.files['photo']
    try:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendPhoto"
        files = {'photo': (photo_file.filename, photo_file.stream, photo_file.mimetype)}
        data = {
            'chat_id': TG_GROUP_ID,
            'disable_notification': True
        }
        res = requests.post(url, files=files, data=data, timeout=20).json()
        if res.get("ok"):
            file_id = res["result"]["photo"][-1]["file_id"]
            return jsonify({"success": True, "file_id": file_id})
        else:
            return jsonify({"success": False, "error": res.get("description", "Upload Failed")}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/tg-image/<file_id>', methods=['GET'])
def serve_tg_image(file_id):
    try:
        info_res = requests.get(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getFile?file_id={file_id}", timeout=10).json()
        if not info_res.get("ok"):
            return "File not found", 404
        file_path = info_res["result"]["file_path"]
        file_url = f"https://api.telegram.org/file/bot{TG_BOT_TOKEN}/{file_path}"
        img_res = requests.get(file_url, timeout=15)
        return Response(img_res.content, mimetype=img_res.headers.get('Content-Type', 'application/octet-stream'))
    except Exception as e:
        return str(e), 500

# ==================== ប្រព័ន្ធឆាតឯកជនក្នុងវេបសាយ (Text Only) ====================
@app.route('/api/chat/send', methods=['POST'])
def chat_send():
    payload = request.get_json(silent=True) or {}
    room_id = str(payload.get("room_id", "")).strip()
    sender_id = str(payload.get("sender_id", "")).strip()
    sender_name = str(payload.get("sender_name", "User")).strip()
    sender_username = str(payload.get("sender_username", "")).strip()
    sender_photo = str(payload.get("sender_photo", "")).strip()
    is_admin = bool(payload.get("is_admin", False))
    text = str(payload.get("text", "")).strip()

    if not room_id or not sender_id or not text:
        return jsonify({"success": False, "error": "សូមបញ្ចូលសារជាអក្សរ!"}), 400

    d = load_data()
    chats = d.setdefault("chats", {})
    users = d.get("users", {})
    target_user = users.get(room_id, {})

    if room_id not in chats:
        chats[room_id] = {
            "user_id": room_id,
            "user_name": target_user.get("first_name", sender_name if not is_admin else "Customer"),
            "user_username": target_user.get("username", sender_username if not is_admin else ""),
            "user_photo": target_user.get("photo_url", sender_photo if not is_admin else ""),
            "unread_admin": 0,
            "unread_user": 0,
            "updated_ts": time.time(),
            "messages": []
        }

    room = chats[room_id]
    if not is_admin:
        room["user_name"] = sender_name
        room["user_username"] = sender_username
        if sender_photo:
            room["user_photo"] = sender_photo
        room["unread_admin"] = room.get("unread_admin", 0) + 1
    else:
        room["unread_user"] = room.get("unread_user", 0) + 1

    room["updated_ts"] = time.time()

    msg_obj = {
        "id": f"m_{int(time.time()*1000)}",
        "sender_id": sender_id,
        "sender_name": sender_name,
        "sender_photo": sender_photo,
        "is_admin": is_admin,
        "text": text,
        "time": time.strftime("%H:%M")
    }
    room["messages"].append(msg_obj)
    if len(room["messages"]) > 150:
        room["messages"] = room["messages"][-150:]

    save_data(d)
    return jsonify({"success": True, "message": msg_obj})

@app.route('/api/chat/room', methods=['POST'])
def chat_get_room():
    payload = request.get_json(silent=True) or {}
    room_id = str(payload.get("room_id", "")).strip()
    viewer_is_admin = bool(payload.get("is_admin", False))
    d = load_data()
    room = d.get("chats", {}).get(room_id)
    if not room:
        return jsonify({"success": True, "messages": [], "unread_user": 0})

    changed = False
    if viewer_is_admin and room.get("unread_admin", 0) > 0:
        room["unread_admin"] = 0
        changed = True
    elif not viewer_is_admin and room.get("unread_user", 0) > 0:
        room["unread_user"] = 0
        changed = True

    if changed:
        save_data(d)

    return jsonify({
        "success": True,
        "messages": room.get("messages", []),
        "unread_user": room.get("unread_user", 0)
    })

@app.route('/api/chat/admin/overview', methods=['POST'])
def chat_admin_overview():
    d = load_data()
    chats = d.get("chats", {})
    users = d.get("users", {})

    recent_rooms = []
    total_unread = 0

    sorted_chats = sorted(chats.items(), key=lambda x: x[1].get("updated_ts", 0), reverse=True)
    for r_id, r_data in sorted_chats:
        msgs = r_data.get("messages", [])
        if not msgs:
            continue
        last_msg = msgs[-1]
        unread = r_data.get("unread_admin", 0)
        total_unread += unread
        recent_rooms.append({
            "room_id": r_id,
            "user_name": r_data.get("user_name", "User"),
            "user_username": r_data.get("user_username", ""),
            "user_photo": r_data.get("user_photo", ""),
            "unread_admin": unread,
            "last_preview": last_msg.get("text", ""),
            "last_time": last_msg.get("time", "")
        })

    all_users = []
    for u_id, u_data in users.items():
        if u_data.get("username", "").lower() == ADMIN_USERNAME:
            continue
        all_users.append({
            "user_id": str(u_id),
            "user_name": u_data.get("first_name", "User"),
            "user_username": u_data.get("username", ""),
            "user_photo": u_data.get("photo_url", ""),
            "joined_at": u_data.get("joined_at", "")
        })

    return jsonify({
        "success": True,
        "recent_rooms": recent_rooms,
        "all_users": list(reversed(all_users)),
        "total_unread": total_unread
    })

# ==================== ការគ្រប់គ្រងគណនីហ្គេម & ការទូទាត់ KHQR ចូល ABA ====================
@app.route('/api/admin/accounts', methods=['POST'])
def get_admin_accounts():
    d = load_data()
    return jsonify({"success": True, "accounts": d.get("accounts", [])})

@app.route('/api/admin/account/save', methods=['POST'])
def save_admin_account():
    payload = request.get_json(silent=True) or {}
    d = load_data()
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

@app.route('/api/admin/account/delete', methods=['POST'])
def delete_admin_account():
    payload = request.get_json(silent=True) or {}
    acc_id = payload.get("acc_id")
    d = load_data()
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
    tg_id = str(payload.get("tg_id", "")).strip()
    d = load_data()
    user_orders = [o for o in d["orders"] if str(o.get("tg_id", "")).strip() == tg_id]
    return jsonify({"success": True, "orders": list(reversed(user_orders))})

@app.route('/api/admin/orders', methods=['POST'])
def get_all_orders_admin():
    d = load_data()
    return jsonify({"success": True, "orders": list(reversed(d["orders"]))})

@app.route('/api/store/save', methods=['POST'])
def update_store():
    payload = request.get_json(silent=True) or {}
    d = load_data()
    new_data = payload.get("data")
    if new_data:
        d["banners"] = new_data.get("banners", d["banners"])
        d["games"] = new_data.get("games", d["games"])
        d["items"] = new_data.get("items", d["items"])
        save_data(d)
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Invalid data"}), 400

@app.route('/api/create-order', methods=['POST'])
def create_order():
    data = request.get_json(silent=True) or {}
    tg_id = str(data.get("tg_id", "")).strip()
    tg_username = str(data.get("tg_username", "")).strip()
    tg_name = str(data.get("tg_name", "")).strip()
    order_type = data.get("order_type", "ITEM")
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
        unique_nonce = uuid.uuid4().hex[:6].upper()
        bill_no = f"KTY-{int(time.time())}-{unique_nonce}"
        
        qr_string = build_aba_khqr(price_usd, bill_no, unique_nonce)
        md5_hash = khqr.generate_md5(qr_string)

        order_record = {
            "bill_number": bill_no,
            "md5": md5_hash,
            "order_type": order_type,
            "account_id": acc_id,
            "tg_id": tg_id if tg_id else "GUEST",
            "tg_username": user.get("username", tg_username) if user else tg_username,
            "tg_name": user.get("first_name", tg_name or "ភ្ញៀវទូទៅ (Guest)") if user else (tg_name or "ភ្ញៀវទូទៅ (Guest)"),
            "game_name": game_name,
            "item_name": item_name,
            "player_info": player_info,
            "amount": round(price_usd, 2),
            "status": "PENDING",
            "used": False,
            "created_ts": time.time(),
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
            "expires_in": 300
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/check-payment', methods=['POST'])
def check_payment():
    data = request.get_json(silent=True) or {}
    md5_hash = data.get("md5")
    fallback_order = data.get("order_info") or {}
    if not md5_hash:
        return jsonify({"success": False, "error": "Missing MD5"}), 400

    d = load_data()
    order = next((o for o in d["orders"] if o["md5"] == md5_hash), None)

    if not order and fallback_order:
        order = {
            "bill_number": fallback_order.get("bill_number", f"KTY-{int(time.time())}"),
            "md5": md5_hash,
            "order_type": fallback_order.get("order_type", "ITEM"),
            "account_id": fallback_order.get("account_id", ""),
            "tg_id": fallback_order.get("tg_id", "GUEST"),
            "tg_username": fallback_order.get("tg_username", ""),
            "tg_name": fallback_order.get("tg_name", "ភ្ញៀវទូទៅ (Guest)"),
            "game_name": fallback_order.get("game_name", "Game"),
            "item_name": fallback_order.get("item_name", "Item"),
            "player_info": fallback_order.get("player_info", ""),
            "amount": float(fallback_order.get("amount", 0)),
            "status": "PENDING",
            "used": False,
            "created_ts": time.time(),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        d["orders"].append(order)

    if not order:
        return jsonify({"success": False, "error": "រកមិនឃើញវិក្កយបត្រនេះទេ!"}), 404

    if order.get("status") == "PAID" or order.get("used"):
        return jsonify({"success": True, "status": "PAID", "order": order})

    if time.time() - order.get("created_ts", 0) > 300:
        order["status"] = "EXPIRED"
        order["used"] = True
        save_data(d)
        return jsonify({"success": True, "status": "EXPIRED"})

    try:
        status = khqr.check_payment(md5_hash)
        if status == "PAID":
            order["status"] = "PAID"
            order["used"] = True
            order["paid_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

            if order.get("order_type") == "ACCOUNT":
                acc = next((a for a in d["accounts"] if a["id"] == order.get("account_id")), None)
                if acc:
                    order["delivered_login"] = acc.get("acc_login", "")
                    order["delivered_password"] = acc.get("acc_password", "")
                    if acc["stock"] > 0:
                        acc["stock"] -= 1

            save_data(d)

            if order["tg_id"] == "GUEST":
                buyer_text = "ភ្ញៀវទូទៅ (Guest)"
            else:
                tg_tag = f"@{order['tg_username']}" if order.get("tg_username") else order.get("tg_name")
                buyer_text = f"{tg_tag} (<code>{order['tg_id']}</code>)"

            if order.get("order_type") == "ACCOUNT":
                msg = (
                    f"🔐 <b>លក់គណនីហ្គេមជោគជ័យ (PAID ✅)</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"🧾 វិក្កយបត្រ៖ <code>{order['bill_number']}</code>\n"
                    f"🎮 ហ្គេម៖ <b>{order['game_name']}</b>\n"
                    f"🏷️ ឈ្មោះគណនី៖ <b>{order['item_name']}</b>\n"
                    f"💵 ទឹកប្រាក់៖ <b>${order['amount']:.2f}</b> (ចូល ABA)\n"
                    f"👤 អ្នកទិញ៖ {buyer_text}\n"
                    f"📧 User/Gmail៖ <code>{order.get('delivered_login', '')}</code>\n"
                    f"🔑 Password៖ <code>{order.get('delivered_password', '')}</code>\n"
                    f"⏰ ម៉ោងបង់ប្រាក់៖ {order['paid_at']}"
                )
            else:
                msg = (
                    f"💰 <b>មានការបញ្ជាទិញថ្មី (PAID ✅)</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"🧾 វិក្កយបត្រ៖ <code>{order['bill_number']}</code>\n"
                    f"🎮 ហ្គេម៖ <b>{order['game_name']}</b>\n"
                    f"💎 កញ្ចប់ Item៖ <b>{order['item_name']}</b>\n"
                    f"🆔 គណនីហ្គេម៖ <code>{order['player_info']}</code>\n"
                    f"💵 ទឹកប្រាក់៖ <b>${order['amount']:.2f}</b> (ចូល ABA)\n"
                    f"👤 អ្នកទិញ៖ {buyer_text}\n"
                    f"⏰ ម៉ោងបង់ប្រាក់៖ {order['paid_at']}"
                )
            send_telegram_group(msg)
            return jsonify({"success": True, "status": "PAID", "order": order})

        return jsonify({"success": True, "status": status})
    except Exception as e:
        print("Check Payment Error:", e)
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
