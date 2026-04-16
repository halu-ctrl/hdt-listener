import os
import time
import threading
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
PERPLEXITY_API_KEY = os.environ.get("PERPLEXITY_API_KEY")
HALU_USER_ID = "U0235EQ8M7G"

processed_events = set()

def slack_post_message(channel_id, thread_ts, text):
    resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={
            "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
            "Content-Type": "application/json"
        },
        json={
            "channel": channel_id,
            "thread_ts": thread_ts,
            "text": text
        }
    )
    result = resp.json()
    print(f"[DEBUG] chat.postMessage result: ok={result.get('ok')} error={result.get('error')}")
    return result

def call_perplexity(channel_id, thread_ts, sender_id, message_text):
    prompt = f"""你是 Halu Digital Twin（HDT），VITABOX® 與 Rill® 創辦人 Halu 的數位分身。

有人在 Slack tag 了 Halu，請起草一則回覆。

發送者 UserID: {sender_id}
訊息內容: {message_text}

請起草回覆，格式：
HDT
<@{sender_id}>

[回覆內容]

規則：
- 口語、直接、有溫度
- 用「我們」為主體
- 最多 2 個 emoji
- 不加「Sent using @Computer」
- 純知會型：溫暖簡短 1-2 句
- 合約/大額支出/人事：回「收到，我確認後回你。」"""

    resp = requests.post(
        "https://api.perplexity.ai/chat/completions",
        headers={
            "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": "sonar",
            "messages": [{"role": "user", "content": prompt}]
        }
    )
    result = resp.json()
    print(f"[DEBUG] Perplexity ok={result.get('id', 'no-id')}")

    choices = result.get("choices") or []
    if not choices:
        print(f"[DEBUG] No choices in response: {str(result)[:300]}")
        return

    reply_text = choices[0].get("message", {}).get("content", "")
    print(f"[DEBUG] reply_text length={len(reply_text)}")

    if reply_text:
        slack_post_message(channel_id, thread_ts, reply_text)

def handle_event(channel_id, thread_ts, sender_id, message_text):
    time.sleep(1)
    call_perplexity(channel_id, thread_ts, sender_id, message_text)

@app.route("/slack/events", methods=["POST"])
def slack_events():
    body = request.get_json()

    if body.get("type") == "url_verification":
        return jsonify({"challenge": body["challenge"]})

    event = body.get("event", {})
    event_type = event.get("type")
    event_id = body.get("event_id", "")

    print(f"[DEBUG] event_type={event_type} sender={event.get('user')} text={event.get('text','')[:80]}")

    if event_id in processed_events:
        print(f"[DEBUG] Duplicate event, skipping")
        return jsonify({"ok": True})
    processed_events.add(event_id)
    if len(processed_events) > 500:
        processed_events.clear()

    if event_type == "app_mention":
        sender_id = event.get("user")
        if event.get("bot_id") or sender_id == HALU_USER_ID:
            return jsonify({"ok": True})

        channel_id = event.get("channel")
        thread_ts = event.get("thread_ts") or event.get("ts")
        message_text = event.get("text", "")

        t = threading.Thread(target=handle_event, args=(channel_id, thread_ts, sender_id, message_text))
        t.daemon = True
        t.start()

    return jsonify({"ok": True})

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
