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
import threading

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

# Media/Item Image Storage Bot
MEDIA_BOT_TOKEN = "9255176136:AAHL3yYdOnqtO26-DvtwzGG4bqQsXHsL8ew"

# Admin Control Bot (Restricted strictly to @ktyofficial169)
CTRL_BOT_TOKEN = "9108175209:AAHoT0Wq_7L0LeLFKuEmAv2CjzmtIjt2IqQ"
CTRL_ADMIN_USERNAME = "ktyofficial169"
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

ctrl_user_states = {}

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
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=6
        )
    except Exception as e:
        print("Telegram sendMessage error:", e)

def send_telegram_group(text):
    send_telegram_msg(TG_BOT_TOKEN, TG_GROUP_ID, text)

def send_withdraw_telegram(text, qr_file_id=""):
    send_telegram_msg(WITHDRAW_BOT_TOKEN, WITHDRAW_GROUP_ID, text)
    if qr_file_id:
        try:
            for tok in (MEDIA_BOT_TOKEN, TG_BOT_TOKEN):
                info = requests.get(f"https://api.telegram.org/bot{tok}/getFile?file_id={qr_file_id}", timeout=8).json()
                if info.get("ok"):
                    fpath = info["result"]["file_path"]
                    raw_bytes = requests.get(f"https://api.telegram.org/file/bot{tok}/{fpath}", timeout=12).content
                    requests.post(
                        f"https://api.telegram.org/bot{WITHDRAW_BOT_TOKEN}/sendPhoto",
                        files={"photo": ("khqr.jpg", io.BytesIO(raw_bytes), "image/jpeg")},
                        data={"chat_id": WITHDRAW_GROUP_ID, "caption": "KHQR Reseller"},
                        timeout=15
                    )
                    break
        except Exception as e:
            print("Withdraw QR photo error:", e)

def backup_store_to_telegram(data_obj, pin_it=False):
    try:
        json_bytes = json.dumps(data_obj, ensure_ascii=False, indent=2).encode('utf-8')
        files = {'document': ('store_data.json', io.BytesIO(json_bytes), 'application/json')}
        payload = {
            'chat_id': TG_GROUP_ID,
            'caption': f"Auto Backup KTY Store ({time.strftime('%Y-%m-%d %H:%M:%S')})",
            'disable_notification': True
        }
        res = requests.post(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendDocument", files=files, data=payload, timeout=15).json()
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
        "tg_id": sid, "name": order.get("seller_name", "Reseller"), "username": "",
        "shop_open": True, "balance": 0.0, "total_earned_90": 0.0, "total_withdrawn": 0.0
    })
    seller["balance"] = round(float(seller.get("balance", 0.0)) + payout, 2)
    seller["total_earned_90"] = round(float(seller.get("total_earned_90", 0.0)) + payout, 2)
    return True

def process_auto_completions(d):
    now = time.time()
    changed = False
    for o in d.get("orders", []):
        if o.get("status") == "PAID" and o.get("order_type") in ("ITEM", "MARKET_ITEM"):
            if o.get("fulfillment_status", "PENDING_APPROVAL") == "IN_PROGRESS":
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

@app.route('/')
def home():
    return send_file(os.path.join(BASE_DIR, 'index.html'))

@app.route('/api/store', methods=['GET'])
def get_store():
    d = load_data()
    return jsonify({
        "banners": d["banners"],
        "games": d["games"],
        "items": d["items"],
        "accounts": d["accounts"],
        "marketplace_items": d.get("marketplace_items", [])
    })

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
        "name": name, "game_name": game_name, "price": price, "stock": stock,
        "description": str(prod.get("description", "")).strip(),
        "image": first_img, "images": images, "seller_id": "", "seller_name": ""
    }
    if existing_idx != -1:
        d["marketplace_items"][existing_idx] = new_item
    else:
        d["marketplace_items"].append(new_item)
    save_data(d)
    threading.Thread(target=backup_store_to_telegram, args=(json.loads(json.dumps(d)), True), daemon=True).start()
    return jsonify({"success": True, "item": new_item})

# ==================== Telegram Admin Bot (@ktyofficial169 Only) ====================
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
    body = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        body["reply_markup"] = reply_markup
    return ctrl_tg_api("sendMessage", body)

def ctrl_answer_cb(cb_id, text=""):
    return ctrl_tg_api("answerCallbackQuery", {"callback_query_id": cb_id, "text": text, "show_alert": False})

def ctrl_is_owner(msg_or_cb):
    user = msg_or_cb.get("from") or {}
    uname = str(user.get("username") or "").lstrip("@").strip().lower()
    return uname == CTRL_ADMIN_USERNAME.lower()

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

def ctrl_poll_loop():
    ctrl_tg_api("deleteWebhook", {"drop_pending_updates": False})
    offset = 0
    while True:
        try:
            res = ctrl_tg_api("getUpdates", {"offset": offset, "timeout": 25})
            if res.get("ok"):
                for upd in res.get("result", []):
                    offset = upd["update_id"] + 1
                    msg = upd.get("message")
                    cb = upd.get("callback_query")
                    if msg and ctrl_is_owner(msg):
                        chat_id = (msg.get("chat") or {}).get("id")
                        txt = (msg.get("text") or "").strip()
                        if chat_id and txt in ("/start", "/menu"):
                            ctrl_send_msg(chat_id, "<b>សួស្តី @ktyofficial169!</b> ជ្រើសរើសមុខងារ៖", ctrl_main_menu())
                    elif cb and ctrl_is_owner(cb):
                        chat_id = ((cb.get("message") or {}).get("chat") or {}).get("id")
                        ctrl_answer_cb(cb["id"])
                        if chat_id:
                            ctrl_send_msg(chat_id, f"បានទទួលបញ្ជា៖ <code>{cb.get('data')}</code>", ctrl_main_menu())
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

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
