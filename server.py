import os
import json
import uuid
import time
import asyncio
from typing import List, Optional, Union, Dict, Any
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="MONSTER AI Server")

# سماح لجميع الأصول (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_FILE = "database.json"

# تهيئة قاعدة البيانات المحلية للمحادثات
def load_db() -> Dict[str, Any]:
    if not os.path.exists(DB_FILE):
        return {"conversations": {}}
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"conversations": {}}

def save_db(data: Dict[str, Any]):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# نماذج البيانات (Pydantic Models)
class FileUploadModel(BaseModel):
    filename: str
    mime_type: str
    data: str
    conversation_id: str

class MessagesSaveModel(BaseModel):
    messages: List[Dict[str, Any]]

class ChatRequestModel(BaseModel):
    model: str = "auto"
    conversation_id: Optional[str] = None
    messages: List[Dict[str, Any]]
    stream: bool = True

# =========================================================
# API ROUTES (حفظ واسترجاع المحادثات والملفات)
# =========================================================

@app.get("/api/conversations")
async def get_conversations():
    """استرجاع قائمة المحادثات لظهورها في القائمة الجانبية"""
    db = load_db()
    convs = list(db["conversations"].values())
    # ترتيب المحادثات من الأحدث إلى الأقدم
    convs.sort(key=lambda x: x.get("updated_at", 0), reverse=True)
    return convs

@app.post("/api/conversations")
async def create_conversation():
    """إنشاء محادثة جديدة"""
    db = load_db()
    cid = str(uuid.uuid4())
    now = time.time()
    new_conv = {
        "id": cid,
        "title": "New Conversation",
        "messages": [],
        "created_at": now,
        "updated_at": now
    }
    db["conversations"][cid] = new_conv
    save_db(db)
    return new_conv

@app.get("/api/conversations/{cid}")
async def get_conversation(cid: str):
    """فتح محادثة معينة واسترجاع رسائلها"""
    db = load_db()
    if cid not in db["conversations"]:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return db["conversations"][cid]

@app.post("/api/conversations/{cid}/messages")
async def save_messages(cid: str, req: MessagesSaveModel):
    """حفظ سجل المحادثة تحديث عنوانها تلقائياً"""
    db = load_db()
    if cid not in db["conversations"]:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    conv = db["conversations"][cid]
    conv["messages"] = req.messages
    conv["updated_at"] = time.time()

    # تحديث العنوان من أول سؤال للمستخدم إذا كان العنوان افتراضياً
    if req.messages and (conv["title"] == "New Conversation" or not conv["title"]):
        for msg in req.messages:
            if msg.get("role") == "user":
                content = msg.get("content")
                text_title = ""
                if isinstance(content, str):
                    text_title = content
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            text_title = part.get("text", "")
                            break
                if text_title:
                    conv["title"] = text_title[:30] + ("..." if len(text_title) > 30 else "")
                    break

    db["conversations"][cid] = conv
    save_db(db)
    return {"status": "success", "conversation": conv}

@app.delete("/api/conversations/{cid}")
async def delete_conversation(cid: str):
    """حذف محادثة"""
    db = load_db()
    if cid in db["conversations"]:
        del db["conversations"][cid]
        save_db(db)
    return {"status": "deleted"}

@app.post("/api/files")
async def upload_file(file_req: FileUploadModel):
    """معالجة ورفع الملفات والصور"""
    extracted_text = ""
    if not file_req.mime_type.startswith("image/"):
        # إذا كان ملفاً نصياً يتم استخراج محتواه
        try:
            if "," in file_req.data:
                import base64
                b64_data = file_req.data.split(",")[1]
                decoded_bytes = base64.b64decode(b64_data)
                extracted_text = decoded_bytes.decode("utf-8", errors="ignore")
        except Exception as e:
            extracted_text = f"[Could not parse file content: {str(e)}]"

    return {
        "filename": file_req.filename,
        "mime_type": file_req.mime_type,
        "extracted_text": extracted_text
    }

# =========================================================
# STREAMING CHAT API (الذكاء الاصطناعي والبث التدفقي)
# =========================================================

async def ai_stream_generator(prompt_text: str, cid: Optional[str] = None, full_history: list = None):
    """مولد البث التدفقي لتوليد الردود ورسائل الـ SSE"""
    
    # يمكنك ربطه بمحرك خارجي مثل OpenAI أو Ollama أو Gemini
    # هنا محاكاة ذكية وسريعة للرد التدفقي:
    response_text = f"أهلاً بك! لقد استلمت طلبك بنجاح:\n\n> **{prompt_text[:100]}**\n\nأنا نظام **MONSTER AI** الجاهز للأتمتة ومعالجة البيانات والملفات وتحليلها بأعلى كفاءة."

    words = response_text.split(" ")
    accumulated_text = ""

    for word in words:
        delta = word + " "
        accumulated_text += delta
        data = {
            "choices": [
                {
                    "delta": {"content": delta}
                }
            ]
        }
        yield f"data: {json.dumps(data)}\n\n"
        await asyncio.sleep(0.04)

    yield "data: [DONE]\n\n"

    # حفظ رد الـ AI تلقائياً في المحادثة
    if cid:
        db = load_db()
        if cid in db["conversations"]:
            conv = db["conversations"][cid]
            if full_history is not None:
                full_history.append({"role": "assistant", "content": accumulated_text})
                conv["messages"] = full_history
            else:
                conv["messages"].append({"role": "assistant", "content": accumulated_text})
            conv["updated_at"] = time.time()
            db["conversations"][cid] = conv
            save_db(db)

@app.post("/api/chat")
async def chat_endpoint(req: ChatRequestModel):
    """نقطة إرسال المحادثة البثية"""
    last_user_message = ""
    if req.messages:
        last_msg = req.messages[-1]
        content = last_msg.get("content")
        if isinstance(content, str):
            last_user_message = content
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    last_user_message += part.get("text", "") + " "

    return StreamingResponse(
        ai_stream_generator(last_user_message, req.conversation_id, req.messages),
        media_type="text/event-stream"
    )

# =========================================================
# SERVE FRONTEND & LOGO
# =========================================================

@app.get("/")
async def serve_index():
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return HTMLResponse("<h1>index.html not found!</h1>")

@app.get("/monster_logo.png.png")
async def serve_logo():
    if os.path.exists("monster_logo.png.png"):
        return FileResponse("monster_logo.png.png")
    return HTMLResponse("", status_code=404)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
