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
PERPLEXITY_API_KEY = os.environ.get("PERPLEXITY_API_KEY")

HALU_USER_ID = "U0235EQ8M7G"
KELLY_USER_ID = "U02L5GLTL1Y"

processed_events = set()

def slack_get(endpoint, params):
    resp = requests.get(
        f"https://slack.com/api/{endpoint}",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
        params=params
    )
    return resp.json()

def slack_post(endpoint, data):
    resp = requests.post(
        f"https://slack.com/api/{endpoint}",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}", "Content-Type": "application/json"},
        json=data
    )
    return resp.json()

def read_thread(channel_id, thread_ts):
    result = slack_get("conversations.replies", {"channel": channel_id, "ts": thread_ts, "limit": 100})
    return result.get("messages", [])

def should_reply(messages):
    halu_msgs = [m for m in messages if m.get("user") == HALU_USER_ID]
    other_msgs = [m for m in messages
                  if m.get("user") != HALU_USER_ID
                  and not m.get("text", "").startswith("HDT")
                  and not m.get("bot_id")]

    if not other_msgs:
        return False

    last_other_ts = max(float(m["ts"]) for m in other_msgs)
    last_halu_ts = max((float(m["ts"]) for m in halu_msgs), default=0)

    return last_other_ts > last_halu_ts

def call_perplexity_agent(channel_id, thread_ts, sender_id, message_text, thread_messages):
    """用 Perplexity Sonar 模型起草回覆，直接用 Slack API 發送"""

    # 整理 thread 脈絡
    context = "\n".join([
        f"[{m.get('user', 'unknown')}] {m.get('text', '')}"
        for m in thread_messages[-10:]  # 最近 10 則
    ])

    prompt = f"""你是 Halu Digital Twin（HDT），VITABOX® 與 Rill® 創辦人 Halu 的數位分身。

有人在 Slack tag 了 Halu，請起草一則回覆。

發送者 UserID: {sender_id}
訊息內容: {message_text}

Thread 脈絡（最近幾則）:
{context}

請起草回覆，格式：
HDT
<@{sender_id}>

[回覆內容]

規則：
- 口語、直接、有溫度，讓人工作有趣
- 用「我們」為主體
- 避免「不是…而是…」「支持」「節奏」「接住」「撐得過」「話術」
- 最多 2 個 emoji
- 不加「Sent using @Computer」
- 純知會型訊息：溫暖簡短 1-2 句即可
- 合約/大額支出/人事決策：回「收到，我確認後回你。」"""

    headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "sonar",
        "messages": [{"role": "user", "content": prompt}]
    }

    resp = requests.post("https://api.perplexity.ai/chat/completions", headers=headers, json=data)
    result = resp.json()

    reply_text = result.get("choices", [{}])[0].get("message", {}).get("content", "")

    if reply_text:
        slack_post("chat.postMessage", {
            "channel": channel_id,
            "thread_ts": thread_ts,
            "text": reply_text
        })

def handle_mention(event, channel_id, thread_ts, sender_id, message_text):
    time.sleep(2)  # 等一下避免重複觸發

    messages = read_thread(channel_id, thread_ts)

    if should_reply(messages):
        call_perplexity_agent(channel_id, thread_ts, sender_id, message_text, messages)

@app.route("/slack/events", methods=["POST"])
def slack_events():
    body = request.get_json()

    # URL verification
    if body.get("type") == "url_verification":
        return jsonify({"challenge": body["challenge"]})

    event = body.get("event", {})
    event_type = event.get("type")
    event_id = body.get("event_id", "")

    # 去重
    if event_id in processed_events:
        return jsonify({"ok": True})
    processed_events.add(event_id)
    if len(processed_events) > 1000:
        processed_events.clear()

    if event_type == "app_mention":
        channel_id = event.get("channel")
        thread_ts = event.get("thread_ts") or event.get("ts")
        sender_id = event.get("user")
        message_text = event.get("text", "")

        # 忽略 bot 和 Halu 自己
        if event.get("bot_id") or sender_id == HALU_USER_ID:
            return jsonify({"ok": True})

        t = threading.Thread(
            target=handle_mention,
            args=(event, channel_id, thread_ts, sender_id, message_text)
        )
        t.daemon = True
        t.start()

    return jsonify({"ok": True})

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "timestamp": time.time()})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
