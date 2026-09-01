import os
import json
import uuid
import time
import asyncio
import httpx
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="MONSTER AI Server - OmniRoute Edition")

# سماح لجميع الأصول (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_FILE = "database.json"

# =========================================================
# ⚙️ إعدادات OMNIROUTE
# =========================================================
# ضع هنا رابط OmniRoute الخاص بك (مثل رابط Cloudflare Tunnel أو Localhost)
OMNIROUTE_BASE_URL = os.getenv(
    "OMNIROUTE_BASE_URL",
    "https://firms-adsl-bingo-closure.trycloudflare.com/v1"
)

OMNIROUTE_API_KEY = os.getenv("OMNIROUTE_API_KEY")

DEFAULT_MODEL = "auto"

# تعليمات النظام الأساسية لـ MONSTER AI
SYSTEM_INSTRUCTION = """
أنت MONSTER AI، تم تطويرك بواسطة هيثم حماتة (Heythem Hamata)، مهندس أتمتة وباني أنظمة ذكاء اصطناعي (Automation Engineer & AI Builder).
أنت ذكي، محترف، وتجيب بدقة وسرعة باللغة التي يكلمك بها المستخدم (عربي، فرنسي، إنجليزي، أو الدارجة).
تخصصك: البرمجة، أنظمة الذكاء الاصطناعي، الأتمتة (n8n, APIs)، والتحليل.
"""

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
# API ROUTES (إدارة السجل والملفات)
# =========================================================

@app.get("/api/conversations")
async def get_conversations():
    db = load_db()
    convs = list(db["conversations"].values())
    convs.sort(key=lambda x: x.get("updated_at", 0), reverse=True)
    return convs

@app.post("/api/conversations")
async def create_conversation():
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
    db = load_db()
    if cid not in db["conversations"]:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return db["conversations"][cid]

@app.post("/api/conversations/{cid}/messages")
async def save_messages(cid: str, req: MessagesSaveModel):
    db = load_db()
    if cid not in db["conversations"]:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    conv = db["conversations"][cid]
    conv["messages"] = req.messages
    conv["updated_at"] = time.time()

    # تحديث عنوان المحادثة بناءً على أول سؤال
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
    db = load_db()
    if cid in db["conversations"]:
        del db["conversations"][cid]
        save_db(db)
    return {"status": "deleted"}

@app.post("/api/files")
async def upload_file(file_req: FileUploadModel):
    extracted_text = ""
    if not file_req.mime_type.startswith("image/"):
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
# OMNIROUTE STREAMING CHAT ENGINE
# =========================================================

async def call_omniroute_stream(messages_history: list, model_name: str):
    """إرسال الطلب إلى OmniRoute عبر OpenAI-compatible streaming API"""

    payload_messages = [
        {
            "role": "system",
            "content": SYSTEM_INSTRUCTION
        }
    ]

    for msg in messages_history:
        payload_messages.append({
            "role": msg.get("role", "user"),
            "content": msg.get("content", "")
        })

    url = OMNIROUTE_BASE_URL.rstrip("/") + "/chat/completions"

    headers = {
        "Content-Type": "application/json"
    }

    if OMNIROUTE_API_KEY:
        headers["Authorization"] = f"Bearer {OMNIROUTE_API_KEY}"

    selected_model = (
        model_name
        if model_name and model_name != "auto"
        else DEFAULT_MODEL
    )

    payload = {
        "model": selected_model,
        "messages": payload_messages,
        "stream": True
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST",
            url,
            headers=headers,
            json=payload
        ) as response:

            if response.status_code != 200:
                err_content = await response.aread()
                raise Exception(
                    f"OmniRoute Error HTTP {response.status_code}: "
                    f"{err_content.decode('utf-8', errors='ignore')}"
                )

            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue

                raw_data = line[5:].strip()

                if raw_data == "[DONE]":
                    break

                try:
                    json_data = json.loads(raw_data)

                    delta_content = (
                        json_data
                        .get("choices", [{}])[0]
                        .get("delta", {})
                        .get("content", "")
                    )

                    if delta_content:
                        yield delta_content

                except json.JSONDecodeError:
                    continue

async def ai_stream_generator(cid: Optional[str], full_history: list, model_name: str):
    accumulated_text = ""
    try:
        async for chunk in call_omniroute_stream(full_history, model_name):
            accumulated_text += chunk
            data = {"choices": [{"delta": {"content": chunk}}]}
            yield f"data: {json.dumps(data)}\n\n"
            await asyncio.sleep(0.005)

    except Exception as e:
        error_msg = f"⚠️ [OmniRoute Stream Exception]: {str(e)}"
        accumulated_text += f"\n\n{error_msg}"
        data = {"choices": [{"delta": {"content": f"\n\n{error_msg}"}}]}
        yield f"data: {json.dumps(data)}\n\n"

    yield "data: [DONE]\n\n"

    # حفظ الرسالة في السجل بعد اكتمال البث
    if cid and accumulated_text.strip():
        db = load_db()
        if cid in db["conversations"]:
            conv = db["conversations"][cid]
            full_history.append({"role": "assistant", "content": accumulated_text})
            conv["messages"] = full_history
            conv["updated_at"] = time.time()
            db["conversations"][cid] = conv
            save_db(db)

@app.post("/api/chat")
async def chat_endpoint(req: ChatRequestModel):
    return StreamingResponse(
        ai_stream_generator(req.conversation_id, req.messages, req.model),
        media_type="text/event-stream"
    )

# =========================================================
# STATIC FILES (FRONTEND)
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
