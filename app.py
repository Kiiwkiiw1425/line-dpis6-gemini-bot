import os
import json
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

# --- 1. ตั้งค่า Environment Variables (ต้องกำหนดใน Render) ---
app = Flask(__name__)
# ตรวจสอบว่าได้ตั้งค่า 3 ตัวแปรนี้บน Render แล้ว
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
# นี่คือ IP Address ภายในที่ได้รับอนุญาตจาก Firewall
OPENAI_API_BASE_URL = os.environ.get('OPENAI_API_BASE_URL') 
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')           

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
            # บันทึกข้อผิดพลาดที่เกิดขึ้น
            error_message = f"Error processing AI response: {e}"
            print(error_message)
            # ส่งข้อความ Error กลับ (สำหรับ debug)
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="ขออภัยค่ะ ระบบ AI ขัดข้องชั่วคราว: " + str(e))
            )

# --- 4. ฟังก์ชันเชื่อมต่อ Open WebUI/Gemini ---
def get_ai_response(prompt):
    """ส่ง Prompt ไปยัง Open WebUI API และรับคำตอบ"""
    
    # Path ที่เป็นไปได้สำหรับ Open WebUI
    possible_endpoints = [
        "/v1/chat/completions",         # 1. Path มาตรฐาน (OpenAI API Compatible)
        "/api/v1/chat/completions"      # 2. Path ที่มี /api/ นำหน้า
    ]

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}", 
        "Content-Type": "application/json"
    }
    
    payload = {
        # ยืนยันว่า Model นี้ถูกตั้งค่าใน Open WebUI Server ของคุณแล้ว
        "model": "gemini-2.5-flash", 
        "messages": [
            {"role": "system", "content": "คุณคือผู้ช่วยผู้เชี่ยวชาญด้านโปรแกรม DPIS6 กรุณาตอบคำถามอย่างกระชับและเป็นมิตร"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7 
    }
    
    last_exception = None

    for endpoint in possible_endpoints:
        url = f"{OPENAI_API_BASE_URL}{endpoint}"
        
        try:
            print(f"Attempting to call URL: {url}")
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status() # ตรวจสอบสถานะ HTTP Error (2xx)
            
            data = response.json()
            # ถ้าสำเร็จ ให้ออกจากลูปและคืนค่า
            ai_text = data['choices'][0]['message']['content']
            return ai_text
            
        except requests.exceptions.RequestException as e:
            # บันทึก exception ล่าสุด เผื่อไว้แสดง error
            last_exception = e
            print(f"Failed attempt on {url}: {e}")
            # ถ้าเป็น 404/403 ให้ลอง endpoint ถัดไป
            if response.status_code in [403, 404]:
                continue
            else:
                # ถ้าเป็น error อื่นที่ไม่ใช่ 403/404 อาจเป็นปัญหาใหญ่ ให้หยุดลอง
                raise

    # ถ้าลองทุก endpoint แล้วไม่สำเร็จ ให้แสดง exception ล่าสุดที่เกิดขึ้น
    if last_exception:
        raise last_exception
    else:
        # กรณีที่ไม่มี exception แต่ไม่ได้รับคำตอบที่ถูกต้อง
        raise Exception("API connection failed after trying all endpoints.")


# --- 5. สำหรับรันบน Render ---
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
