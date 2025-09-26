import os
import google.generativeai as genai
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

# --- 1. Load Environment Variables from Render ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

if not all([LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET, GEMINI_API_KEY]):
    raise ValueError("One or more environment variables are not set.")

# --- 2. Initialize Flask and Line Bot API ---
app = Flask(__name__)
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# --- 3. Configure Gemini AI ---
genai.configure(api_key=GEMINI_API_KEY)
# Use Gemini 2.5 Flash-Lite model
model = genai.GenerativeModel('models/gemini-2.5-flash-lite') 

# --- 4. Define the Webhook endpoint ---
@app.route("/", methods=['POST'])
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

# --- 5. Handle incoming text messages ---
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text
    print(f"User message received: {user_message}")

    try:
        # Use Gemini to generate a response
        response = model.generate_content(user_message)
        ai_response = response.text
    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        ai_response = "ขออภัยค่ะ ขณะนี้ระบบ AI ขัดข้อง กรุณาลองใหม่อีกครั้งค่ะ"

    # Reply to the user
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=ai_response)
    )

# --- 6. Run the Flask app ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))
