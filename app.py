import os
import json
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
# 💡 เพิ่ม Imports สำหรับ Firestore และ Line Events และ Quick Replies
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, FollowEvent, 
    PostbackEvent, QuickReply, QuickReplyButton, MessageAction
)
# 💡 เพิ่ม Imports สำหรับ Firestore
from google.cloud.firestore import Client as FirestoreClient
import difflib # 💡 Library สำหรับการค้นหาคำที่ใกล้เคียง (Fuzzy Search)

# --- ข้อมูลกรม/ส่วนราชการ (ต้องมี 148 รายการ) ---
# NOTE: ใน Production ควรดึงมาจากฐานข้อมูลหรือไฟล์ภายนอก
THAI_DEPARTMENTS = [
    "สำนักงานปลัดกระทรวงการคลัง",
    "กรมสรรพากร",
    "กรมศุลกากร",
    "กรมธนารักษ์",
    "กรมควบคุมโรค",
    "กรมส่งเสริมการเกษตร",
    "กรมปศุสัตว์",
    "สำนักงาน ก.พ.",
    "สำนักเลขาธิการคณะรัฐมนตรี",
    "สำนักงบประมาณ",
    # 📌 กรุณาใส่ชื่อกรมทั้งหมด 148 รายการของคุณที่นี่
]

# --- ชื่อย่อสำหรับแสดงผลใน Quick Replies (ถ้าชื่อยาวเกินไป) ---
# ชื่อเต็ม: ชื่อย่อสำหรับปุ่ม
THAI_DEPARTMENT_ALIAS = {
    "สำนักงานปลัดกระทรวงการคลัง": "ปลัดกระทรวงการคลัง",
    "สำนักงานคณะกรรมการกำกับและส่งเสริมการประกอบธุรกิจประกันภัย": "คปภ.",
    "สำนักงานคณะกรรมการส่งเสริมสวัสดิการและสวัสดิภาพครูและบุคลากรทางการศึกษา": "สกสค.",
    "สำนักงานคณะกรรมการพัฒนาระบบราชการ": "ก.พ.ร.",
    "สำนักงานคณะกรรมการคุ้มครองข้อมูลส่วนบุคคล": "สคส.",
    # 📌 เพิ่มชื่อย่อสำหรับกรมที่มีชื่อยาวที่นี่
}
# -----------------------------------------------

# --- Firebase Initialization (ต้องใช้เพื่อเก็บสถานะ) ---
# NOTE: โค้ดนี้ใช้สำหรับการเชื่อมต่อ Google Cloud Firestore Client
try:
    # 💡 ใช้ Global Variables ที่ Canvas เตรียมไว้
    firebase_config = json.loads(os.environ.get('__firebase_config', '{}'))
    app_id = os.environ.get('__app_id', 'default-app-id')
    
    if firebase_config:
        # หากเชื่อมต่อได้ (ใน Canvas Environment) ให้ใช้ Firestore Client
        db = FirestoreClient()
    else:
        # Fallback หากรันนอก Canvas Environment ที่ไม่มี config
        db = None
        print("Warning: Firestore client not initialized. User registration will not work.")
except Exception as e:
    print(f"Firestore Initialization Error: {e}")
    db = None 
    app_id = 'default-app-id'


# --- 1. ตั้งค่า Environment Variables ---
app = Flask(__name__)
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
OPENAI_API_BASE_URL = os.environ.get('OPENAI_API_BASE_URL') # URL ของ Open WebUI Server
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')           # API Key ที่กำหนดใน Open WebUI

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# --- Firestore Path Helpers ---
USER_PROFILE_COLLECTION = f"artifacts/{app_id}/public/data/user_profiles"

def get_user_profile(user_id):
    """ดึงข้อมูลสถานะของผู้ใช้จาก Firestore"""
    if not db: return {}
    doc_ref = db.collection(USER_PROFILE_COLLECTION).document(user_id)
    doc = doc_ref.get()
    return doc.to_dict() if doc.exists else {}

def update_user_profile(user_id, data):
    """อัปเดตข้อมูลสถานะของผู้ใช้ใน Firestore"""
    if not db: return
    doc_ref = db.collection(USER_PROFILE_COLLECTION).document(user_id)
    doc_ref.set(data, merge=True)
    
# --- Quick Reply Builder ---
def create_department_quick_replies(departments):
    """สร้าง Quick Reply Buttons จาก list ชื่อกรม"""
    items = []
    # จำกัดไม่เกิน 13 ปุ่ม (ตามข้อจำกัดของ Quick Reply)
    for dept_full_name in departments[:13]: 
        # 💡 ใช้ชื่อย่อ (Alias) ถ้ามี ถ้าไม่มีให้ใช้ชื่อเต็ม
        dept_label = THAI_DEPARTMENT_ALIAS.get(dept_full_name, dept_full_name)
        
        # เมื่อผู้ใช้คลิก ปุ่มจะส่งชื่อเต็ม (dept_full_name) กลับมา
        items.append(
            QuickReplyButton(
                action=MessageAction(
                    label=dept_label, # แสดงชื่อย่อ
                    # ใช้ Prefix ในการยืนยันเพื่อให้โค้ดรู้ว่านี่คือการเลือกกรม (ส่งชื่อเต็ม)
                    text=f"DEPT_CONFIRM:{dept_full_name}" 
                )
            )
        )
    return QuickReply(items=items)

# --- Fuzzy Search Function ---
def search_departments(query):
    """ค้นหากรมที่ใกล้เคียงที่สุด 5 รายการจาก query"""
    # ใช้ difflib.get_close_matches สำหรับ fuzzy search
    # cutoff=0.3 หมายถึงความใกล้เคียง 30% ขึ้นไป
    matches = difflib.get_close_matches(query, THAI_DEPARTMENTS, n=5, cutoff=0.3)
    return matches


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


# --- 3. การจัดการ Follow Event (เพิ่มเพื่อน) ---
@handler.add(FollowEvent)
def handle_follow(event):
    user_id = event.source.user_id
    
    # เริ่มต้นสถานะการลงทะเบียนทันทีเมื่อเพิ่มเพื่อน
    update_user_profile(user_id, {'state': 'waiting_for_name', 'isVerified': False})
    
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(
            text="สวัสดีค่ะ! ยินดีต้อนรับสู่ผู้ช่วย DPIS6 กรุณาพิมพ์ **ชื่อ-นามสกุลจริง** ของคุณเพื่อยืนยันตัวตนค่ะ"
        )
    )
    

# --- 4. การจัดการข้อความ (Logic หลัก: Multi-Step Registration) ---
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_message = event.message.text
    
    # 1. ตรวจสอบข้อความยืนยันกรมจาก Quick Reply (DEPT_CONFIRM)
    if user_message.startswith("DEPT_CONFIRM:"):
        # ข้อความที่ส่งกลับมาคือชื่อเต็ม
        department_name = user_message.replace("DEPT_CONFIRM:", "") 
        
        # 📌 เสร็จสิ้นการยืนยันตัวตน
        update_user_profile(user_id, {'department': department_name, 'isVerified': True, 'state': 'done'})
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text=f"✅ ยืนยันตัวตนสำเร็จ! คุณจาก {department_name} ยินดีให้บริการด้านโปรแกรม DPIS6 ค่ะ"
            )
        )
        return # 👈 หยุดการทำงานทันทีหลังจากยืนยันสำเร็จ

    # 2. ดึงสถานะปัจจุบันของ User จาก Firestore
    user_profile = get_user_profile(user_id)
    
    # 3. 💡 CHECK STATUS: ถ้ายังไม่ยืนยันตัวตน หรือไม่เคยมีโปรไฟล์
    if not user_profile or user_profile.get('isVerified') == False:
        
        current_state = user_profile.get('state', 'not_started') # ถ้าไม่มี state ถือว่ายังไม่เริ่มลงทะเบียน
        
        if current_state == 'not_started':
            # สถานะไม่ชัดเจน (ผู้ใช้เก่าที่ไม่มี profile) ให้เริ่มกระบวนการใหม่
            update_user_profile(user_id, {'state': 'waiting_for_name', 'isVerified': False})
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ระบบไม่พบข้อมูลการลงทะเบียนของคุณ กรุณาพิมพ์ชื่อ-นามสกุลจริงเพื่อเริ่มการยืนยันตัวตนค่ะ"))
            
        elif current_state == 'waiting_for_name':
            # 3.1 ขั้นตอน: บันทึกชื่อ
            if len(user_message.strip()) > 3:
                update_user_profile(user_id, {'name': user_message.strip(), 'state': 'waiting_for_dept'})
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text="ขอบคุณค่ะ! ตอนนี้กรุณา **พิมพ์ชื่อกรม** บางส่วน (เช่น สรรพากร) เพื่อให้เราค้นหาตัวเลือกที่ถูกต้องค่ะ")
                )
            else:
                 line_bot_api.reply_message(event.reply_token, TextSendMessage(text="กรุณาพิมพ์ชื่อเต็มที่ถูกต้องค่ะ"))
                 
        elif current_state == 'waiting_for_dept':
            # 3.2 ขั้นตอน: ค้นหาและแสดงตัวเลือกกรม
            matched_depts = search_departments(user_message)
            
            if matched_depts:
                # ถ้าพบกรมที่ใกล้เคียง ให้แสดงเป็น Quick Replies
                quick_replies = create_department_quick_replies(matched_depts)
                
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(
                        text="กรุณาคลิกเลือกกรม/ส่วนราชการที่ถูกต้องจากตัวเลือกด้านล่างเพื่อยืนยันค่ะ (หรือพิมพ์ใหม่เพื่อค้นหาเพิ่มเติม)",
                        quick_reply=quick_replies
                    )
                )
            else:
                # ถ้าไม่พบ
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ไม่พบชื่อกรมที่ใกล้เคียง กรุณาลองพิมพ์ชื่อที่สั้นลง หรือพิมพ์ชื่อเต็มอีกครั้งค่ะ"))
                 
        else:
            # สถานะ 'done' หรือสถานะอื่น ๆ ที่ไม่ควรเกิดขึ้นในเงื่อนไขนี้ (ป้องกันความผิดพลาด)
             line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ระบบกำลังประมวลผลการลงทะเบียนของคุณ กรุณารอสักครู่"))


    # 4. 🟢 AI CHAT LOGIC: ถ้าผู้ใช้ยืนยันตัวตนแล้ว (isVerified = True)
    elif user_profile.get('isVerified') == True:
        if event.source.type == 'user':
            try:
                # *********** LOGIC การเรียก Open WebUI ***********
                # 💡 เราจะส่งชื่อกรมของผู้ใช้ไปใน System Prompt ด้วย เพื่อให้ AI ตอบได้ตรงบริบทมากขึ้น
                department_name = user_profile.get('department', 'ผู้ใช้ทั่วไป')
                ai_response = get_ai_response(user_message, department_name)
                
                # ส่งข้อความกลับไปหาผู้ใช้ผ่าน Line
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text=ai_response)
                )
                
            except Exception as e:
                print(f"Error processing AI response: {e}")
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text="ขออภัยค่ะ ระบบ AI ขัดข้องชั่วคราว: " + str(e))
                )

# --- 5. ฟังก์ชันเชื่อมต่อ Open WebUI/Gemini (อัปเดตเพื่อรับชื่อกรม) ---
def get_ai_response(prompt, department_name="ผู้ใช้ทั่วไป"):
    """ส่ง Prompt ไปยัง Open WebUI API และรับคำตอบ"""
    
    url = f"{OPENAI_API_BASE_URL}/api/v1/chat/completions"  
 
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}", 
        "Content-Type": "application/json"
    }
    
    system_prompt = (
        f"คุณคือผู้ช่วยผู้เชี่ยวชาญด้านโปรแกรม DPIS6 ผู้ใช้มาจากกรม/ส่วนราชการ: {department_name} "
        "กรุณาตอบคำถามอย่างกระชับและเป็นมิตร"
    )
    
    payload = {
        "model": "hrms-dpis6", 
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7 
    }
    
    response = requests.post(url, headers=headers, json=payload, timeout=30)
    response.raise_for_status()
    
    data = response.json()
    
    ai_text = data['choices'][0]['message']['content']
    
    return ai_text

# --- 6. สำหรับรันบน Render ---
if __name__ == "__main__":
    # การตั้งค่าพอร์ตให้รับค่าจาก Environment Variable PORT
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
