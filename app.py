import os
import json
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

# --- 1. ตั้งค่า Environment Variables (ต้องกำหนดใน Render) ---
app = Flask(__name__)
# *** FIX: เพิ่ม .strip() เพื่อตัดช่องว่างที่อาจติดมากับ ENV VARS ***
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN').strip() if os.environ.get('LINE_CHANNEL_ACCESS_TOKEN') else None
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET').strip() if os.environ.get('LINE_CHANNEL_SECRET') else None
OPENAI_API_BASE_URL = os.environ.get('OPENAI_API_BASE_URL').strip() if os.environ.get('OPENAI_API_BASE_URL') else None
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY').strip() if os.environ.get('OPENAI_API_KEY') else None

# ตรวจสอบว่าตัวแปรสำคัญถูกโหลดแล้ว
if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_CHANNEL_SECRET or not OPENAI_API_BASE_URL or not OPENAI_API_KEY:
    print("FATAL: One or more critical environment variables (LINE_CHANNEL_ACCESS_TOKEN, LINE_CHANNEL_SECRET, OPENAI_API_BASE_URL, OPENAI_API_KEY) are missing or empty.")
    # ไม่ abort ในตอนนี้ แต่จะไปแจ้ง error ที่ LINE แทน

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
            # --- โลจิกใหม่: ตรวจสอบ Outbound Connection ถ้าผู้ใช้พิมพ์ /check ---
            if user_message.strip().lower() == '/check':
                result = check_outbound_connection()
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text=result)
                )
                return # หยุดการทำงานไม่ให้ไปเรียก AI
            # -----------------------------------------------------------------

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

# --- 4. ฟังก์ชันเชื่อมต่อ Open WebUI/Gemini ---
def get_ai_response(prompt):
    """ส่ง Prompt ไปยัง Open WebUI API และรับคำตอบ"""

    # ตรวจสอบ Key ก่อนส่ง Request
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is missing. Cannot proceed with API call.")
        
    # 1. กำหนด Header โดยใช้ Authorization: Bearer
    # *** FIX: .strip() ถูกใช้ตั้งแต่ตอนดึงค่าแล้ว ทำให้แน่ใจว่า Key สะอาด ***
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}" 
    }
    
    # 2. URL สำหรับ OpenAI-compatible API
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

# --- 5. ฟังก์ชันสำหรับตรวจสอบ Outbound Connection (Firewall Test) ---
def check_outbound_connection():
    """
    ทดสอบว่า Render สามารถเชื่อมต่อออกไปยังเว็บไซต์ภายนอกที่เป็นที่รู้จักได้หรือไม่
    เพื่อวินิจฉัยปัญหา Firewall ขาออก
    """
    test_url = "https://www.google.com"
    try:
        response = requests.get(test_url, timeout=10)
        
        if response.status_code == 200:
            return f"✅ การเชื่อมต่อขาออก (Outbound) ไปยัง {test_url} สำเร็จ (รหัส 200)\n\nข้อสรุป: Render ไมได้บล็อกการเชื่อมต่อภายนอกทั่วไป ปัญหาน่าจะจำกัดอยู่ที่ URL ของ Open WebUI เท่านั้น"
        else:
            return f"⚠️ การเชื่อมต่อขาออก (Outbound) ไปยัง {test_url} ล้มเหลว (รหัส {response.status_code})\n\nข้อสรุป: มีปัญหาการเชื่อมต่อขาออกของ Render ทั่วไป"
            
    except requests.exceptions.RequestException as e:
        return f"❌ การเชื่อมต่อขาออก (Outbound) ล้มเหลวโดยสมบูรณ์: {e}\n\nข้อสรุป: Render อาจถูกจำกัด Firewall ขาออก หรือมีปัญหา DNS/Network (ต้องติดต่อ Support ของ Render)"


# --- 6. สำหรับรันบน Render ---
if __name__ == "__main__":
    # ตรวจสอบว่าตัวแปรสำคัญถูกโหลดแล้วหรือไม่
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_CHANNEL_SECRET or not OPENAI_API_BASE_URL or not OPENAI_API_KEY:
        print("Starting app but critical ENV VARs are missing. Responses in Line may fail.")
        
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
