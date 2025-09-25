import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

# --- 1. ดึงค่า Keys จาก Render Environment Variables ---
# ใช้ os.environ.get เพื่อดึงค่าที่เราตั้งไว้บน Render (เพื่อความปลอดภัย)
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
# GEMINI_API_KEY ถูกดึงมาแล้ว แต่ยังไม่ถูกเรียกใช้จริงใน PoC นี้
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY') 

app = Flask(__name__)

# ตั้งค่า Line Bot Client
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# --- 2. End-point สำหรับ Webhook ---
# Line OA จะส่งข้อความมาที่ End-point นี้
@app.route("/callback", methods=['POST'])
def callback():
    # รับ X-Line-Signature header
    signature = request.headers['X-Line-Signature']

    # รับ Request body ทั้งหมด
    body = request.get_data(as_text=True)

    # จัดการ Webhook body และตรวจสอบลายเซ็น
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        # หากเกิด InvalidSignatureError ให้ Log และ Abort ด้วย 400
        print("Invalid signature. Please check your channel access token/secret.")
        abort(400)

    # สำคัญ: ต้องตอบกลับด้วย 'OK' และ HTTP Status 200
    return 'OK'

# --- 3. Logic การตอบกลับ (PoC) ---
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text # ข้อความที่ผู้ใช้พิมพ์เข้ามา

    # โค้ด PoC: ตอบกลับแบบง่ายๆ เพื่อยืนยันว่าระบบทำงานได้
    if user_message.lower() in ["สวัสดี", "hello"]:
        reply_text = "สวัสดีครับ! ผมคือ AI ผู้เชี่ยวชาญ DPIS6 ตอนนี้ระบบเชื่อมต่อสำเร็จแล้ว รอการติดตั้งสมองกล Gemini ที่อัปเกรดข้อมูลแล้วครับ"
    else:
        reply_text = "ผมได้รับข้อความของคุณแล้ว (PoC Success!)"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    # Render จะใช้ Environment Variable 'PORT' เพื่อรัน
    port = int(os.environ.get('PORT', 5000)) 
    app.run(host='0.0.0.0', port=port)
