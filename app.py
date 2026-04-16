import os
import json
import hmac
import hashlib
import time
import threading
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET")
PERPLEXITY_SPACE_ID = os.environ.get("PERPLEXITY_SPACE_ID")
PERPLEXITY_API_KEY = os.environ.get("PERPLEXITY_API_KEY")

HALU_USER_ID = "U0235EQ8M7G"

def verify_slack_signature(request):
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    if abs(time.time() - int(timestamp)) > 300:
        return False
    sig_basestring = f"v0:{timestamp}:{request.get_data(as_text=True)}"
    my_signature = "v0=" + hmac.new(
        SLACK_SIGNING_SECRET.encode(),
        sig_basestring.encode(),
        hashlib.sha256
    ).hexdigest()
    slack_signature = request.headers.get("X-Slack-Signature", "")
    return hmac.compare_digest(my_signature, slack_signature)

def read_thread(channel_id, thread_ts):
    resp = requests.get(
        "https://slack.com/api/conversations.replies",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
        params={"channel": channel_id, "ts": thread_ts, "limit": 100}
    )
    return resp.json().get("messages", [])

def should_reply(messages):
    halu_msgs = [m for m in messages if m.get("user") == HALU_USER_ID]
    other_msgs = [m for m in messages if m.get("user") != HALU_USER_ID and not m.get("text", "").startswith("HDT")]

    if not other_msgs:
        return False

    last_other_ts = max(float(m["ts"]) for m in other_msgs)
    last_halu_ts = max((float(m["ts"]) for m in halu_msgs), default=0)

    return last_other_ts > last_halu_ts

def trigger_hdt(channel_id, thread_ts, sender_id, message_text):
    """呼叫 Perplexity Computer API 觸發 HDT 回覆"""
    if not PERPLEXITY_API_KEY:
        return

    prompt = f"""你是 Halu Digital Twin（HDT），VITABOX® 與 Rill® 創辦人 Halu 的數位分身。

有人在 Slack tag 了 Halu，請立即處理這則訊息並回覆。

訊息資訊：
- Channel ID: {channel_id}
- Thread TS: {thread_ts}
- 發送者 UserID: {sender_id}
- 訊息內容: {message_text}

請依照以下步驟處理：
1. 用 slack_read_thread 讀取 channel_id={channel_id}, message_ts={thread_ts} 的完整 thread
2. 判斷是否需要 HDT 回覆（last_other_ts > last_halu_ts）
3. 若需要，查詢 BS/BSS/EOS Agent Index，起草並用 slack_send_message 回覆

Halu/HDT user_id: U0235EQ8M7G
Kelly user_id: U02L5GLTL1Y
BS Agent Index: https://www.notion.so/3382322c59b481d687a6f3aeda1d1bc2
BSS Agent Index: https://www.notion.so/3382322c59b481dbb037d18aa1938939
EOS Agent Index: https://www.notion.so/3402322c59b4814b8be8df8d5adda720

回覆格式：
HDT
<@發送者UserID>

[回覆內容]

規則：口語直接有溫度，用「我們」為主體，最多 2 個 emoji，不加「Sent using @Computer」"""

    # 呼叫 Perplexity API
    headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "sonar",
        "messages": [{"role": "user", "content": prompt}]
    }
    requests.post("https://api.perplexity.ai/chat/completions", headers=headers, json=data)

def handle_event_async(event, channel_id, thread_ts, sender_id, message_text):
    time.sleep(1)  # 避免重複觸發

    # 讀完整 thread 判斷是否需要回覆
    messages = read_thread(channel_id, thread_ts)
    if should_reply(messages):
        trigger_hdt(channel_id, thread_ts, sender_id, message_text)

@app.route("/slack/events", methods=["POST"])
def slack_events():
    # URL verification
    body = request.get_json()
    if body.get("type") == "url_verification":
        return jsonify({"challenge": body["challenge"]})

    # 驗證簽名
    # if not verify_slack_signature(request):
    #     return jsonify({"error": "Invalid signature"}), 403

    event = body.get("event", {})
    event_type = event.get("type")

    # 只處理 app_mention
    if event_type == "app_mention":
        channel_id = event.get("channel")
        thread_ts = event.get("thread_ts") or event.get("ts")
        sender_id = event.get("user")
        message_text = event.get("text", "")

        # 忽略 bot 訊息和 HDT 自己的訊息
        if event.get("bot_id") or sender_id == HALU_USER_ID:
            return jsonify({"ok": True})

        # 非同步處理，立即回傳 200
        t = threading.Thread(
            target=handle_event_async,
            args=(event, channel_id, thread_ts, sender_id, message_text)
        )
        t.daemon = True
        t.start()

    return jsonify({"ok": True})

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
