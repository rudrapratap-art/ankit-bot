#!/usr/bin/env python3
"""
Simple Telegram support bot (getUpdates long-poll)

Features (preserved):
 - Users send messages/media/stickers -> bot forwards media to all admins and notifies admins (quoted text).
 - Admins get buttons: Copy user_id, Prepare Reply, Prepare Send Media.
 - Admin can reply to forwarded admin-message -> bot forwards reply to original user (text/photo/video/sticker).
 - Admin can send media via /send_media flows.
 - Admin can use /send_sticker <chat_id> then send a sticker which will be forwarded to that chat.
 - Admin can use /sendtoalluser <message> to message all known chats.
 - All state persisted in bot_data.json:
     last_update_id, seen_chats, inbox (recent messages), thread_map (adminMsg -> userChat), pending_sticker.
 - Deletes webhook on start to avoid HTTP 409.
"""

import json
import time
import urllib.request
import urllib.parse
import traceback
from datetime import datetime
from typing import Any, Dict, Optional
import ssl

# -------------------- CONFIG --------------------
BOT_TOKEN = "8438639692:AAHKxD2egSS9STGZ0iTvF7EsoncML3C_wiI"
ADMIN_IDS = [7627349162,5980759440]
DATA_FILE = "bot_data.json"
POLL_INTERVAL = 1.0                # seconds between retries
INBOX_LIMIT = 1000
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}/"

# -------------------- HTTP / API --------------------
def api_request(method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Make a simple application/x-www-form-urlencoded POST to Telegram API"""
    url = API_BASE + method
    data = None
    if params:
        safe: Dict[str, Any] = {}
        for k, v in params.items():
            if isinstance(v, (dict, list)):
                safe[k] = json.dumps(v, ensure_ascii=False)
            else:
                safe[k] = v
        data = urllib.parse.urlencode(safe).encode()

    try:
        # Create SSL context that doesn't verify certificates
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        with urllib.request.urlopen(url, data=data, timeout=30, context=ssl_context) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as he:
        try:
            body = he.read().decode("utf-8", errors="ignore")
        except Exception:
            body = str(he)
        print(f"[api_request] HTTPError {he.code}: {body}")
        return {"ok": False, "error": f"HTTPError {he.code}", "code": he.code, "body": body}
    except Exception as exc:
        print(f"[api_request] Exception: {exc}")
        return {"ok": False, "error": str(exc)}

# convenience wrappers
def send_message(chat_id: int, text: str, parse_mode: Optional[str] = None,
                 reply_to_message_id: Optional[int] = None, reply_markup: Optional[Dict] = None) -> Dict:
    params = {"chat_id": chat_id, "text": text}
    if parse_mode:
        params["parse_mode"] = parse_mode
    if reply_to_message_id:
        params["reply_to_message_id"] = reply_to_message_id
    if reply_markup:
        params["reply_markup"] = reply_markup
    return api_request("sendMessage", params)

def send_photo(chat_id: int, file_id: str, caption: Optional[str] = None,
               reply_to_message_id: Optional[int] = None) -> Dict:
    params = {"chat_id": chat_id, "photo": file_id}
    if caption:
        params["caption"] = caption
    if reply_to_message_id:
        params["reply_to_message_id"] = reply_to_message_id
    return api_request("sendPhoto", params)

def send_video(chat_id: int, file_id: str, caption: Optional[str] = None,
               reply_to_message_id: Optional[int] = None) -> Dict:
    params = {"chat_id": chat_id, "video": file_id}
    if caption:
        params["caption"] = caption
    if reply_to_message_id:
        params["reply_to_message_id"] = reply_to_message_id
    return api_request("sendVideo", params)

def send_sticker(chat_id: int, sticker_file_id: str, reply_to_message_id: Optional[int] = None) -> Dict:
    params = {"chat_id": chat_id, "sticker": sticker_file_id}
    if reply_to_message_id:
        params["reply_to_message_id"] = reply_to_message_id
    return api_request("sendSticker", params)

def forward_message(chat_id: int, from_chat_id: int, message_id: int) -> Dict:
    params = {"chat_id": chat_id, "from_chat_id": from_chat_id, "message_id": message_id}
    return api_request("forwardMessage", params)

def answer_callback(callback_id: str, text: Optional[str] = None) -> Dict:
    params = {"callback_query_id": callback_id}
    if text:
        params["text"] = text
    return api_request("answerCallbackQuery", params)

# -------------------- Persistence --------------------
def load_store() -> Dict[str, Any]:
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {"last_update_id": None, "seen_chats": [], "inbox": [], "thread_map": {}, "pending_sticker": {}}
    except Exception as exc:
        print(f"[load_store] error: {exc}")
        return {"last_update_id": None, "seen_chats": [], "inbox": [], "thread_map": {}, "pending_sticker": {}}

def save_store(data: Dict[str, Any]) -> None:
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    except Exception as exc:
        print(f"[save_store] error: {exc}")

# -------------------- Helpers --------------------
def is_admin(uid: Optional[int]) -> bool:
    return uid in ADMIN_IDS

def now_ts() -> int:
    return int(time.time())

def fmt_time(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

def escape_html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# thread_map helpers
def store_thread_map(admin_id: int, admin_msg_id: int, user_chat_id: int) -> None:
    d = load_store()
    tm = d.get("thread_map", {})
    tm[f"{admin_id}:{admin_msg_id}"] = user_chat_id
    d["thread_map"] = tm
    save_store(d)

def lookup_thread_target(admin_id: int, admin_msg_id: int) -> Optional[int]:
    d = load_store()
    return d.get("thread_map", {}).get(f"{admin_id}:{admin_msg_id}")

# pending sticker helpers
def set_pending_sticker(admin_id: int, target_chat: int) -> None:
    d = load_store()
    pend = d.get("pending_sticker", {})
    pend[str(admin_id)] = int(target_chat)
    d["pending_sticker"] = pend
    save_store(d)

def get_pending_sticker(admin_id: int) -> Optional[int]:
    d = load_store()
    return d.get("pending_sticker", {}).get(str(admin_id))

def pop_pending_sticker(admin_id: int) -> Optional[int]:
    d = load_store()
    pend = d.get("pending_sticker", {})
    key = str(admin_id)
    if key in pend:
        val = pend.pop(key)
        d["pending_sticker"] = pend
        save_store(d)
        return val
    return None

# -------------------- Notifications to admins --------------------
def notify_admins(user_chat_id: int, user_from: Dict[str, Any], text: str,
                  photos=None, video=None, sticker=None) -> None:
    """
    Forward any media to admins (so admins can reply directly to forwarded media),
    then send a quoted notification with 3 inline buttons:
      - Copy user_id
      - Prepare Reply
      - Prepare Send Media
    Each admin message id is mapped back to the user's chat id.
    """
    uid = user_from.get("id")
    username = user_from.get("username") or ""
    first = user_from.get("first_name") or ""
    last = user_from.get("last_name") or ""
    fullname = (first + " " + last).strip() or "(no name)"

    ts = fmt_time(now_ts())
    safe_text = escape_html(text or "")

    # forward media first so admins can reply to it
    caption = f"{fullname} | @{username if username else 'no-username'}\nuser_id:{uid} | chat_id:{user_chat_id}"

    if photos:
        file_id = photos[-1].get("file_id")
        for aid in ADMIN_IDS:
            res = send_photo(aid, file_id, caption=caption)
            if res.get("ok") and res.get("result"):
                try:
                    store_thread_map(aid, res["result"]["message_id"], user_chat_id)
                except Exception:
                    pass

    if video:
        file_id = video.get("file_id")
        for aid in ADMIN_IDS:
            res = send_video(aid, file_id, caption=caption)
            if res.get("ok") and res.get("result"):
                try:
                    store_thread_map(aid, res["result"]["message_id"], user_chat_id)
                except Exception:
                    pass

    if sticker:
        file_id = sticker.get("file_id")
        for aid in ADMIN_IDS:
            res = send_sticker(aid, file_id)
            if res.get("ok") and res.get("result"):
                try:
                    store_thread_map(aid, res["result"]["message_id"], user_chat_id)
                except Exception:
                    pass

    # prepare notification text
    header = f"📩 New message to bot\nTime: {ts}\nName: {escape_html(fullname)}\n"
    if username:
        header += f"Username: @{escape_html(username)}\n"
    user_line = f"user_id: {uid} | chat_id: {user_chat_id}"
    body = f"{header}{user_line}\n\n<pre>\"{safe_text}\"</pre>"

    # inline keyboard
    kb = [
        {"text": "Copy user_id", "callback_data": f"copyuid:{uid}"},
        {"text": "Prepare Reply", "callback_data": f"prep_reply:{user_chat_id}"},
        {"text": "Prepare Send Media", "callback_data": f"prep_send_media:{user_chat_id}"}
    ]
    reply_markup = {"inline_keyboard": [kb]}

    # notify each admin and map notification message -> user chat (for reply-forwarding)
    for aid in ADMIN_IDS:
        res = send_message(aid, body, parse_mode="HTML", reply_markup=reply_markup)
        if res.get("ok") and res.get("result"):
            try:
                store_thread_map(aid, res["result"]["message_id"], user_chat_id)
            except Exception:
                pass

# -------------------- Admin commands / helpers --------------------
def cmd_reply(admin_id: int, args: str) -> Dict[str, Any]:
    if not is_admin(admin_id):
        return {"ok": False, "error": "not admin"}
    if not args:
        return {"ok": False, "error": "usage: /reply <chat_id> <message>"}
    parts = args.strip().split(None, 1)
    if len(parts) < 2:
        return {"ok": False, "error": "usage: /reply <chat_id> <message>"}
    try:
        target = int(parts[0])
    except Exception:
        return {"ok": False, "error": "invalid chat_id"}
    message = parts[1].strip()
    if not message:
        return {"ok": False, "error": "empty message"}
    res = send_message(target, message)
    if res.get("ok"):
        return {"ok": True, "sent_to": target}
    return {"ok": False, "error": res.get("description")}

def cmd_send_media(admin_id: int, msg: Dict[str, Any], args_text: str) -> Dict[str, Any]:
    """
    Supports:
      - Admin replies to a media/sticker message with `/send_media <chat_id> [caption]`
      - Admin sends a media with caption starting `/send_media <chat_id> [caption]`
    """
    if not is_admin(admin_id):
        return {"ok": False, "error": "not admin"}
    args = (args_text or "").strip()
    if not args:
        return {"ok": False, "error": "usage: /send_media <chat_id> <optional caption>"}
    parts = args.split(None, 1)
    try:
        target = int(parts[0])
    except Exception:
        return {"ok": False, "error": "invalid chat_id"}
    caption = parts[1].strip() if len(parts) > 1 else None

    # if replied-to message has media/sticker
    if msg.get("reply_to_message"):
        replied = msg["reply_to_message"]
        if replied.get("photo"):
            fid = replied["photo"][-1].get("file_id")
            return send_photo(target, fid, caption=caption)
        if replied.get("video"):
            fid = replied["video"].get("file_id")
            return send_video(target, fid, caption=caption)
        if replied.get("sticker"):
            fid = replied["sticker"].get("file_id")
            return send_sticker(target, fid)
        return {"ok": False, "error": "replied message has no media/sticker"}

    # if current message contains media/sticker
    if msg.get("photo"):
        fid = msg["photo"][-1].get("file_id")
        return send_photo(target, fid, caption=caption)
    if msg.get("video"):
        fid = msg["video"].get("file_id")
        return send_video(target, fid, caption=caption)
    if msg.get("sticker"):
        fid = msg["sticker"].get("file_id")
        return send_sticker(target, fid)
    return {"ok": False, "error": "no media/sticker found"}

def cmd_sendtoalluser(admin_id: int, text: str) -> Dict[str, Any]:
    if not is_admin(admin_id):
        return {"ok": False, "error": "not admin"}
    if not text or not text.strip():
        return {"ok": False, "error": "no message"}
    d = load_store()
    chat_ids = d.get("seen_chats", [])
    sent = 0
    failed = 0
    failures = []
    for cid in chat_ids:
        try:
            r = send_message(cid, text)
            if r.get("ok"):
                sent += 1
            else:
                failed += 1
                failures.append({"chat_id": cid, "error": r})
        except Exception as exc:
            failed += 1
            failures.append({"chat_id": cid, "error": str(exc)})
        time.sleep(0.05)   # gentle pacing
    return {"ok": True, "sent": sent, "failed": failed, "failures": failures}

# -------------------- Webhook helper --------------------
def ensure_no_webhook() -> None:
    print("[startup] deleting webhook (if any)")
    print(api_request("deleteWebhook", {}))

# -------------------- Main loop --------------------
def main() -> None:
    ensure_no_webhook()
    print("[main] bot started")

    store = load_store()
    last_update_id = store.get("last_update_id")
    seen_chats = set(store.get("seen_chats", []))

    while True:
        try:
            params: Dict[str, Any] = {"timeout": 20}
            if last_update_id:
                params["offset"] = last_update_id + 1

            resp = api_request("getUpdates", params)
            if not resp.get("ok"):
                # handle webhook conflict gracefully
                if resp.get("code") == 409:
                    print("[main] 409 conflict - deleting webhook and retrying")
                    api_request("deleteWebhook", {})
                    time.sleep(1)
                    continue
                print("[main] getUpdates failed:", resp)
                time.sleep(POLL_INTERVAL)
                continue

            updates = resp.get("result", [])
            for upd in updates:
                last_update_id = max(last_update_id or 0, upd["update_id"])

                # callback queries (inline button presses)
                if "callback_query" in upd:
                    cq = upd["callback_query"]
                    cq_id = cq.get("id")
                    cq_from = cq.get("from", {}) or {}
                    cq_data = cq.get("data", "")

                    if cq_data.startswith("copyuid:"):
                        answer_callback(cq_id, text="User ID sent to your chat.")
                        try:
                            uid = cq_data.split(":", 1)[1]
                            send_message(cq_from.get("id"), uid)
                        except Exception:
                            send_message(cq_from.get("id"), "Failed to send user id.")
                        continue

                    if cq_data.startswith("prep_reply:"):
                        answer_callback(cq_id, text="Prepared reply command.")
                        try:
                            target = cq_data.split(":", 1)[1]
                            send_message(cq_from.get("id"), f"/reply {target} ")
                        except Exception:
                            send_message(cq_from.get("id"), "Failed to prepare reply.")
                        continue

                    if cq_data.startswith("prep_send_media:"):
                        answer_callback(cq_id, text="Prepared send_media command.")
                        try:
                            target = cq_data.split(":", 1)[1]
                            send_message(cq_from.get("id"), f"/send_media {target} ")
                        except Exception:
                            send_message(cq_from.get("id"), "Failed to prepare send_media.")
                        continue

                    # unknown callback
                    answer_callback(cq_id, text="Unknown action")
                    continue

                # normal message or edited_message
                msg = upd.get("message") or upd.get("edited_message")
                if not msg:
                    continue

                chat = msg.get("chat", {}) or {}
                chat_id = chat.get("id")
                from_user = msg.get("from", {}) or {}
                user_id = from_user.get("id")
                text = msg.get("text", "") or ""
                photos = msg.get("photo")
                video = msg.get("video")
                sticker = msg.get("sticker")
                caption = msg.get("caption", "") or ""

                # record chat id
                if chat_id:
                    seen_chats.add(chat_id)

                # ADMIN flows
                if is_admin(user_id):
                    # /send_sticker start flow
                    if text.strip().startswith("/send_sticker"):
                        parts = text.strip().split(None, 1)
                        if len(parts) < 2:
                            send_message(user_id, "Usage: /send_sticker <chat_id>")
                        else:
                            try:
                                target = int(parts[1])
                                set_pending_sticker(user_id, target)
                                send_message(user_id, f"OK — now send the sticker to forward to {target}. Use /cancel_sticker to cancel.")
                            except Exception:
                                send_message(user_id, "Invalid chat_id. Usage: /send_sticker <chat_id>")
                        continue

                    # cancel pending sticker
                    if text.strip().startswith("/cancel_sticker"):
                        prev = pop_pending_sticker(user_id)
                        if prev:
                            send_message(user_id, f"Pending sticker to {prev} cancelled.")
                        else:
                            send_message(user_id, "No pending sticker request.")
                        continue

                    # if admin sends a sticker and has a pending target -> forward and clear pending
                    if sticker:
                        pending = get_pending_sticker(user_id)
                        if pending:
                            fid = sticker.get("file_id")
                            res = send_sticker(pending, fid)
                            if res.get("ok"):
                                send_message(user_id, f"Sticker forwarded to {pending}.")
                                pop_pending_sticker(user_id)
                            else:
                                send_message(user_id, f"Failed to forward sticker: {res}")
                            continue
                        # else sticker may be reply-forward; handled below

                    # reply-to-admin-message mapping -> forward to user
                    if msg.get("reply_to_message"):
                        replied = msg["reply_to_message"]
                        replied_mid = replied.get("message_id")
                        target_chat = lookup_thread_target(user_id, replied_mid)
                        if target_chat:
                            forwarded = False
                            if text:
                                send_message(target_chat, text)
                                forwarded = True
                                send_message(user_id, f"Forwarded to user {target_chat}.")
                            if photos:
                                fid = photos[-1].get("file_id")
                                send_photo(target_chat, fid, caption=caption if caption else None)
                                forwarded = True
                                send_message(user_id, f"Photo forwarded to user {target_chat}.")
                            if video:
                                fid = video.get("file_id")
                                send_video(target_chat, fid, caption=caption if caption else None)
                                forwarded = True
                                send_message(user_id, f"Video forwarded to user {target_chat}.")
                            if sticker:
                                fid = sticker.get("file_id")
                                send_sticker(target_chat, fid)
                                forwarded = True
                                send_message(user_id, f"Sticker forwarded to user {target_chat}.")
                            if not forwarded:
                                send_message(user_id, "No forwardable content found in your reply.")
                            continue

                    # admin send_media flows
                    if ((photos or video or sticker) and caption.strip().startswith("/send_media")):
                        cmd_text = caption.strip()
                        res = cmd_send_media(user_id, msg, cmd_text[len("/send_media"):].strip())
                        if res.get("ok"):
                            send_message(user_id, "Media/sticker sent to target.")
                        else:
                            send_message(user_id, "Send media failed: " + (res.get("error") or "unknown"))
                        continue

                    if text.strip().startswith("/send_media"):
                        res = cmd_send_media(user_id, msg, text[len("/send_media"):].strip())
                        if res.get("ok"):
                            send_message(user_id, "Media/sticker sent to target.")
                        else:
                            send_message(user_id, "Send media failed: " + (res.get("error") or "unknown"))
                        continue

                    # /sendtoalluser
                    if text.strip().startswith("/sendtoalluser"):
                        payload = text.strip()[len("/sendtoalluser"):].strip()
                        res = cmd_sendtoalluser(user_id, payload)
                        if res.get("ok"):
                            send_message(user_id, f"Sent to {res.get('sent')} users; failed: {res.get('failed')}.")
                        else:
                            send_message(user_id, "sendtoalluser failed: " + (res.get("error") or "unknown"))
                        continue

                    # generic admin commands: /reply, /inbox, /broadcast, /help
                    if text.strip().startswith("/reply"):
                        res = cmd_reply(user_id, text.strip()[len("/reply"):].strip())
                        if res.get("ok"):
                            send_message(user_id, f"Message sent to {res.get('sent_to')}.")
                        else:
                            send_message(user_id, "Reply failed: " + (res.get("error") or "unknown"))
                        continue

                    if text.strip().startswith("/inbox"):
                        d = load_store()
                        inbox = d.get("inbox", [])[-20:]
                        if not inbox:
                            send_message(user_id, "Inbox is empty.")
                        else:
                            lines = [f"{fmt_time(e['ts'])} | user_id:{e['user_id']} | chat:{e['chat_id']} | {e.get('text','')[:60]}"
                                     for e in inbox]
                            send_message(user_id, "Last messages:\n" + "\n".join(lines))
                        continue

                    if text.strip().startswith("/broadcast"):
                        payload = text.strip()[len("/broadcast"):].strip()
                        if payload:
                            d = load_store()
                            count = 0
                            for cid in d.get("seen_chats", []):
                                r = send_message(cid, payload)
                                if r.get("ok"):
                                    count += 1
                                time.sleep(0.02)
                            send_message(user_id, f"Broadcast sent to ~{count} chats.")
                        else:
                            send_message(user_id, "Usage: /broadcast <message>")
                        continue

                    if text.strip().startswith("/help"):
                        send_message(user_id,
                                     "Admin commands:\n"
                                     "/reply <chat_id> <message>\n"
                                     "/send_media <chat_id> (reply to media or send media with caption)\n"
                                     "/send_sticker <chat_id>  -> then send the sticker\n"
                                     "/cancel_sticker\n"
                                     "/sendtoalluser <message>\n"
                                     "/inbox\n"
                                     "/broadcast <message>\n"
                                     "You can also reply to a forwarded message to send to the original user.")
                        continue

                    # if none matched, ignore or extend
                    continue

                # -------------------- NON-ADMIN (user) --------------------
                # simple user help
                if text.strip().startswith("/help"):
                    send_message(chat_id, "Commands:\n/start\n/help\n(You can message admin via this bot.)")
                    continue

                # store inbox entry (with small info)
                ts = now_ts()
                try:
                    d = load_store()
                    inbox = d.get("inbox", [])
                    inbox.append({
                        "ts": ts,
                        "chat_id": chat_id,
                        "user_id": user_id,
                        "text": text,
                        "username": from_user.get("username"),
                        "first_name": from_user.get("first_name"),
                        "last_name": from_user.get("last_name")
                    })
                    if len(inbox) > INBOX_LIMIT:
                        inbox = inbox[-INBOX_LIMIT:]
                    d["inbox"] = inbox
                    save_store(d)
                except Exception as exc:
                    print(f"[main] failed to store inbox: {exc}")

                # notify admins and forward any media/sticker
                notify_admins(chat_id, from_user, text, photos=photos, video=video, sticker=sticker)
                send_message(chat_id, "धन्यवाद — आपका संदेश पहुँच गया। Admin जल्द reply कर देगा।")
                continue

            # persist loop state
            store = load_store()
            store["last_update_id"] = last_update_id
            store["seen_chats"] = list(seen_chats)
            save_store(store)

        except KeyboardInterrupt:
            print("[main] interrupted by user")
            break
        except Exception as exc:
            err = str(exc)[:400]
            print(f"[main] exception: {err}")
            traceback.print_exc()
            if "409" in err or "Conflict" in err:
                print("[main] detected possible 409 conflict; deleting webhook")
                api_request("deleteWebhook", {})
            time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
