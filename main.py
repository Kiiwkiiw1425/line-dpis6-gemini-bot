import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from google import genai
from google.genai.errors import APIError

# --- 1. ดึงค่า Keys จาก Render Environment Variables ---
# Use os.environ.get to get values from Render (for security)
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY') 

app = Flask(__name__)

# Set up Line Bot Client
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# Use GEMINI_API_KEY from Environment Variable
try:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel('gemini-1.5-pro-latest')
except ValueError as e:
    print(f"Error configuring Gemini API: {e}")
    gemini_model = None

# --- 2. Health Check Endpoint for Kuma Ping ---
# This endpoint will immediately return 'OK' when called.
@app.route("/", methods=['GET'])
def home():
    return 'OK', 200

# --- 3. Webhook Endpoint ---
# Line OA sends messages to this endpoint
@app.route("/callback", methods=['POST'])
def callback():
    # Get X-Line-Signature header
    signature = request.headers['X-Line-Signature']

    # Get the entire Request body
    body = request.get_data(as_text=True)

    # Handle Webhook body and verify signature
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("Invalid signature. Please check your channel access token/secret.")
        abort(400)

    # Must return 'OK' and HTTP Status 200
    return 'OK'

# --- 4. Message Reply Logic (Using Gemini API) ---
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text
    reply_text = "ขออภัยครับ ระบบ AI ไม่สามารถใช้งานได้ในขณะนี้"

    if gemini_model is not None:
        try:
            # 1. Define System Instruction (Set AI's persona)
            system_prompt = (
                "คุณคือ AI ผู้เชี่ยวชาญด้าน Line OA ที่มีบุคลิกสุภาพ และเป็นทางการ "
                "จงตอบคำถามผู้ใช้ด้วยข้อมูลที่ถูกต้องและกระชับ"
            )

            # 2. Send the question to Gemini for processing
            response = gemini_model.generate_content(
                f"{system_prompt}\n\nUser's question: {user_message}"
            )
            
            # 3. Get the answer
            reply_text = response.text
            
        except Exception as e:
            print(f"An error occurred: {e}")
            reply_text = "ขออภัยครับ เกิดข้อผิดพลาดในการเรียกใช้บริการ AI"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    # Render will use the 'PORT' Environment Variable to run
    port = int(os.environ.get('PORT', 5000)) 
    app.run(host='0.0.0.0', port=port)
