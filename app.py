import os
import json
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

# --- ตั้งค่า Environment Variables (กำหนดค่าใน Render) ---
app = Flask(__name__)
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')

# URL/IP ของ Open WebUI Server 
OPENAI_API_BASE_URL = os.environ.get('OPENAI_API_BASE_URL') 

# API Key ที่กำหนดใน Open WebUI
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')           

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# --- Health Check Endpoint เพื่อป้องกันการ Sleep บน Render ---
@app.route("/ping", methods=['GET'])
def health_check():
    """
    Endpoint นี้ถูกสร้างขึ้นเพื่อให้ Uptime Kuma เรียกใช้ เพื่อตรวจสอบสถานะ
    และป้องกันไม่ให้ Render เข้าสู่สถานะ Idle (Sleep)
    """
    return 'OK', 200

# --- Webhook Endpoint ที่ Line จะเรียก ---
@app.route("/webhook", methods=['POST'])
def webhook():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("Invalid signature. Please check your channel access token/secret.")
        abort(400)

    return 'OK'

# --- การจัดการข้อความ (Logic หลัก) ---
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text

    # ถ้าผู้ใช้เป็นคนพิมพ์มา (ไม่ใช่ bot)
    if event.source.type == 'user':
        try:
            # *********** LOGIC การเรียก Open WebUI ***********
            ai_response = get_ai_response(user_message)

            # ส่งข้อความกลับไปหาผู้ใช้ผ่าน Line
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=ai_response)
            )

        except Exception as e:
            # รายงาน Error กลับไปเพื่อให้ผู้ใช้ทราบถึงปัญหา
            print(f"Error processing AI response: {e}")
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="ขออภัยค่ะ ระบบ AI ขัดข้องชั่วคราว: " + str(e))
            )

# --- ฟังก์ชันเชื่อมต่อ Open WebUI/Gemini ---
    def get_ai_response(prompt):
    """ส่ง Prompt ไปยัง Open WebUI API และรับคำตอบ"""

    # กำหนด Header โดยใช้ Authorization: Bearer
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}" # ส่ง API Key ผ่าน Header
    }
    
    # URL สำหรับ OpenAI-compatible API
    url = f"{OPENAI_API_BASE_URL}/api/v1/chat/completions"

    payload = {
        # Model ID ต้องตรงกับที่ตั้งค่าไว้ใน Open WebUI
        "model": "hrms-dpis6",
        "messages": [
            {"role": "system", "content": "คุณคือผู้ช่วยผู้เชี่ยวชาญด้านโปรแกรม DPIS6 กรุณาตอบคำถามอย่างกระชับและเป็นมิตร"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.5
    }

    # ส่ง request พร้อม headers ใหม่
    response = requests.post(url, headers=headers, json=payload, timeout=30)
    response.raise_for_status() # ตรวจสอบสถานะ HTTP Error (ถ้าไม่ใช่ 200 จะเกิด Exception)

    data = response.json()

    # ดึงข้อความจากโครงสร้าง Response ของ OpenAI-compatible API
    ai_text = data['choices'][0]['message']['content']

    return ai_text

# --- สำหรับรันบน Render ---
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
