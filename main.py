import os
import json
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

# --- 1. Load Environment Variables from Render ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
OPEN_WEBUI_API_URL = os.environ.get('OPEN_WEBUI_API_URL')
OPEN_WEBUI_API_KEY = os.environ.get('OPEN_WEBUI_API_KEY')

if not all([LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET, OPEN_WEBUI_API_URL, OPEN_WEBUI_API_KEY]):
    raise ValueError("One or more environment variables are not set. Check for LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET, OPEN_WEBUI_API_URL, and OPEN_WEBUI_API_KEY.")

# --- 2. Initialize Flask and Line Bot API ---
app = Flask(__name__)
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# --- 3. Define the Webhook endpoint ---
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.info("Invalid signature. Please check your channel access token/secret.")
        abort(400)
    
    return 'OK'

# --- 4. Handle incoming text messages ---
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text
    print(f"User message received: {user_message}")

    try:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPEN_WEBUI_API_KEY}"
        }
        
        payload = {
            "model": "gemini-2.5-flash-lite",
            "messages": [
                {
                    "role": "user",
                    "content": user_message
                }
            ],
            "stream": False
        }
        
        response = requests.post(OPEN_WEBUI_API_URL, headers=headers, data=json.dumps(payload))
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        
        ai_response = response.json()["choices"][0]["message"]["content"]

    except requests.exceptions.RequestException as e:
        print(f"Error calling Open WebUI API: {e}")
        ai_response = "ขออภัยค่ะ ขณะนี้ระบบ AI ขัดข้อง กรุณาลองใหม่อีกครั้งค่ะ"
    except (KeyError, IndexError) as e:
        print(f"Error parsing JSON from Open WebUI: {e}")
        ai_response = "ขออภัยค่ะ ขณะนี้ระบบ AI มีปัญหา กรุณาลองใหม่อีกครั้งค่ะ"

    # Reply to the user
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=ai_response)
    )

# --- 5. Add a root route for health check ---
@app.route("/", methods=['GET'])
def health_check():
    return 'Your service is running!', 200

# --- 6. Run the Flask app ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))
