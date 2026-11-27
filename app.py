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
import io

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# Bakong Token & ABA Account
BAKONG_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJkYXRhIjp7ImlkIjoiYTYwNGFhZjliNmRlNGMzNyJ9LCJpYXQiOjE3OTA5ODA1MzgsImV4cCI6MTc5ODc1NjUzOH0.JVGnd51f_4MWB3nUu_OwtEmeo9FjJgy9BypFytO053I"
ABA_ROUTING_ID = "abaakhppxxx@abaa"
ABA_ACCOUNT_NO = "010765908"
ABA_MERCHANT_DISPLAY_NAME = "KTY STORE"

# Main Telegram Bot & Group (Orders, Users, Auto Backup)
TG_BOT_TOKEN = "9286576815:AAGW1VCYg8uZDqvGj5zATrnFaUjwghJpmqc"
TG_GROUP_ID = "-1005852775918"

# Reseller Withdrawal Bot & Group
WITHDRAW_BOT_TOKEN = "9264512580:AAFmfrxDbjR8KOJFaF5arlCJSqYbg0ONRCA"
WITHDRAW_GROUP_ID = "-1005930853810"

# Media/Item Image Storage Bot (shares TG_GROUP_ID or storage chat)
MEDIA_BOT_TOKEN = "9255176136:AAHL3yYdOnqtO26-DvtwzGG4bqQsXHsL8ew"

ADMIN_USERNAME = "ktyofficial169"
RESELLER_SHARE_RATE = 0.90
ADMIN_FEE_RATE = 0.10
AUTO_COMPLETE_SECONDS = 24 * 3600

khqr = KHQR(BAKONG_TOKEN)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, 'store_data.json')

DEFAULT_DATA = {
    "banners": [],
    "games": [],
    "items": [],
    "accounts": [],
    "marketplace_items": [],
    "allowed_resellers": ["novala16"],
    "resellers": {},
    "withdrawals": [],
    "users": {},
    "orders": [],
    "chats": {}
}

def crc16_ccitt(data: str) -> str:
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

def send_telegram_msg(bot_token, chat_id, text):
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }, timeout=6)
    except Exception as e:
        print("Telegram sendMessage error:", e)

def send_telegram_group(text):
    send_telegram_msg(TG_BOT_TOKEN, TG_GROUP_ID, text)

def send_withdraw_telegram(text, qr_file_id=""):
    send_telegram_msg(WITHDRAW_BOT_TOKEN, WITHDRAW_GROUP_ID, text)
    if qr_file_id:
        try:
            # Fetch file via MEDIA_BOT_TOKEN or TG_BOT_TOKEN and forward/send to WITHDRAW_GROUP_ID
            for tok in (MEDIA_BOT_TOKEN, TG_BOT_TOKEN):
                info = requests.get(f"https://api.telegram.org/bot{tok}/getFile?file_id={qr_file_id}", timeout=8).json()
                if info.get("ok"):
                    fpath = info["result"]["file_path"]
                    raw_bytes = requests.get(f"https://api.telegram.org/file/bot{tok}/{fpath}", timeout=12).content
                    requests.post(
                        f"https://api.telegram.org/bot{WITHDRAW_BOT_TOKEN}/sendPhoto",
                        files={"photo": ("khqr.jpg", io.BytesIO(raw_bytes), "image/jpeg")},
                        data={"chat_id": WITHDRAW_GROUP_ID, "caption": "📷 រូបភាព KHQR សម្រាប់ផ្ញើប្រាក់ជូន Reseller"},
                        timeout=15
                    )
                    break
        except Exception as e:
            print("Withdraw QR photo error:", e)

def backup_store_to_telegram(data_obj, pin_it=False):
    try:
        json_bytes = json.dumps(data_obj, ensure_ascii=False, indent=2).encode('utf-8')
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendDocument"
        files = {'document': ('store_data.json', io.BytesIO(json_bytes), 'application/json')}
        payload = {
            'chat_id': TG_GROUP_ID,
            'caption': f"💾 Auto Backup KTY Store ({time.strftime('%Y-%m-%d %H:%M:%S')})",
            'disable_notification': True
        }
        res = requests.post(url, files=files, data=payload, timeout=15).json()
        if pin_it and res.get("ok") and res.get("result", {}).get("message_id"):
            msg_id = res["result"]["message_id"]
            requests.post(
                f"https://api.telegram.org/bot{TG_BOT_TOKEN}/pinChatMessage",
                json={"chat_id": TG_GROUP_ID, "message_id": msg_id, "disable_notification": True},
                timeout=8
            )
    except Exception as e:
        print("Backup note:", e)

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
                        for k, v in DEFAULT_DATA.items():
                            raw.setdefault(k, json.loads(json.dumps(v)))
                        with open(DATA_FILE, 'w', encoding='utf-8') as f:
                            json.dump(raw, f, ensure_ascii=False, indent=2)
                        return raw
    except Exception as e:
        print("Initial load note:", e)
    return None

def ensure_schema(d):
    for k, v in DEFAULT_DATA.items():
        d.setdefault(k, json.loads(json.dumps(v)))
    allowed = [str(x).lstrip("@").strip().lower() for x in d.get("allowed_resellers", []) if str(x).strip()]
    if "novala16" not in allowed:
        allowed.append("novala16")
    d["allowed_resellers"] = allowed
    return d

def credit_reseller_for_order(d, order):
    """ផ្ទេរប្រាក់ 90% ចូលបាលែន Reseller (ធានាថាបញ្ចូលតែម្តងគត់)"""
    if order.get("reseller_credited"):
        return False
    sid = str(order.get("seller_id", "")).strip()
    if not sid:
        return False
    payout = round(float(order.get("amount", 0)) * RESELLER_SHARE_RATE, 2)
    order["reseller_payout"] = payout
    order["admin_commission"] = round(float(order.get("amount", 0)) - payout, 2)
    order["reseller_credited"] = True
    order["credited_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

    resellers = d.setdefault("resellers", {})
    seller = resellers.setdefault(sid, {
        "tg_id": sid,
        "name": order.get("seller_name", "Reseller"),
        "username": "",
        "shop_open": True,
        "balance": 0.0,
        "total_earned_90": 0.0,
        "total_withdrawn": 0.0
    })
    seller["balance"] = round(float(seller.get("balance", 0.0)) + payout, 2)
    seller["total_earned_90"] = round(float(seller.get("total_earned_90", 0.0)) + payout, 2)
    return True

def process_auto_completions(d):
    """ស្វ័យប្រវត្តិ៖ ប្រសិនបើ Item Order កំពុងដំណើរការលើសពី 24 ម៉ោង នឹងប្តូរទៅជា COMPLETED ដោយខ្លួនឯង"""
    now = time.time()
    changed = False
    for o in d.get("orders", []):
        if o.get("status") == "PAID" and o.get("order_type") in ("ITEM", "MARKET_ITEM"):
            fulfill = o.get("fulfillment_status", "PENDING_APPROVAL")
            if fulfill == "IN_PROGRESS":
                started_at = o.get("approved_at_ts") or o.get("paid_ts") or o.get("created_ts") or now
                if now - started_at >= AUTO_COMPLETE_SECONDS:
                    o["fulfillment_status"] = "COMPLETED"
                    o["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    o["auto_completed"] = True
                    credit_reseller_for_order(d, o)
                    changed = True
    return changed

def load_data():
    d = None
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                candidate = json.load(f)
                if isinstance(candidate, dict):
                    d = ensure_schema(candidate)
        except Exception:
            d = None

    if d is None or (not d.get("games") and not d.get("banners") and not d.get("items") and not d.get("accounts")):
        cloud_data = load_initial_from_telegram_pinned()
        if cloud_data:
            d = ensure_schema(cloud_data)
        elif d is None:
            d = json.loads(json.dumps(DEFAULT_DATA))
            save_data(d)

    if process_auto_completions(d):
        save_data(d)

    return d

def save_data(data):
    ensure_schema(data)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def push_admin_chat_notification(d, text_msg):
    """ផ្ញើសារជូនដំណឹងទៅក្នុងប្រអប់ឆាតរបស់ម្ចាស់វេបសាយ (Admin)"""
    chats = d.setdefault("chats", {})
    admin_room_id = "admin_notifications"
    if admin_room_id not in chats:
        chats[admin_room_id] = {
            "user_id": admin_room_id,
            "user_name": "🔔 ដំណឹងការបញ្ជាទិញ (Orders)",
            "user_username": "system_orders",
            "user_photo": "",
            "unread_admin": 0,
            "unread_user": 0,
            "updated_ts": time.time(),
            "messages": []
        }
    room = chats[admin_room_id]
    room["user_name"] = "🔔 ដំណឹងការបញ្ជាទិញ (Orders)"
    room["unread_admin"] = room.get("unread_admin", 0) + 1
    room["updated_ts"] = time.time()
    room["messages"].append({
        "id": f"m_{int(time.time()*1000)}_{uuid.uuid4().hex[:4]}",
        "sender_id": "system",
        "sender_name": "🤖 ប្រព័ន្ធ KTY Store",
        "sender_photo": "",
        "is_admin": False,
        "text": text_msg,
        "time": time.strftime("%H:%M")
    })
    if len(room["messages"]) > 200:
        room["messages"] = room["messages"][-200:]

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

@app.route('/api/roblox/lookup', methods=['POST'])
def roblox_lookup():
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username", "")).strip()
    if not username:
        return jsonify({"success": False, "error": "សូមបញ្ចូល Username Roblox ជាមុនសិន!"}), 400

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

def lookup_freefire_nickname(user_id: str):
    endpoints = [
        f"https://api.isan.eu.org/nickname/ff?id={user_id}",
        f"https://freefire-api-six.vercel.app/get_player_info?id={user_id}",
        f"https://api.ryzendesu.vip/api/stalk/ff?id={user_id}"
    ]
    for url in endpoints:
        try:
            r = requests.get(url, timeout=6)
            if r.status_code != 200:
                continue
            data = r.json()
            if isinstance(data, dict):
                if data.get("success") and data.get("name"):
                    return str(data["name"]).strip()
                if data.get("nickname"):
                    return str(data["nickname"]).strip()
                if isinstance(data.get("data"), dict):
                    inner = data["data"]
                    for k in ("nickname", "name", "username", "player_name"):
                        if inner.get(k):
                            return str(inner[k]).strip()
                if isinstance(data.get("basicInfo"), dict) and data["basicInfo"].get("nickname"):
                    return str(data["basicInfo"]["nickname"]).strip()
        except Exception:
            continue
    return None

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
            res = requests.get(url, timeout=8).json()
            if res.get("success") and res.get("name"):
                return jsonify({
                    "success": True,
                    "nickname": res["name"],
                    "user_id": user_id,
                    "zone_id": zone_id
                })
            return jsonify({"success": False, "error": "❌ រកមិនឃើញគណនីនេះទេ! សូមពិនិត្យ ID ឡើងវិញ។"})

        elif game_type == "freefire":
            if not user_id.isdigit() or len(user_id) < 5:
                return jsonify({"success": False, "error": "❌ Free Fire ID ត្រូវតែជាលេខយ៉ាងតិច ៥ ខ្ទង់!"})

            nick = lookup_freefire_nickname(user_id)
            if nick:
                return jsonify({
                    "success": True,
                    "nickname": nick,
                    "user_id": user_id,
                    "zone_id": zone_id
                })
            return jsonify({
                "success": True,
                "fallback": True,
                "nickname": f"Player ID: {user_id}",
                "user_id": user_id,
                "zone_id": zone_id
            })

        else:
            return jsonify({"success": False, "error": "មិនគាំទ្រហ្គេមនេះទេ!"}), 400
    except Exception:
        return jsonify({"success": False, "error": "⚠️ ប្រព័ន្ធឆែកឈ្មោះកំពុងរវល់ ប៉ុន្តែអ្នកអាចបន្តទិញបានធម្មតា។"}), 500

@app.route('/api/store', methods=['GET'])
def get_store():
    d = load_data()
    resellers = d.get("resellers", {})

    def is_seller_open(seller_id):
        if not seller_id:
            return True
        s = resellers.get(str(seller_id))
        if not s:
            return True
        return bool(s.get("shop_open", True))

    safe_accounts = []
    for acc in d.get("accounts", []):
        if not is_seller_open(acc.get("seller_id", "")):
            continue
        safe_accounts.append({
            "id": acc["id"],
            "title": acc["title"],
            "game_name": acc["game_name"],
            "price": acc["price"],
            "stock": acc["stock"],
            "description": acc.get("description", ""),
            "images": acc.get("images", []),
            "seller_id": acc.get("seller_id", ""),
            "seller_name": acc.get("seller_name", "")
        })

    safe_market_items = []
    for m_item in d.get("marketplace_items", []):
        if not is_seller_open(m_item.get("seller_id", "")):
            continue
        safe_market_items.append({
            "id": m_item["id"],
            "name": m_item["name"],
            "game_name": m_item.get("game_name", "Roblox"),
            "price": m_item["price"],
            "stock": m_item.get("stock", 10),
            "description": m_item.get("description", ""),
            "image": m_item.get("image", ""),
            "images": m_item.get("images", []),
            "seller_id": m_item.get("seller_id", ""),
            "seller_name": m_item.get("seller_name", "")
        })

    return jsonify({
        "banners": d["banners"],
        "games": d["games"],
        "items": d["items"],
        "accounts": safe_accounts,
        "marketplace_items": safe_market_items
    })

@app.route('/api/upload-tg-image', methods=['POST'])
def upload_tg_image():
    if 'photo' not in request.files:
        return jsonify({"success": False, "error": "មិនមានរូបភាពទេ!"}), 400
    photo_file = request.files['photo']
    try:
        # Use dedicated MEDIA_BOT_TOKEN first, fallback to TG_BOT_TOKEN
        for tok in (MEDIA_BOT_TOKEN, TG_BOT_TOKEN):
            url = f"https://api.telegram.org/bot{tok}/sendPhoto"
            photo_file.stream.seek(0)
            files = {'photo': (photo_file.filename, photo_file.stream, photo_file.mimetype)}
            data = {'chat_id': TG_GROUP_ID, 'disable_notification': True}
            res = requests.post(url, files=files, data=data, timeout=20).json()
            if res.get("ok"):
                file_id = res["result"]["photo"][-1]["file_id"]
                return jsonify({"success": True, "file_id": f"{tok[:8]}:{file_id}"})
        return jsonify({"success": False, "error": "Upload Failed"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/tg-image/<path:encoded_id>', methods=['GET'])
def serve_tg_image(encoded_id):
    try:
        prefix = ""
        file_id = encoded_id
        if ":" in encoded_id:
            prefix, file_id = encoded_id.split(":", 1)

        tokens_to_try = []
        if prefix == MEDIA_BOT_TOKEN[:8]:
            tokens_to_try = [MEDIA_BOT_TOKEN, TG_BOT_TOKEN]
        elif prefix == TG_BOT_TOKEN[:8]:
            tokens_to_try = [TG_BOT_TOKEN, MEDIA_BOT_TOKEN]
        else:
            tokens_to_try = [MEDIA_BOT_TOKEN, TG_BOT_TOKEN]

        for tok in tokens_to_try:
            info_res = requests.get(f"https://api.telegram.org/bot{tok}/getFile?file_id={file_id}", timeout=10).json()
            if info_res.get("ok"):
                file_path = info_res["result"]["file_path"]
                file_url = f"https://api.telegram.org/file/bot{tok}/{file_path}"
                img_res = requests.get(file_url, timeout=15)
                if img_res.status_code == 200:
                    return Response(img_res.content, mimetype=img_res.headers.get('Content-Type', 'application/octet-stream'))
        return "File not found", 404
    except Exception as e:
        return str(e), 500

# ==================== Chat System (Resellers CANNOT initiate chat to customers first) ====================
@app.route('/api/chat/send', methods=['POST'])
def chat_send():
    payload = request.get_json(silent=True) or {}
    room_id = str(payload.get("room_id", "")).strip()
    sender_id = str(payload.get("sender_id", "")).strip()
    sender_name = str(payload.get("sender_name", "User")).strip()
    sender_username = str(payload.get("sender_username", "")).strip()
    sender_photo = str(payload.get("sender_photo", "")).strip()
    is_admin = bool(payload.get("is_admin", False))
    is_reseller = bool(payload.get("is_reseller", False))
    text = str(payload.get("text", "")).strip()

    if not room_id or not sender_id or not text:
        return jsonify({"success": False, "error": "សូមបញ្ចូលសារជាអក្សរ!"}), 400

    d = load_data()
    chats = d.setdefault("chats", {})
    users = d.get("users", {})
    target_user = users.get(room_id, {})

    existing_room = chats.get(room_id)
    # Reseller cannot initiate a brand-new conversation with a customer who hasn't messaged first
    if is_reseller and not is_admin:
        if not existing_room or not existing_room.get("customer_initiated", False):
            return jsonify({
                "success": False,
                "error": "⚠️ អ្នកមិនមានសិទ្ធិផ្ញើសារទៅអតិថិជនមុនទេ! លុះត្រាតែអតិថិជនឆាតមកអ្នកជាមុនសិន។"
            }), 403

    if room_id not in chats:
        chats[room_id] = {
            "user_id": room_id,
            "user_name": target_user.get("first_name", sender_name if not is_admin else "Customer"),
            "user_username": target_user.get("username", sender_username if not is_admin else ""),
            "user_photo": target_user.get("photo_url", sender_photo if not is_admin else ""),
            "unread_admin": 0,
            "unread_user": 0,
            "customer_initiated": False,
            "updated_ts": time.time(),
            "messages": []
        }

    room = chats[room_id]
    if not is_admin and not is_reseller:
        room["customer_initiated"] = True
        room["user_name"] = sender_name
        room["user_username"] = sender_username
        if sender_photo:
            room["user_photo"] = sender_photo
        room["unread_admin"] = room.get("unread_admin", 0) + 1
    else:
        room["unread_user"] = room.get("unread_user", 0) + 1

    room["updated_ts"] = time.time()

    msg_obj = {
        "id": f"m_{int(time.time()*1000)}_{uuid.uuid4().hex[:4]}",
        "sender_id": sender_id,
        "sender_name": sender_name,
        "sender_photo": sender_photo,
        "is_admin": is_admin or is_reseller,
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
        return jsonify({"success": True, "messages": [], "unread_user": 0, "customer_initiated": False})

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
        "unread_user": room.get("unread_user", 0),
        "customer_initiated": bool(room.get("customer_initiated", False))
    })

@app.route('/api/chat/admin/overview', methods=['POST'])
def chat_admin_overview():
    payload = request.get_json(silent=True) or {}
    requester_is_admin = bool(payload.get("is_admin", True))
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
        # Resellers only see rooms where customer initiated chat
        if not requester_is_admin and not r_data.get("customer_initiated", False):
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

    # Only website owner (admin) gets full all_users directory to initiate chat first
    all_users = []
    if requester_is_admin:
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

# ==================== Reseller Portal APIs ====================
@app.route('/api/reseller/dashboard', methods=['POST'])
def reseller_dashboard():
    payload = request.get_json(silent=True) or {}
    tg_id = str(payload.get("tg_id", "")).strip()
    tg_name = str(payload.get("tg_name", "Reseller")).strip()
    tg_username = str(payload.get("tg_username", "")).strip()

    if not tg_id:
        return jsonify({"success": False, "error": "Missing user"}), 400

    d = load_data()
    if not is_username_approved_reseller(d, tg_username, tg_id):
        u_clean = str(tg_username or "").lstrip("@").strip().lower()
        if not u_clean:
            err_msg = "គណនី Telegram របស់អ្នកមិនទាន់មាន @username ទេ! សូមដាក់ @username ក្នុង Telegram រួច Login ឡើងវិញ។"
        else:
            err_msg = f"Username @{u_clean} មិនទាន់មានក្នុងបញ្ជី Reseller ដែលបានអនុញ្ញាតទេ!"
        return jsonify({"success": False, "error": err_msg, "checked_username": u_clean}), 403
    resellers = d.setdefault("resellers", {})

    if tg_id not in resellers:
        resellers[tg_id] = {
            "tg_id": tg_id,
            "name": tg_name,
            "username": tg_username,
            "shop_open": True,
            "balance": 0.0,
            "total_earned_90": 0.0,
            "total_withdrawn": 0.0,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        save_data(d)

    seller = resellers[tg_id]
    seller["name"] = tg_name or seller.get("name", "Reseller")
    seller["username"] = tg_username or seller.get("username", "")

    my_accounts = [a for a in d.get("accounts", []) if str(a.get("seller_id", "")) == tg_id]
    my_items = [m for m in d.get("marketplace_items", []) if str(m.get("seller_id", "")) == tg_id]
    my_orders = [
        o for o in reversed(d.get("orders", []))
        if str(o.get("seller_id", "")) == tg_id and o.get("status") == "PAID"
    ]

    total_listed = len(my_accounts) + len(my_items)
    total_ordered = len(my_orders)
    total_sold = sum(
        1 for o in my_orders
        if o.get("order_type") == "ACCOUNT" or o.get("fulfillment_status") == "COMPLETED"
    )
    my_withdrawals = [w for w in reversed(d.get("withdrawals", [])) if str(w.get("tg_id", "")) == tg_id]

    return jsonify({
        "success": True,
        "reseller": seller,
        "stats": {
            "total_listed": total_listed,
            "total_ordered": total_ordered,
            "total_sold": total_sold,
            "balance": round(float(seller.get("balance", 0.0)), 2),
            "shop_open": bool(seller.get("shop_open", True))
        },
        "accounts": my_accounts,
        "items": my_items,
        "orders": my_orders,
        "withdrawals": my_withdrawals
    })

@app.route('/api/reseller/shop-toggle', methods=['POST'])
def reseller_shop_toggle():
    payload = request.get_json(silent=True) or {}
    tg_id = str(payload.get("tg_id", "")).strip()
    d = load_data()
    u_obj = d.get("users", {}).get(tg_id, {})
    eff_user = payload.get("tg_username") or payload.get("seller_username") or u_obj.get("username", "")
    if not is_admin_request(d, payload) and not is_username_approved_reseller(d, eff_user, tg_id):
        return jsonify({"success": False, "error": "គណនីរបស់អ្នកមិនមានសិទ្ធិជា Reseller ទេ!"}), 403
    shop_open = bool(payload.get("shop_open", True))
    resellers = d.setdefault("resellers", {})
    seller = resellers.setdefault(tg_id, {
        "tg_id": tg_id,
        "name": payload.get("tg_name", "Reseller"),
        "username": payload.get("tg_username", ""),
        "shop_open": True,
        "balance": 0.0
    })
    seller["shop_open"] = shop_open
    save_data(d)
    backup_store_to_telegram(d, pin_it=True)
    return jsonify({"success": True, "shop_open": shop_open})


@app.route('/api/admin/market-item/save', methods=['POST'])
def save_admin_market_item_route():
    payload = request.get_json(silent=True) or {}
    d = load_data()
    if not is_admin_request(d, payload):
        return jsonify({"success": False, "error": "មានតែ @ktyofficial169 ប៉ុណ្ណោះដែលមានសិទ្ធិ!"}), 403
    prod = payload.get("product") or {}
    name = str(prod.get("name") or prod.get("title") or "").strip()
    try:
        price = round(float(prod.get("price", 0)), 2)
    except Exception:
        price = 0.0
    try:
        stock = max(0, int(prod.get("stock", 1)))
    except Exception:
        stock = 1
    game_name = str(prod.get("game_name", "Roblox")).strip() or "Roblox"
    images = (prod.get("images") or [])[:10]
    first_img = str(prod.get("image") or (images[0] if images else "")).strip()
    prod_id = prod.get("id")

    if not name or price <= 0:
        return jsonify({"success": False, "error": "សូមបំពេញឈ្មោះ និងតម្លៃ Item"}), 400

    existing_idx = next((i for i, m in enumerate(d.setdefault("marketplace_items", [])) if m["id"] == prod_id), -1)
    new_item = {
        "id": prod_id or f"ritem_{int(time.time())}_{uuid.uuid4().hex[:4]}",
        "name": name,
        "game_name": game_name,
        "price": price,
        "stock": stock,
        "description": str(prod.get("description", "")).strip(),
        "image": first_img,
        "images": images,
        "seller_id": "",
        "seller_name": ""
    }
    if existing_idx != -1:
        d["marketplace_items"][existing_idx] = new_item
    else:
        d["marketplace_items"].append(new_item)

    save_data(d)
    threading.Thread(target=backup_store_to_telegram, args=(json.loads(json.dumps(d)), True), daemon=True).start()
    return jsonify({"success": True, "item": new_item})

@app.route('/api/reseller/product/save', methods=['POST'])
def reseller_product_save():
    payload = request.get_json(silent=True) or {}
    tg_id = str(payload.get("tg_id", "")).strip()
    seller_name = str(payload.get("seller_name", "Reseller")).strip()
    kind = str(payload.get("kind", "ACCOUNT")).upper().strip()
    prod = payload.get("product") or {}

    if not tg_id or not prod:
        return jsonify({"success": False, "error": "ទិន្នន័យមិនត្រឹមត្រូវ"}), 400

    d = load_data()
    u_obj = d.get("users", {}).get(tg_id, {})
    eff_user = payload.get("tg_username") or payload.get("seller_username") or u_obj.get("username", "")
    if not is_username_approved_reseller(d, eff_user, tg_id):
        return jsonify({"success": False, "error": "គណនីរបស់អ្នកមិនមានសិទ្ធិជា Reseller ទេ!"}), 403
    resellers = d.setdefault("resellers", {})
    resellers.setdefault(tg_id, {
        "tg_id": tg_id,
        "name": seller_name,
        "username": payload.get("seller_username", ""),
        "shop_open": True,
        "balance": 0.0
    })

    prod_id = prod.get("id")
    price = round(float(prod.get("price", 0)), 2)
    stock = int(prod.get("stock", 1))
    title_or_name = str(prod.get("title") or prod.get("name") or "").strip()
    game_name = str(prod.get("game_name", "Roblox")).strip() or "Roblox"
    desc = str(prod.get("description", "")).strip()
    images = (prod.get("images") or [])[:10]
    first_img = prod.get("image") or (images[0] if images else "")

    if not title_or_name or price <= 0:
        return jsonify({"success": False, "error": "សូមបញ្ចូលឈ្មោះ និងតម្លៃឱ្យត្រឹមត្រូវ"}), 400

    if kind == "ACCOUNT":
        acc_login = str(prod.get("acc_login", "")).strip()
        acc_password = str(prod.get("acc_password", "")).strip()
        if not acc_login or not acc_password:
            return jsonify({"success": False, "error": "សូមបញ្ចូល Gmail/Username និង Password គណនី"}), 400

        existing_idx = next((i for i, a in enumerate(d["accounts"]) if a["id"] == prod_id), -1)
        new_acc = {
            "id": prod_id or f"racc_{int(time.time())}_{uuid.uuid4().hex[:4]}",
            "title": title_or_name,
            "game_name": game_name,
            "price": price,
            "stock": stock,
            "description": desc,
            "acc_login": acc_login,
            "acc_password": acc_password,
            "images": images,
            "seller_id": tg_id,
            "seller_name": seller_name
        }
        if existing_idx != -1:
            if str(d["accounts"][existing_idx].get("seller_id", "")) != tg_id:
                return jsonify({"success": False, "error": "គ្មានសិទ្ធិកែគណនីអ្នកដទៃទេ"}), 403
            d["accounts"][existing_idx] = new_acc
        else:
            d["accounts"].append(new_acc)
    else:
        existing_idx = next((i for i, m in enumerate(d["marketplace_items"]) if m["id"] == prod_id), -1)
        new_item = {
            "id": prod_id or f"ritem_{int(time.time())}_{uuid.uuid4().hex[:4]}",
            "name": title_or_name,
            "game_name": game_name,
            "price": price,
            "stock": stock,
            "description": desc,
            "image": first_img,
            "images": images,
            "seller_id": tg_id,
            "seller_name": seller_name
        }
        if existing_idx != -1:
            if str(d["marketplace_items"][existing_idx].get("seller_id", "")) != tg_id:
                return jsonify({"success": False, "error": "គ្មានសិទ្ធិកែ Item អ្នកដទៃទេ"}), 403
            d["marketplace_items"][existing_idx] = new_item
        else:
            d["marketplace_items"].append(new_item)

    save_data(d)
    threading.Thread(target=backup_store_to_telegram, args=(json.loads(json.dumps(d)), True), daemon=True).start()
    return jsonify({"success": True})

@app.route('/api/reseller/product/delete', methods=['POST'])
def reseller_product_delete():
    payload = request.get_json(silent=True) or {}
    tg_id = str(payload.get("tg_id", "")).strip()
    kind = str(payload.get("kind", "ACCOUNT")).upper().strip()
    prod_id = str(payload.get("prod_id", "")).strip()
    d = load_data()
    u_obj = d.get("users", {}).get(tg_id, {})
    eff_user = payload.get("tg_username") or payload.get("seller_username") or u_obj.get("username", "")
    if not is_username_approved_reseller(d, eff_user, tg_id):
        return jsonify({"success": False, "error": "គណនីរបស់អ្នកមិនមានសិទ្ធិជា Reseller ទេ!"}), 403

    if kind == "ACCOUNT":
        d["accounts"] = [
            a for a in d["accounts"]
            if not (a["id"] == prod_id and str(a.get("seller_id", "")) == tg_id)
        ]
    else:
        d["marketplace_items"] = [
            m for m in d["marketplace_items"]
            if not (m["id"] == prod_id and str(m.get("seller_id", "")) == tg_id)
        ]
    save_data(d)
    backup_store_to_telegram(d, pin_it=True)
    return jsonify({"success": True})

@app.route('/api/reseller/withdraw', methods=['POST'])
def reseller_withdraw():
    payload = request.get_json(silent=True) or {}
    tg_id = str(payload.get("tg_id", "")).strip()
    tg_username = str(payload.get("tg_username", "")).strip()
    account_name = str(payload.get("account_name", "")).strip()
    payment_id = str(payload.get("payment_id", "")).strip()
    qr_image_id = str(payload.get("qr_image_id", "")).strip()
    amount_raw = payload.get("amount")
    if not tg_id or not account_name or not payment_id:
        return jsonify({"success": False, "error": "សូមបំពេញឈ្មោះគណនី និងលេខសម្គាល់បង់ប្រាក់ (ABA)"}), 400
    d = load_data()
    u_obj = d.get("users", {}).get(tg_id, {})
    eff_user = tg_username or payload.get("seller_username") or u_obj.get("username", "")
    if not is_username_approved_reseller(d, eff_user, tg_id):
        return jsonify({"success": False, "error": "គណនីរបស់អ្នកមិនមានសិទ្ធិជា Reseller ទេ!"}), 403
    seller = d.get("resellers", {}).get(tg_id)
    if not seller:
        return jsonify({"success": False, "error": "រកមិនឃើញគណនី Reseller"}), 404

    current_bal = round(float(seller.get("balance", 0.0)), 2)
    try:
        req_amount = round(float(amount_raw), 2) if amount_raw not in (None, "") else current_bal
    except Exception:
        return jsonify({"success": False, "error": "ទឹកប្រាក់ដកមិនត្រឹមត្រូវ"}), 400

    if req_amount <= 0 or req_amount > current_bal:
        return jsonify({"success": False, "error": f"ទឹកប្រាក់ដកមិនគ្រប់គ្រាន់! បាលែនបច្ចុប្បន្ន៖ ${current_bal:.2f}"}), 400

    seller["balance"] = round(current_bal - req_amount, 2)
    seller["total_withdrawn"] = round(float(seller.get("total_withdrawn", 0.0)) + req_amount, 2)

    wd_record = {
        "id": f"WD-{int(time.time())}-{uuid.uuid4().hex[:4].upper()}",
        "tg_id": tg_id,
        "tg_username": tg_username,
        "seller_name": seller.get("name", "Reseller"),
        "account_name": account_name,
        "payment_id": payment_id,
        "qr_image_id": qr_image_id,
        "amount": req_amount,
        "status": "PENDING",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    d.setdefault("withdrawals", []).append(wd_record)
    save_data(d)
    backup_store_to_telegram(d, pin_it=True)

    tg_msg = (
        f"💸 <b>សំណើដកប្រាក់របស់ Reseller (90% Payout)</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🧾 លេខសំណើ៖ <code>{wd_record['id']}</code>\n"
        f"👤 Reseller៖ <b>{wd_record['seller_name']}</b> {('@' + tg_username) if tg_username else ''} (<code>{tg_id}</code>)\n"
        f"🏦 ឈ្មោះគណនី៖ <b>{account_name}</b>\n"
        f"🔢 លេខសម្គាល់ (ABA/ID)៖ <code>{payment_id}</code>\n"
        f"💵 ទឹកប្រាក់ត្រូវផ្ញើជូន៖ <b>${req_amount:.2f}</b>\n"
        f"💰 បាលែននៅសល់៖ <b>${seller['balance']:.2f}</b>\n"
        f"⏰ ម៉ោងស្នើ៖ {wd_record['created_at']}"
    )
    send_withdraw_telegram(tg_msg, qr_image_id)

    return jsonify({"success": True, "withdrawal": wd_record, "balance": seller["balance"]})

# ==================== Admin & Fulfillment Controls (Approve / Reject / Complete) ====================


def is_admin_request(d, payload: dict) -> bool:
    req_user = str(payload.get("username", "")).lstrip("@").strip().lower()
    if req_user == ADMIN_USERNAME.lower():
        return True
    req_tg_id = str(payload.get("tg_id", "")).strip()
    if req_tg_id:
        u_obj = d.get("users", {}).get(req_tg_id, {})
        if str(u_obj.get("username", "")).lstrip("@").strip().lower() == ADMIN_USERNAME.lower():
            return True
    return False

def is_username_approved_reseller(d, username: str, tg_id: str = "") -> bool:
    allowed = [str(x).lstrip("@").strip().lower() for x in d.get("allowed_resellers", []) if str(x).strip()]
    u = str(username or "").lstrip("@").strip().lower()
    if u:
        if u == ADMIN_USERNAME.lower() or u in allowed:
            return True
    tid = str(tg_id or "").strip()
    if tid:
        u_obj = d.get("users", {}).get(tid, {})
        saved_u = str(u_obj.get("username", "")).lstrip("@").strip().lower()
        if saved_u and (saved_u == ADMIN_USERNAME.lower() or saved_u in allowed):
            return True
        res_obj = d.get("resellers", {}).get(tid, {})
        res_u = str(res_obj.get("username", "")).lstrip("@").strip().lower()
        if res_u and (res_u == ADMIN_USERNAME.lower() or res_u in allowed):
            return True
    return False

@app.route('/api/admin/resellers/list', methods=['POST'])
def admin_resellers_list():
    payload = request.get_json(silent=True) or {}
    d = load_data()
    if not is_admin_request(d, payload):
        return jsonify({"success": False, "error": "មានតែ @ktyofficial169 ប៉ុណ្ណោះដែលមានសិទ្ធិ!"}), 403
    allowed = [str(x).lstrip("@").strip().lower() for x in d.get("allowed_resellers", []) if str(x).strip()]
    resellers_map = d.get("resellers", {})
    details = []
    for u in allowed:
        matched = next((r for r in resellers_map.values() if str(r.get("username", "")).lstrip("@").lower() == u), None)
        details.append({
            "username": u,
            "name": matched.get("name", "") if matched else "",
            "tg_id": matched.get("tg_id", "") if matched else "",
            "balance": round(float(matched.get("balance", 0.0)), 2) if matched else 0.0,
            "shop_open": bool(matched.get("shop_open", True)) if matched else True
        })
    return jsonify({"success": True, "usernames": allowed, "resellers": details})

@app.route('/api/admin/reseller/add', methods=['POST'])
def admin_reseller_add():
    payload = request.get_json(silent=True) or {}
    d = load_data()
    if not is_admin_request(d, payload):
        return jsonify({"success": False, "error": "មានតែ @ktyofficial169 ប៉ុណ្ណោះដែលមានសិទ្ធិ!"}), 403
    raw_user = str(payload.get("username", "")).lstrip("@").strip().lower()
    if not raw_user:
        return jsonify({"success": False, "error": "សូមបញ្ចូល Username Telegram!"}), 400
    allowed = d.setdefault("allowed_resellers", [])
    clean_list = [str(x).lstrip("@").strip().lower() for x in allowed if str(x).strip()]
    if raw_user not in clean_list:
        clean_list.append(raw_user)
    d["allowed_resellers"] = clean_list
    save_data(d)
    backup_store_to_telegram(d, pin_it=True)
    return jsonify({"success": True, "usernames": clean_list})

@app.route('/api/admin/reseller/remove', methods=['POST'])
def admin_reseller_remove():
    payload = request.get_json(silent=True) or {}
    d = load_data()
    if not is_admin_request(d, payload):
        return jsonify({"success": False, "error": "មានតែ @ktyofficial169 ប៉ុណ្ណោះដែលមានសិទ្ធិ!"}), 403
    raw_user = str(payload.get("username", "")).lstrip("@").strip().lower()
    allowed = [str(x).lstrip("@").strip().lower() for x in d.get("allowed_resellers", []) if str(x).lstrip("@").strip().lower() != raw_user]
    d["allowed_resellers"] = allowed
    save_data(d)
    backup_store_to_telegram(d, pin_it=True)
    return jsonify({"success": True, "usernames": allowed})

@app.route('/api/admin/accounts', methods=['POST'])
def get_admin_accounts():
    payload = request.get_json(silent=True) or {}
    d = load_data()
    if not is_admin_request(d, payload):
        return jsonify({"success": False, "error": "មានតែ @ktyofficial169 ប៉ុណ្ណោះដែលមានសិទ្ធិ!"}), 403
    return jsonify({"success": True, "accounts": d.get("accounts", [])})

@app.route('/api/admin/account/save', methods=['POST'])
def save_admin_account():
    payload = request.get_json(silent=True) or {}
    d = load_data()
    if not is_admin_request(d, payload):
        return jsonify({"success": False, "error": "មានតែ @ktyofficial169 ប៉ុណ្ណោះដែលមានសិទ្ធិ!"}), 403
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
        "images": acc_data.get("images", [])[:10],
        "seller_id": acc_data.get("seller_id", ""),
        "seller_name": acc_data.get("seller_name", "")
    }

    if existing_idx != -1:
        d["accounts"][existing_idx] = new_acc
    else:
        d["accounts"].append(new_acc)

    save_data(d)
    backup_store_to_telegram(d, pin_it=True)
    return jsonify({"success": True})

@app.route('/api/admin/account/delete', methods=['POST'])
def delete_admin_account():
    payload = request.get_json(silent=True) or {}
    d = load_data()
    if not is_admin_request(d, payload):
        return jsonify({"success": False, "error": "មានតែ @ktyofficial169 ប៉ុណ្ណោះដែលមានសិទ្ធិ!"}), 403
    acc_id = payload.get("acc_id")
    d["accounts"] = [a for a in d["accounts"] if a["id"] != acc_id]
    save_data(d)
    backup_store_to_telegram(d, pin_it=True)
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
    payload = request.get_json(silent=True) or {}
    d = load_data()
    if not is_admin_request(d, payload):
        return jsonify({"success": False, "error": "មានតែ @ktyofficial169 ប៉ុណ្ណោះដែលមានសិទ្ធិ!"}), 403
    return jsonify({"success": True, "orders": list(reversed(d["orders"]))})

@app.route('/api/order/fulfill', methods=['POST'])
def order_fulfill():
    """Admin or Reseller actions for ITEM / MARKET_ITEM orders: ACCEPT, COMPLETE (credits 90%), REJECT"""
    payload = request.get_json(silent=True) or {}
    bill_number = str(payload.get("bill_number", "")).strip()
    action = str(payload.get("action", "")).upper().strip()  # ACCEPT, COMPLETE, REJECT
    reason = str(payload.get("reason", "")).strip()
    actor_id = str(payload.get("tg_id", "")).strip()
    is_admin = bool(payload.get("is_admin", False))

    if not bill_number or action not in ("ACCEPT", "COMPLETE", "REJECT"):
        return jsonify({"success": False, "error": "សំណើមិនត្រឹមត្រូវ"}), 400

    d = load_data()
    order = next((o for o in d["orders"] if o.get("bill_number") == bill_number), None)
    if not order:
        return jsonify({"success": False, "error": "រកមិនឃើញការបញ្ជាទិញនេះទេ"}), 404

    if not is_admin and str(order.get("seller_id", "")) != actor_id:
        return jsonify({"success": False, "error": "អ្នកគ្មានសិទ្ធិគ្រប់គ្រងការបញ្ជាទិញនេះទេ!"}), 403

    if order.get("fulfillment_status") in ("COMPLETED", "REJECTED"):
        return jsonify({"success": False, "error": "ការបញ្ជាទិញនេះត្រូវបានបញ្ចប់ ឬបដិសេធរួចហើយ!"}), 400

    now_str = time.strftime("%Y-%m-%d %H:%M:%S")

    if action == "ACCEPT":
        order["fulfillment_status"] = "IN_PROGRESS"
        order["approved_at_ts"] = time.time()
        order["approved_at"] = now_str
        status_note = "កំពុងដំណើរការផ្ញើ Item (In Progress)"
    elif action == "COMPLETE":
        order["fulfillment_status"] = "COMPLETED"
        order["completed_at"] = now_str
        credited = credit_reseller_for_order(d, order)
        status_note = "បានផ្ញើ Item រួចរាល់ (Completed)"
        if credited:
            status_note += f" • ប្រាក់ 90% (${order.get('reseller_payout', 0):.2f}) បានចូលបាលែន Reseller"
    elif action == "REJECT":
        order["fulfillment_status"] = "REJECTED"
        order["rejected_at"] = now_str
        order["reject_reason"] = reason or "អស់ស្តុក Item នេះបណ្តោះអាសន្ន"
        if order.get("order_type") == "MARKET_ITEM" and order.get("market_item_id"):
            m_item = next((m for m in d.get("marketplace_items", []) if m["id"] == order["market_item_id"]), None)
            if m_item:
                m_item["stock"] = int(m_item.get("stock", 0)) + 1
        status_note = f"បានបដិសេធ ({order['reject_reason']})"

    save_data(d)
    backup_store_to_telegram(d, pin_it=True)

    # Notify customer in chat if they have a chat room
    cust_id = str(order.get("tg_id", ""))
    if cust_id and cust_id != "GUEST" and cust_id in d.get("chats", {}):
        room = d["chats"][cust_id]
        room["unread_user"] = room.get("unread_user", 0) + 1
        room["updated_ts"] = time.time()
        room["messages"].append({
            "id": f"m_{int(time.time()*1000)}_{uuid.uuid4().hex[:4]}",
            "sender_id": "system",
            "sender_name": "🔔 ស្ថានភាពបញ្ជាទិញ",
            "sender_photo": "",
            "is_admin": True,
            "text": f"[{bill_number}] {order['item_name']}: {status_note}",
            "time": time.strftime("%H:%M")
        })
        save_data(d)

    return jsonify({"success": True, "order": order})

@app.route('/api/store/save', methods=['POST'])
def update_store():
    payload = request.get_json(silent=True) or {}
    d = load_data()
    if not is_admin_request(d, payload):
        return jsonify({"success": False, "error": "មានតែ @ktyofficial169 ប៉ុណ្ណោះដែលមានសិទ្ធិ!"}), 403
    new_data = payload.get("data")
    if new_data:
        d["banners"] = new_data.get("banners", d["banners"])
        d["games"] = new_data.get("games", d["games"])
        d["items"] = new_data.get("items", d["items"])
        save_data(d)
        backup_store_to_telegram(d, pin_it=True)
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Invalid data"}), 400

@app.route('/api/create-order', methods=['POST'])
def create_order():
    data = request.get_json(silent=True) or {}
    tg_id = str(data.get("tg_id", "")).strip()
    tg_username = str(data.get("tg_username", "")).strip()
    tg_name = str(data.get("tg_name", "")).strip()
    order_type = str(data.get("order_type", "ITEM")).upper().strip()
    d = load_data()
    user = d["users"].get(tg_id) if tg_id else None

    seller_id = ""
    seller_name = ""
    acc_id = ""
    market_item_id = ""

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
        seller_id = str(acc.get("seller_id", ""))
        seller_name = str(acc.get("seller_name", ""))

    elif order_type == "MARKET_ITEM":
        market_item_id = data.get("market_item_id")
        m_item = next((m for m in d.get("marketplace_items", []) if m["id"] == market_item_id), None)
        roblox_user = str(data.get("roblox_username", "")).strip()
        if not roblox_user:
            return jsonify({"success": False, "error": "សូមបញ្ចូល Username Roblox ដើម្បីទទួល Item!"}), 400
        if m_item and int(m_item.get("stock", 1)) <= 0:
            return jsonify({"success": False, "error": "Item នេះអស់ស្តុកហើយ!"}), 400

        game_name = (m_item.get("game_name") if m_item else None) or str(data.get("game_name", "Roblox")).strip() or "Roblox"
        item_name = (m_item.get("name") if m_item else None) or str(data.get("item_name", "Item")).strip() or "Item"
        player_info = f"Roblox: {roblox_user}"
        raw_p = m_item.get("price") if m_item and m_item.get("price") is not None else data.get("price", 0)
        try:
            price_usd = float(raw_p)
        except Exception:
            price_usd = 0.0
        seller_id = str(m_item.get("seller_id", "")) if m_item else ""
        seller_name = str(m_item.get("seller_name", "")) if m_item else ""

    else:
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

        reseller_payout = round(price_usd * RESELLER_SHARE_RATE, 2) if seller_id else 0.0
        admin_commission = round(price_usd * ADMIN_FEE_RATE, 2) if seller_id else round(price_usd, 2)

        order_record = {
            "bill_number": bill_no,
            "md5": md5_hash,
            "order_type": order_type,
            "account_id": acc_id,
            "market_item_id": market_item_id,
            "seller_id": seller_id,
            "seller_name": seller_name,
            "reseller_payout": reseller_payout,
            "admin_commission": admin_commission,
            "fulfillment_status": "AUTO_DELIVERED" if order_type == "ACCOUNT" else "PENDING_APPROVAL",
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
        amt = float(fallback_order.get("amount", 0))
        sid = str(fallback_order.get("seller_id", ""))
        otype = fallback_order.get("order_type", "ITEM")
        order = {
            "bill_number": fallback_order.get("bill_number", f"KTY-{int(time.time())}"),
            "md5": md5_hash,
            "order_type": otype,
            "account_id": fallback_order.get("account_id", ""),
            "market_item_id": fallback_order.get("market_item_id", ""),
            "seller_id": sid,
            "seller_name": fallback_order.get("seller_name", ""),
            "reseller_payout": round(amt * RESELLER_SHARE_RATE, 2) if sid else 0.0,
            "admin_commission": round(amt * ADMIN_FEE_RATE, 2) if sid else round(amt, 2),
            "fulfillment_status": "AUTO_DELIVERED" if otype == "ACCOUNT" else "PENDING_APPROVAL",
            "tg_id": fallback_order.get("tg_id", "GUEST"),
            "tg_username": fallback_order.get("tg_username", ""),
            "tg_name": fallback_order.get("tg_name", "ភ្ញៀវទូទៅ (Guest)"),
            "game_name": fallback_order.get("game_name", "Game"),
            "item_name": fallback_order.get("item_name", "Item"),
            "player_info": fallback_order.get("player_info", ""),
            "amount": amt,
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
            order["paid_ts"] = time.time()
            order["paid_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

            # For ACCOUNT orders, auto-deliver and credit 90% immediately.
            # For ITEM / MARKET_ITEM orders, hold 90% until seller/admin confirms delivery (COMPLETED).
            sid = str(order.get("seller_id", ""))
            if sid:
                payout = round(float(order.get("amount", 0)) * RESELLER_SHARE_RATE, 2)
                order["reseller_payout"] = payout
                order["admin_commission"] = round(float(order.get("amount", 0)) - payout, 2)
                if order.get("order_type") == "ACCOUNT":
                    credit_reseller_for_order(d, order)

            if order.get("order_type") == "ACCOUNT":
                acc = next((a for a in d["accounts"] if a["id"] == order.get("account_id")), None)
                if acc:
                    order["delivered_login"] = acc.get("acc_login", "")
                    order["delivered_password"] = acc.get("acc_password", "")
                    if acc["stock"] > 0:
                        acc["stock"] -= 1

            elif order.get("order_type") == "MARKET_ITEM":
                m_item = next((m for m in d["marketplace_items"] if m["id"] == order.get("market_item_id")), None)
                if m_item and int(m_item.get("stock", 1)) > 0:
                    m_item["stock"] = int(m_item["stock"]) - 1

            if order["tg_id"] == "GUEST":
                buyer_text = "ភ្ញៀវទូទៅ (Guest)"
            else:
                tg_tag = f"@{order['tg_username']}" if order.get("tg_username") else order.get("tg_name")
                buyer_text = f"{tg_tag} (<code>{order['tg_id']}</code>)"

            seller_line = ""
            if sid:
                if order.get("reseller_credited"):
                    seller_line = f"\n🤝 Reseller៖ <b>{order.get('seller_name', 'Reseller')}</b> (ចូលបាលែន 90% រួច: <b>${order.get('reseller_payout', 0):.2f}</b> | ហាង 10%: <b>${order.get('admin_commission', 0):.2f}</b>)"
                else:
                    seller_line = f"\n🤝 Reseller៖ <b>{order.get('seller_name', 'Reseller')}</b> (រង់ចាំ Confirm ផ្ញើរួច ទើបចូល 90%: <b>${order.get('reseller_payout', 0):.2f}</b> | ហាង 10%: <b>${order.get('admin_commission', 0):.2f}</b>)"

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
                    f"🔑 Password៖ <code>{order.get('delivered_password', '')}</code>"
                    f"{seller_line}\n"
                    f"⏰ ម៉ោងបង់ប្រាក់៖ {order['paid_at']}"
                )
                chat_notif = (
                    f"✅ គណនីត្រូវបានទិញរួច!\n"
                    f"• វិក្កយបត្រ: {order['bill_number']}\n"
                    f"• ឈ្មោះគណនី: {order['item_name']}\n"
                    f"• តម្លៃ: ${order['amount']:.2f}\n"
                    f"• អ្នកទិញ: {order['tg_name']}"
                )
            else:
                msg = (
                    f"💰 <b>មានការបញ្ជាទិញ Item ថ្មី (PAID ✅)</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"🧾 វិក្កយបត្រ៖ <code>{order['bill_number']}</code>\n"
                    f"🎮 ហ្គេម៖ <b>{order['game_name']}</b>\n"
                    f"💎 កញ្ចប់ Item៖ <b>{order['item_name']}</b>\n"
                    f"🆔 គណនីហ្គេម៖ <code>{order['player_info']}</code>\n"
                    f"💵 ទឹកប្រាក់៖ <b>${order['amount']:.2f}</b> (ចូល ABA)"
                    f"{seller_line}\n"
                    f"👤 អ្នកទិញ៖ {buyer_text}\n"
                    f"⏰ ម៉ោងបង់ប្រាក់៖ {order['paid_at']}"
                )
                chat_notif = (
                    f"💎 ការបញ្ជាទិញ Item ថ្មី!\n"
                    f"• វិក្កយបត្រ: {order['bill_number']}\n"
                    f"• Item: {order['item_name']} (${order['amount']:.2f})\n"
                    f"• ព័ត៌មានអ្នកទិញ: {order['player_info']}\n"
                    f"• ស្ថានភាព: រង់ចាំទទួល/បដិសេធ"
                )

            push_admin_chat_notification(d, chat_notif)
            save_data(d)
            backup_store_to_telegram(d, pin_it=True)
            send_telegram_group(msg)
            return jsonify({"success": True, "status": "PAID", "order": order})

        return jsonify({"success": True, "status": status})
    except Exception as e:
        print("Check Payment Error:", e)
        return jsonify({"success": False, "error": str(e)}), 500
# ==================== Unified Telegram Admin Bot (@ktyofficial169 Only) ====================
import threading

CTRL_BOT_TOKEN = "9108175209:AAHoT0Wq_7L0LeLFKuEmAv2CjzmtIjt2IqQ"
CTRL_ADMIN_USERNAME = "ktyofficial169"
ctrl_user_states = {}


def ctrl_tg_api(method, payload=None, files=None):
    url = f"https://api.telegram.org/bot{CTRL_BOT_TOKEN}/{method}"
    try:
        if files:
            r = requests.post(url, data=payload or {}, files=files, timeout=20)
        else:
            r = requests.post(url, json=payload or {}, timeout=20)
        return r.json()
    except Exception as e:
        print(f"Ctrl Bot TG API error [{method}]:", e)
        return {"ok": False, "error": str(e)}


def ctrl_send_msg(chat_id, text, reply_markup=None):
    body = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        body["reply_markup"] = reply_markup
    return ctrl_tg_api("sendMessage", body)


def ctrl_answer_cb(cb_id, text=""):
    return ctrl_tg_api("answerCallbackQuery", {"callback_query_id": cb_id, "text": text, "show_alert": False})


def ctrl_is_owner(msg_or_cb):
    user = msg_or_cb.get("from") or {}
    uname = str(user.get("username") or "").lstrip("@").strip().lower()
    return uname == CTRL_ADMIN_USERNAME.lower()


def ctrl_reupload_photo(file_id_from_ctrl_bot):
    try:
        g = ctrl_tg_api("getFile", {"file_id": file_id_from_ctrl_bot})
        if not g.get("ok"):
            return f"{MEDIA_BOT_TOKEN[:8]}:{file_id_from_ctrl_bot}"
        fpath = g["result"]["file_path"]
        raw = requests.get(f"https://api.telegram.org/file/bot{CTRL_BOT_TOKEN}/{fpath}", timeout=20).content
        url = f"https://api.telegram.org/bot{MEDIA_BOT_TOKEN}/sendPhoto"
        res = requests.post(
            url,
            files={"photo": ("item.jpg", raw, "image/jpeg")},
            data={"chat_id": TG_GROUP_ID, "disable_notification": True},
            timeout=20
        ).json()
        if res.get("ok"):
            new_fid = res["result"]["photo"][-1]["file_id"]
            return f"{MEDIA_BOT_TOKEN[:8]}:{new_fid}"
    except Exception as e:
        print("Ctrl photo reupload error:", e)
    return f"{MEDIA_BOT_TOKEN[:8]}:{file_id_from_ctrl_bot}"


def ctrl_main_menu():
    return {
        "inline_keyboard": [
            [
                {"text": "បង្ហោះហ្គេមថ្មី", "callback_data": "c_add_game"},
                {"text": "បង្ហោះ Item ក្នុងហ្គេម", "callback_data": "c_add_gitem"}
            ],
            [
                {"text": "បង្ហោះលក់គណនី", "callback_data": "c_add_acc"},
                {"text": "បង្ហោះលក់អាយធីម", "callback_data": "c_add_mitem"}
            ],
            [
                {"text": "បង្ហោះ Banner", "callback_data": "c_add_banner"},
                {"text": "គ្រប់គ្រង Reseller", "callback_data": "c_resellers"}
            ],
            [
                {"text": "មើលទំនិញ & លុប", "callback_data": "c_list"},
                {"text": "ការបញ្ជាទិញ (Orders)", "callback_data": "c_orders"}
            ]
        ]
    }


def ctrl_start_flow(uid, chat_id, flow_name, extra=None):
    ctrl_user_states[uid] = {"flow": flow_name, "step": 0, "data": extra or {}}
    ctrl_prompt_step(uid, chat_id)


def ctrl_prompt_step(uid, chat_id):
    st = ctrl_user_states.get(uid)
    if not st:
        return
    flow = st["flow"]
    step = st["step"]
    data = st["data"]
    cancel_kb = {"inline_keyboard": [[{"text": "បោះបង់", "callback_data": "c_cancel"}]]}

    if flow == "add_banner":
        ctrl_send_msg(chat_id, "<b>បង្ហោះ Banner ថ្មី</b>\nផ្ញើ <b>Link រូបភាព Banner</b> (16:9):", cancel_kb)

    elif flow == "add_game":
        if step == 0:
            ctrl_send_msg(chat_id, "<b>បង្ហោះហ្គេមថ្មី (១/៦)</b>\nបញ្ចូល <b>ឈ្មោះហ្គេម</b>:", cancel_kb)
        elif step == 1:
            ctrl_send_msg(chat_id, "<b>បង្ហោះហ្គេមថ្មី (២/៦)</b>\nផ្ញើ <b>Link រូបភាព Logo ហ្គេម</b> (ឬ <code>skip</code>):", cancel_kb)
        elif step == 2:
            ctrl_send_msg(chat_id, "<b>បង្ហោះហ្គេមថ្មី (៣/៦)</b>\nបើក <b>ប្រអប់សរសេរទី ១</b> ទេ? វាយ <code>yes</code> ឬ <code>no</code>:", cancel_kb)
        elif step == 3:
            if not data.get("input1_enabled"):
                st["step"] = 4
                ctrl_prompt_step(uid, chat_id)
                return
            ctrl_send_msg(chat_id, "បញ្ចូល <b>ចំណងជើងប្រអប់ទី ១</b>:", cancel_kb)
        elif step == 31:
            ctrl_send_msg(chat_id, "បញ្ចូល <b>អក្សរគំរូ (Placeholder) ប្រអប់ទី ១</b> (ឬ <code>skip</code>):", cancel_kb)
        elif step == 4:
            ctrl_send_msg(chat_id, "<b>បង្ហោះហ្គេមថ្មី (៤/៦)</b>\nបើក <b>ប្រអប់សរសេរទី ២</b> ទេ? វាយ <code>yes</code> ឬ <code>no</code>:", cancel_kb)
        elif step == 5:
            if not data.get("input2_enabled"):
                st["step"] = 6
                ctrl_prompt_step(uid, chat_id)
                return
            ctrl_send_msg(chat_id, "បញ្ចូល <b>ចំណងជើងប្រអប់ទី ២</b>:", cancel_kb)
        elif step == 51:
            ctrl_send_msg(chat_id, "បញ្ចូល <b>អក្សរគំរូ (Placeholder) ប្រអប់ទី ២</b> (ឬ <code>skip</code>):", cancel_kb)
        elif step == 6:
            ctrl_send_msg(chat_id, "<b>បង្ហោះហ្គេមថ្មី (៦/៦)</b>\nបញ្ចូល <b>អក្សរណែនាំ</b> (ឬ <code>skip</code>):", cancel_kb)

    elif flow == "add_game_item":
        d = load_data()
        if step == 0:
            games = d.get("games", [])
            if not games:
                ctrl_user_states.pop(uid, None)
                ctrl_send_msg(chat_id, "មិនទាន់មានហ្គេមទេ! សូមបង្ហោះហ្គេមជាមុនសិន។", ctrl_main_menu())
                return
            rows = [[{"text": f"Game: {g['name']}", "callback_data": f"c_pick_g:{g['id']}"}] for g in games]
            rows.append([{"text": "បោះបង់", "callback_data": "c_cancel"}])
            ctrl_send_msg(chat_id, "<b>បង្ហោះ Item ក្នុងហ្គេម (១/៤)</b>\nជ្រើសរើសហ្គេម៖", {"inline_keyboard": rows})
        elif step == 1:
            ctrl_send_msg(chat_id, "<b>បង្ហោះ Item ក្នុងហ្គេម (២/៤)</b>\nបញ្ចូល <b>ឈ្មោះកញ្ចប់ Item</b>:", cancel_kb)
        elif step == 2:
            ctrl_send_msg(chat_id, "<b>បង្ហោះ Item ក្នុងហ្គេម (៣/៤)</b>\nបញ្ចូល <b>តម្លៃ ($ USD)</b>:", cancel_kb)
        elif step == 3:
            ctrl_send_msg(chat_id, "<b>បង្ហោះ Item ក្នុងហ្គេម (៤/៤)</b>\nផ្ញើ <b>Link រូបភាព Item</b> (ឬ <code>skip</code>):", cancel_kb)

    elif flow == "add_account":
        if step == 0:
            ctrl_send_msg(chat_id, "<b>បង្ហោះលក់គណនី (១/៧)</b>\nបញ្ចូល <b>ប្រភេទហ្គេម</b> (ឧ. Roblox):", cancel_kb)
        elif step == 1:
            ctrl_send_msg(chat_id, "<b>បង្ហោះលក់គណនី (២/៧)</b>\nបញ្ចូល <b>ឈ្មោះគណនី / ចំណងជើង</b>:", cancel_kb)
        elif step == 2:
            ctrl_send_msg(chat_id, "<b>បង្ហោះលក់គណនី (៣/៧)</b>\nបញ្ចូល <b>តម្លៃ ($ USD)</b>:", cancel_kb)
        elif step == 3:
            ctrl_send_msg(chat_id, "<b>បង្ហោះលក់គណនី (៤/៧)</b>\nបញ្ចូល <b>ចំនួនស្តុក</b>:", cancel_kb)
        elif step == 4:
            ctrl_send_msg(chat_id, "<b>បង្ហោះលក់គណនី (៥/៧)</b>\nបញ្ចូល <b>ព័ត៌មានលម្អិត</b> (ឬ <code>skip</code>):", cancel_kb)
        elif step == 5:
            ctrl_send_msg(chat_id, "<b>បង្ហោះលក់គណនី (៦/៧)</b>\nបញ្ចូល <b>Gmail ឬ Username គណនី</b>:", cancel_kb)
        elif step == 6:
            ctrl_send_msg(chat_id, "<b>បង្ហោះលក់គណនី (៧/៧)</b>\nបញ្ចូល <b>Password គណនី</b>:", cancel_kb)
        elif step == 7:
            kb = {
                "inline_keyboard": [
                    [{"text": "រួចរាល់ / បង្ហោះឥឡូវនេះ", "callback_data": "c_done_acc"}],
                    [{"text": "បោះបង់", "callback_data": "c_cancel"}]
                ]
            }
            cnt = len(data.get("images", []))
            ctrl_send_msg(chat_id, f"<b>ផ្ញើរូបភាពគណនី ({cnt}/10 រូប)</b>\nផ្ញើរូបភាពរួចចុច <b>រួចរាល់ / បង្ហោះឥឡូវនេះ</b> (ឬ <code>skip</code>):", kb)

    elif flow == "add_market_item":
        if step == 0:
            ctrl_send_msg(chat_id, "<b>បង្ហោះលក់អាយធីម (១/៤)</b>\nបញ្ចូល <b>ឈ្មោះ Item</b>:", cancel_kb)
        elif step == 1:
            ctrl_send_msg(chat_id, "<b>បង្ហោះលក់អាយធីម (២/៤)</b>\nបញ្ចូល <b>តម្លៃ ($ USD)</b>:", cancel_kb)
        elif step == 2:
            ctrl_send_msg(chat_id, "<b>បង្ហោះលក់អាយធីម (៣/៤)</b>\nបញ្ចូល <b>ចំនួនស្តុក</b>:", cancel_kb)
        elif step == 3:
            kb = {
                "inline_keyboard": [
                    [{"text": "រួចរាល់ / បង្ហោះ Item ឥឡូវនេះ", "callback_data": "c_done_mitem"}],
                    [{"text": "បោះបង់", "callback_data": "c_cancel"}]
                ]
            }
            cnt = len(data.get("images", []))
            ctrl_send_msg(chat_id, f"<b>ផ្ញើរូបភាព Item ({cnt}/10 រូប)</b>\nផ្ញើរូបភាពរួចចុច <b>រួចរាល់ / បង្ហោះ Item ឥឡូវនេះ</b> (ឬ <code>skip</code>):", kb)

    elif flow == "add_reseller":
        ctrl_send_msg(chat_id, "<b>បន្ថែម Reseller</b>\nបញ្ចូល <b>Telegram Username</b> (ឧ. @novala16):", cancel_kb)


def ctrl_finish_acc(uid, chat_id):
    st = ctrl_user_states.pop(uid, None) or {}
    data = st.get("data") or {}
    d = load_data()
    imgs = (data.get("images") or [])[:10]
    acc_obj = {
        "id": f"acc_{int(time.time())}",
        "title": data.get("title", "Account"),
        "game_name": data.get("game_name", "Roblox"),
        "price": data.get("price", 1.0),
        "stock": data.get("stock", 1),
        "description": data.get("description", ""),
        "acc_login": data.get("acc_login", ""),
        "acc_password": data.get("acc_password", ""),
        "images": imgs,
        "seller_id": "",
        "seller_name": ""
    }
    d["accounts"].append(acc_obj)
    save_data(d)
    backup_store_to_telegram(d, pin_it=True)
    ctrl_send_msg(chat_id, f"បានបង្ហោះគណនី <b>{acc_obj['title']}</b> (${acc_obj['price']:.2f}) រួចរាល់!", ctrl_main_menu())


def ctrl_finish_mitem(uid, chat_id):
    st = ctrl_user_states.pop(uid, None) or {}
    data = st.get("data") or {}
    d = load_data()
    imgs = (data.get("images") or [])[:10]
    first_img = imgs[0] if imgs else ""
    m_obj = {
        "id": f"ritem_{int(time.time())}_{uuid.uuid4().hex[:4]}",
        "name": data.get("name", "Item"),
        "game_name": "Roblox",
        "price": data.get("price", 1.0),
        "stock": data.get("stock", 1),
        "description": "",
        "image": first_img,
        "images": imgs,
        "seller_id": "",
        "seller_name": ""
    }
    d.setdefault("marketplace_items", []).append(m_obj)
    save_data(d)
    backup_store_to_telegram(d, pin_it=True)
    ctrl_send_msg(chat_id, f"បានបង្ហោះអាយធីម <b>{m_obj['name']}</b> (${m_obj['price']:.2f}) រួចរាល់!", ctrl_main_menu())


def ctrl_handle_text(uid, chat_id, text):
    st = ctrl_user_states.get(uid)
    if not st:
        return False
    flow = st["flow"]
    step = st["step"]
    data = st["data"]
    low = text.strip().lower()

    if flow == "add_banner":
        d = load_data()
        d["banners"].append(text.strip())
        save_data(d)
        backup_store_to_telegram(d, pin_it=True)
        ctrl_user_states.pop(uid, None)
        ctrl_send_msg(chat_id, "បានបន្ថែម Banner រួចរាល់!", ctrl_main_menu())
        return True

    if flow == "add_game":
        if step == 0:
            data["name"] = text.strip()
            st["step"] = 1
        elif step == 1:
            data["image"] = "" if low == "skip" else text.strip()
            st["step"] = 2
        elif step == 2:
            data["input1_enabled"] = low in ("yes", "y", "1", "true", "បាទ", "ចាស", "បើក")
            st["step"] = 3
        elif step == 3:
            data["input1_label"] = text.strip() or "Username / ID"
            st["step"] = 31
        elif step == 31:
            data["input1_placeholder"] = "" if low == "skip" else text.strip()
            st["step"] = 4
        elif step == 4:
            data["input2_enabled"] = low in ("yes", "y", "1", "true", "បាទ", "ចាស", "បើក")
            st["step"] = 5
        elif step == 5:
            data["input2_label"] = text.strip() or "Server ID"
            st["step"] = 51
        elif step == 51:
            data["input2_placeholder"] = "" if low == "skip" else text.strip()
            st["step"] = 6
        elif step == 6:
            data["input_note"] = "" if low == "skip" else text.strip()
            d = load_data()
            game_obj = {
                "id": "game_" + str(int(time.time())),
                "name": data.get("name", "Game"),
                "image": data.get("image") or "https://cdn-icons-png.flaticon.com/512/686/686589.png",
                "input1_enabled": bool(data.get("input1_enabled", True)),
                "input1_label": data.get("input1_label", "Username / ID"),
                "input1_placeholder": data.get("input1_placeholder", ""),
                "input2_enabled": bool(data.get("input2_enabled", False)),
                "input2_label": data.get("input2_label", "Server ID"),
                "input2_placeholder": data.get("input2_placeholder", ""),
                "input_note": data.get("input_note", "")
            }
            d["games"].append(game_obj)
            save_data(d)
            backup_store_to_telegram(d, pin_it=True)
            ctrl_user_states.pop(uid, None)
            ctrl_send_msg(chat_id, f"បានបង្ហោះហ្គេម <b>{game_obj['name']}</b> រួចរាល់!", ctrl_main_menu())
            return True
        ctrl_prompt_step(uid, chat_id)
        return True

    if flow == "add_game_item":
        if step == 1:
            data["name"] = text.strip()
            st["step"] = 2
        elif step == 2:
            try:
                val = float(text.strip())
                if val <= 0:
                    ctrl_send_msg(chat_id, "តម្លៃត្រូវតែធំជាង 0! សូមបញ្ចូលម្តងទៀត:")
                    return True
                data["price"] = round(val, 2)
                st["step"] = 3
            except Exception:
                ctrl_send_msg(chat_id, "សូមបញ្ចូលតម្លៃជាលេខ (ឧ. 1.00):")
                return True
        elif step == 3:
            img = "" if low == "skip" else text.strip()
            d = load_data()
            item_obj = {
                "id": "item_" + str(int(time.time())),
                "game_id": data.get("game_id"),
                "name": data.get("name", "Item"),
                "price": data.get("price", 1.0),
                "image": img or "https://cdn-icons-png.flaticon.com/512/616/616490.png"
            }
            d["items"].append(item_obj)
            save_data(d)
            backup_store_to_telegram(d, pin_it=True)
            ctrl_user_states.pop(uid, None)
            ctrl_send_msg(chat_id, f"បានបង្ហោះ Item <b>{item_obj['name']}</b> (${item_obj['price']:.2f}) រួចរាល់!", ctrl_main_menu())
            return True
        ctrl_prompt_step(uid, chat_id)
        return True

    if flow == "add_account":
        if step == 0:
            data["game_name"] = text.strip()
            st["step"] = 1
        elif step == 1:
            data["title"] = text.strip()
            st["step"] = 2
        elif step == 2:
            try:
                val = float(text.strip())
                if val <= 0:
                    ctrl_send_msg(chat_id, "តម្លៃត្រូវតែធំជាង 0! សូមបញ្ចូលម្តងទៀត:")
                    return True
                data["price"] = round(val, 2)
                st["step"] = 3
            except Exception:
                ctrl_send_msg(chat_id, "សូមបញ្ចូលតម្លៃជាលេខ (ឧ. 5.00):")
                return True
        elif step == 3:
            try:
                data["stock"] = max(0, int(text.strip()))
                st["step"] = 4
            except Exception:
                ctrl_send_msg(chat_id, "សូមបញ្ចូលស្តុកជាលេខគត់:")
                return True
        elif step == 4:
            data["description"] = "" if low == "skip" else text.strip()
            st["step"] = 5
        elif step == 5:
            data["acc_login"] = text.strip()
            st["step"] = 6
        elif step == 6:
            data["acc_password"] = text.strip()
            data["images"] = []
            st["step"] = 7
        elif step == 7 and low == "skip":
            ctrl_finish_acc(uid, chat_id)
            return True
        ctrl_prompt_step(uid, chat_id)
        return True

    if flow == "add_market_item":
        if step == 0:
            data["name"] = text.strip()
            st["step"] = 1
        elif step == 1:
            try:
                val = float(text.strip())
                if val <= 0:
                    ctrl_send_msg(chat_id, "តម្លៃត្រូវតែធំជាង 0! សូមបញ្ចូលម្តងទៀត:")
                    return True
                data["price"] = round(val, 2)
                st["step"] = 2
            except Exception:
                ctrl_send_msg(chat_id, "សូមបញ្ចូលតម្លៃជាលេខ (ឧ. 1.20):")
                return True
        elif step == 2:
            try:
                data["stock"] = max(0, int(text.strip()))
                data["images"] = []
                st["step"] = 3
            except Exception:
                ctrl_send_msg(chat_id, "សូមបញ្ចូលស្តុកជាលេខគត់:")
                return True
        elif step == 3 and low == "skip":
            ctrl_finish_mitem(uid, chat_id)
            return True
        ctrl_prompt_step(uid, chat_id)
        return True

    if flow == "add_reseller":
        uname = text.strip().lstrip("@").strip().lower()
        if not uname:
            ctrl_send_msg(chat_id, "សូមបញ្ចូល Username ឱ្យត្រឹមត្រូវ:")
            return True
        d = load_data()
        allowed = d.setdefault("allowed_resellers", [])
        if uname not in allowed:
            allowed.append(uname)
        save_data(d)
        backup_store_to_telegram(d, pin_it=True)
        ctrl_user_states.pop(uid, None)
        ctrl_send_msg(chat_id, f"បានផ្តល់សិទ្ធិ Reseller ជូន <b>@{uname}</b> រួចរាល់!", ctrl_main_menu())
        return True

    return False


def ctrl_handle_photo(uid, chat_id, msg):
    st = ctrl_user_states.get(uid)
    if not st or st["flow"] not in ("add_account", "add_market_item") or st["step"] not in (7, 3):
        return False
    photos = msg.get("photo") or []
    if not photos:
        return False
    encoded = ctrl_reupload_photo(photos[-1]["file_id"])
    imgs = st["data"].setdefault("images", [])
    if len(imgs) < 10:
        imgs.append(encoded)
    ctrl_prompt_step(uid, chat_id)
    return True


def ctrl_handle_callback(cb):
    if not ctrl_is_owner(cb):
        ctrl_answer_cb(cb["id"])
        return
    msg = cb.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    uid = str((cb.get("from") or {}).get("id") or "")
    data_str = cb.get("data") or ""
    ctrl_answer_cb(cb["id"])

    if data_str == "c_cancel":
        ctrl_user_states.pop(uid, None)
        ctrl_send_msg(chat_id, "បានបោះបង់។", ctrl_main_menu())
    elif data_str == "c_add_game":
        ctrl_start_flow(uid, chat_id, "add_game")
    elif data_str == "c_add_gitem":
        ctrl_start_flow(uid, chat_id, "add_game_item")
    elif data_str == "c_add_acc":
        ctrl_start_flow(uid, chat_id, "add_account")
    elif data_str == "c_add_mitem":
        ctrl_start_flow(uid, chat_id, "add_market_item")
    elif data_str == "c_add_banner":
        ctrl_start_flow(uid, chat_id, "add_banner")
    elif data_str == "c_done_acc":
        ctrl_finish_acc(uid, chat_id)
    elif data_str == "c_done_mitem":
        ctrl_finish_mitem(uid, chat_id)
    elif data_str.startswith("c_pick_g:"):
        gid = data_str.split(":", 1)[1]
        if uid in ctrl_user_states:
            ctrl_user_states[uid]["data"]["game_id"] = gid
            ctrl_user_states[uid]["step"] = 1
            ctrl_prompt_step(uid, chat_id)
    elif data_str == "c_resellers":
        d = load_data()
        allowed = d.get("allowed_resellers", [])
        txt = "<b>Reseller ដែលបានអនុញ្ញាត៖</b>\n" + ("\n".join(f"• @{u}" for u in allowed) if allowed else "• មិនទាន់មាន")
        kb = {"inline_keyboard": [[{"text": "បន្ថែម Reseller", "callback_data": "c_add_res"}], [{"text": "ម៉ឺនុយដើម", "callback_data": "c_back"}]]}
        ctrl_send_msg(chat_id, txt, kb)
    elif data_str == "c_add_res":
        ctrl_start_flow(uid, chat_id, "add_reseller")
    elif data_str == "c_list":
        d = load_data()
        lines = ["<b>ទំនិញក្នុងហាង៖</b>"]
        kb = []
        for g in d.get("games", []):
            lines.append(f"Game: {g['name']}")
            kb.append([{"text": f"លុប Game: {g['name']}", "callback_data": f"c_del_g:{g['id']}"}])
        for a in d.get("accounts", []):
            lines.append(f"Acc: {a['title']} (${a['price']})")
            kb.append([{"text": f"លុប Acc: {a['title'][:18]}", "callback_data": f"c_del_a:{a['id']}"}])
        for m in d.get("marketplace_items", []):
            lines.append(f"Item: {m['name']} (${m['price']})")
            kb.append([{"text": f"លុប Item: {m['name'][:18]}", "callback_data": f"c_del_m:{m['id']}"}])
        kb.append([{"text": "ម៉ឺនុយដើម", "callback_data": "c_back"}])
        ctrl_send_msg(chat_id, "\n".join(lines), {"inline_keyboard": kb})
    elif data_str.startswith("c_del_g:"):
        gid = data_str.split(":", 1)[1]
        d = load_data()
        d["games"] = [x for x in d.get("games", []) if x["id"] != gid]
        d["items"] = [x for x in d.get("items", []) if x.get("game_id") != gid]
        save_data(d)
        backup_store_to_telegram(d, pin_it=True)
        ctrl_send_msg(chat_id, "បានលុបហ្គេមរួចរាល់!", ctrl_main_menu())
    elif data_str.startswith("c_del_a:"):
        aid = data_str.split(":", 1)[1]
        d = load_data()
        d["accounts"] = [x for x in d.get("accounts", []) if x["id"] != aid]
        save_data(d)
        backup_store_to_telegram(d, pin_it=True)
        ctrl_send_msg(chat_id, "បានលុបគណនីរួចរាល់!", ctrl_main_menu())
    elif data_str.startswith("c_del_m:"):
        mid = data_str.split(":", 1)[1]
        d = load_data()
        d["marketplace_items"] = [x for x in d.get("marketplace_items", []) if x["id"] != mid]
        save_data(d)
        backup_store_to_telegram(d, pin_it=True)
        ctrl_send_msg(chat_id, "បានលុបអាយធីមរួចរាល់!", ctrl_main_menu())
    elif data_str == "c_orders":
        d = load_data()
        orders = list(reversed(d.get("orders", [])))[:8]
        if not orders:
            ctrl_send_msg(chat_id, "មិនទាន់មានការបញ្ជាទិញទេ។", ctrl_main_menu())
            return
        lines = ["<b>ការបញ្ជាទិញចុងក្រោយ៖</b>"] + [f"• <code>{o.get('bill_number')}</code> | {o.get('item_name')} (${o.get('amount')}) | {o.get('status')}" for o in orders]
        ctrl_send_msg(chat_id, "\n".join(lines), ctrl_main_menu())
    elif data_str == "c_back":
        ctrl_user_states.pop(uid, None)
        ctrl_send_msg(chat_id, "<b>ផ្ទាំងបញ្ជា @ktyofficial169</b>", ctrl_main_menu())


def ctrl_handle_message(msg):
    if not ctrl_is_owner(msg):
        return
    chat_id = (msg.get("chat") or {}).get("id")
    uid = str((msg.get("from") or {}).get("id") or "")
    if not chat_id or not uid:
        return
    if ctrl_handle_photo(uid, chat_id, msg):
        return
    text = (msg.get("text") or "").strip()
    if not text:
        return
    if text in ("/start", "/menu", "/cancel"):
        ctrl_user_states.pop(uid, None)
        ctrl_send_msg(chat_id, "<b>សួស្តី @ktyofficial169!</b>\nជ្រើសរើសមុខងារដើម្បីបញ្ជា៖", ctrl_main_menu())
        return
    if ctrl_handle_text(uid, chat_id, text):
        return
    ctrl_send_msg(chat_id, "<b>ផ្ទាំងបញ្ជាសម្រាប់ @ktyofficial169 ប៉ុណ្ណោះ៖</b>", ctrl_main_menu())


def ctrl_poll_loop():
    ctrl_tg_api("deleteWebhook", {"drop_pending_updates": False})
    offset = 0
    while True:
        try:
            res = ctrl_tg_api("getUpdates", {"offset": offset, "timeout": 25})
            if res.get("ok"):
                for upd in res.get("result", []):
                    offset = upd["update_id"] + 1
                    if "message" in upd:
                        ctrl_handle_message(upd["message"])
                    elif "callback_query" in upd:
                        ctrl_handle_callback(upd["callback_query"])
        except Exception as e:
            print("Ctrl bot poll error:", e)
            time.sleep(3)


_ctrl_thread_started = False
_ctrl_thread_lock = threading.Lock()


def ensure_ctrl_bot_running():
    global _ctrl_thread_started
    with _ctrl_thread_lock:
        if not _ctrl_thread_started:
            _ctrl_thread_started = True
            threading.Thread(target=ctrl_poll_loop, daemon=True, name="CtrlAdminBotThread").start()


ensure_ctrl_bot_running()


@app.before_request
def _kickoff_ctrl_bot():
    ensure_ctrl_bot_running()


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
