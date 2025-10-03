import os
import json
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

# --- 1. ตั้งค่า Environment Variables (ต้องกำหนดใน Render) ---
app = Flask(__name__)
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
OPENAI_API_BASE_URL = os.environ.get('OPENAI_API_BASE_URL') # URL/IP ของ Open WebUI Server
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')           # API Key ที่กำหนดใน Open WebUI

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# --- 2. Webhook Endpoint ที่ Line จะเรียก ---
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

# --- 3. การจัดการข้อความ (Logic หลัก) ---
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
            print(f"Error processing AI response: {e}")
            # ส่งข้อความ Error กลับ (สำหรับ debug)
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="ขออภัยค่ะ ระบบ AI ขัดข้องชั่วคราว: " + str(e))
            )

# --- 4. ฟังก์ชันเชื่อมต่อ Open WebUI/Gemini ---
def get_ai_response(prompt):
    """ส่ง Prompt ไปยัง Open WebUI API และรับคำตอบ"""
    
    # Open WebUI มักต้องการ /api/v1/chat/completions
    url = f"{OPENAI_API_BASE_URL}/api/v1/chat/completions" 
  
    headers = {
        # ใช้ Key ที่ตั้งไว้ใน Open WebUI 
        "Authorization": f"Bearer {OPENAI_API_KEY}", 
        "Content-Type": "application/json"
    }
    
    payload = {
        # Model Name ต้องตรงกับ Model ID ที่ตั้งค่าไว้ใน Open WebUI
        "model": "gemini-2.5-flash",  
        "messages": [
            {"role": "system", "content": "คุณคือผู้ช่วยผู้เชี่ยวชาญด้านโปรแกรม DPIS6 กรุณาตอบคำถามอย่างกระชับและเป็นมิตร"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7 
    }
    
    response = requests.post(url, headers=headers, json=payload, timeout=30)
    response.raise_for_status() # ตรวจสอบสถานะ HTTP Error
    
    data = response.json()
    
    # ดึงข้อความจากโครงสร้าง Response ของ OpenAI-compatible API
    ai_text = data['choices'][0]['message']['content']
    
    return ai_text

# --- 5. สำหรับรันบน Render ---
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
