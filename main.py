import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
# นำเข้า Library ตัวล่าสุดสำหรับ Gemini API
import google.generativeai as genai

# --- 1. ดึงค่า Keys จาก Render Environment Variables ---
# ใช้ os.environ.get เพื่อดึงค่าที่เราตั้งไว้บน Render (เพื่อความปลอดภัย)
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY') 

app = Flask(__name__)

# ตั้งค่า Line Bot Client
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# --- กำหนด System Instruction ที่ใช้ในการตั้งค่า AI ---
# ข้อมูล DPIS ที่ท่านเพิ่มมาจะถูกนำไปใช้ในขั้นตอนนี้
SYSTEM_PROMPT = (
    "คุณคือ AI ผู้เชี่ยวชาญด้าน ระบบ DPIS ย่อมาจาก Departmental Personnel Information System (ระบบสารสนเทศทรัพยากรบุคคลระดับกรม) "
    "เป็นโปรแกรมที่พัฒนาโดย สำนักงาน ก.พ. เพื่อใช้บริหารจัดการข้อมูลข้าราชการ ลูกจ้างประจำ และพนักงานราชการในหน่วยงานระดับกรม "
    "โดยระบบนี้ช่วยจัดเก็บข้อมูล จัดการงานบุคคล และบูรณาการข้อมูลกับส่วนราชการอื่น ๆ ผ่าน API รวมถึงมีฟังก์ชันการแจ้งเตือนสำหรับกระบวนการต่าง ๆ "
    "เช่น การลาหรือการประเมินผลการปฏิบัติราชการ. "
    "หน้าที่และวัตถุประสงค์ของระบบ DPIS "
    "บริหารจัดการข้อมูลบุคลากร: จัดเก็บข้อมูลส่วนตัว ประวัติการทำงาน การลา การประเมินผลการปฏิบัติราชการ และข้อมูลอื่น ๆ ที่เกี่ยวข้องกับทรัพยากรบุคคล. "
    "สนับสนุนงานบริหารบุคคล: เป็นเครื่องมือช่วยในการวางแผนอัตรากำลังคน การบริหารงานบุคคล และการดำเนินการตามกฎหมายและระเบียบต่าง ๆ ที่เกี่ยวข้อง. "
    "บูรณาการข้อมูล: เชื่อมโยงและแลกเปลี่ยนข้อมูลบุคลากรกับส่วนราชการอื่น ๆ และ สำนักงาน ก.พ. เพื่อสร้างฐานข้อมูลกลางที่มีประสิทธิภาพ. "
    "แจ้งเตือนและอำนวยความสะดวก: ระบบมีการแจ้งเตือนในกระบวนการต่างๆ เช่น การยื่นขอลา การแจ้งผลการประเมิน ทำให้บุคลากรได้รับข้อมูลที่ทันท่วงทีและปฏิบัติงานได้อย่างมีประสิทธิภาพ. "
    "การเข้าใช้งานระบบ DPIS "
    "ผู้ใช้งานสามารถเข้าสู่ระบบ DPIS ผ่านเว็บเบราว์เซอร์ โดยพิมพ์ URL ที่กำหนดสำหรับหน่วยงานของตนเอง และกรอก Username และ Password เพื่อเข้าสู่ระบบ. "
    "จงตอบคำถามผู้ใช้ด้วยข้อมูลที่ถูกต้องและกระชับ"
)

# --- ตั้งค่า Gemini API ---
# เราจะตรวจสอบว่ามี API Key อยู่หรือไม่ ก่อนทำการตั้งค่า
gemini_model = None
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        # ใช้โมเดล gemini-1.5-flash ซึ่งเหมาะกับการตอบกลับที่รวดเร็ว
        gemini_model = genai.GenerativeModel('gemini-1.5-flash', system_instruction=SYSTEM_PROMPT)
    except Exception as e:
        print(f"Error configuring Gemini API: {e}")

# --- 2. Health Check Endpoint สำหรับ Kuma Ping ---
# End-point นี้จะตอบกลับด้วย 'OK' ทันทีเมื่อถูกเรียก
@app.route("/", methods=['GET'])
def home():
    return 'OK', 200

# --- 3. Webhook Endpoint ---
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
        print("Invalid signature. Please check your channel access token/secret.")
        abort(400)

    # ต้องตอบกลับด้วย 'OK' และ HTTP Status 200
    return 'OK'

# --- 4. Logic การตอบกลับ (ใช้ Gemini API) ---
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text
    reply_text = "ขออภัยครับ ระบบ AI ไม่สามารถใช้งานได้ในขณะนี้" # ข้อความ Default

    if gemini_model: # ตรวจสอบว่าโมเดลถูกตั้งค่าสำเร็จหรือไม่
        try:
            # ส่งคำถามของผู้ใช้ไปให้ Gemini ประมวลผล
            response = gemini_model.generate_content(user_message)
            if response.text:
                reply_text = response.text
        except Exception as e:
            print(f"Gemini API Error: {e}")
            reply_text = "ขออภัยครับ เกิดข้อผิดพลาดในการเรียกใช้บริการ AI"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    # Render จะใช้ Environment Variable 'PORT' เพื่อรัน
    port = int(os.environ.get('PORT', 5000)) 
    app.run(host='0.0.0.0', port=port)
