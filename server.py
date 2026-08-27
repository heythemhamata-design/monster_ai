from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os
import json
import uuid
import base64
import mimetypes
import urllib.request
import urllib.error
import re
import html
import zipfile
import io
from datetime import datetime, timezone
from urllib.parse import urlparse


# =========================================================
# CONFIG
# =========================================================

HOST = "0.0.0.0"
PORT = int(os.getenv("PORT", "8765"))

BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = BASE_DIR / "uploads"
CONVERSATIONS_FILE = DATA_DIR / "conversations.json"


# =========================================================
# LOAD .ENV WITHOUT EXTRA PACKAGE
# =========================================================

def load_env_file():

    env_file = BASE_DIR / ".env"

    if not env_file.exists():
        return

    try:
        for line in env_file.read_text(
            encoding="utf-8"
        ).splitlines():

            line = line.strip()

            if not line:
                continue

            if line.startswith("#"):
                continue

            if "=" not in line:
                continue

            key, value = line.split(
                "=",
                1
            )

            key = key.strip()
            value = value.strip()

            if (
                len(value) >= 2
                and value[0] == '"'
                and value[-1] == '"'
            ):
                value = value[1:-1]

            elif (
                len(value) >= 2
                and value[0] == "'"
                and value[-1] == "'"
            ):
                value = value[1:-1]

            os.environ.setdefault(
                key,
                value
            )

    except Exception as error:

        print(
            "Could not load .env:",
            error
        )


load_env_file()


# =========================================================
# DIRECTORIES
# =========================================================

DATA_DIR.mkdir(
    parents=True,
    exist_ok=True
)

UPLOADS_DIR.mkdir(
    parents=True,
    exist_ok=True
)


if not CONVERSATIONS_FILE.exists():

    CONVERSATIONS_FILE.write_text(
        "[]",
        encoding="utf-8"
    )


# =========================================================
# DATABASE HELPERS
# =========================================================

DB_LOCK = __import__("threading").Lock()


def now_iso():

    return datetime.now(
        timezone.utc
    ).isoformat()


def load_conversations():

    with DB_LOCK:

        try:

            text = CONVERSATIONS_FILE.read_text(
                encoding="utf-8"
            )

            data = json.loads(text)

            if isinstance(data, list):
                return data

            return []

        except Exception:

            return []


def save_conversations(conversations):

    temp_file = CONVERSATIONS_FILE.with_suffix(
        ".tmp"
    )

    with DB_LOCK:

        temp_file.write_text(
            json.dumps(
                conversations,
                ensure_ascii=False,
                indent=2
            ),
            encoding="utf-8"
        )

        temp_file.replace(
            CONVERSATIONS_FILE
        )


def find_conversation(conversation_id):

    conversations = load_conversations()

    for conversation in conversations:

        if conversation.get("id") == conversation_id:
            return conversation

    return None


def generate_title(messages):

    for message in messages:

        if message.get("role") != "user":
            continue

        content = message.get(
            "content",
            ""
        )

        if isinstance(content, list):

            text_parts = []

            for item in content:

                if (
                    isinstance(item, dict)
                    and item.get("type") == "text"
                ):

                    text_parts.append(
                        str(
                            item.get(
                                "text",
                                ""
                            )
                        )
                    )

            content = " ".join(
                text_parts
            )

        content = str(content).strip()

        if not content:
            continue

        content = re.sub(
            r"\s+",
            " ",
            content
        )

        # Remove very long titles.
        if len(content) > 55:

            content = (
                content[:55]
                .rstrip()
                + "..."
            )

        return content

    return "New Conversation"


def create_conversation():

    conversation = {

        "id": str(
            uuid.uuid4()
        ),

        "title":
            "New Conversation",

        "messages": [],

        "files": [],

        "created_at":
            now_iso(),

        "updated_at":
            now_iso()
    }

    conversations = load_conversations()

    conversations.insert(
        0,
        conversation
    )

    save_conversations(
        conversations
    )

    return conversation


def update_conversation(
    conversation_id,
    messages=None,
    files=None
):

    conversations = load_conversations()

    target = None

    for conversation in conversations:

        if conversation.get("id") == conversation_id:

            target = conversation
            break

    if target is None:
        return None

    if messages is not None:

        target["messages"] = messages

        target["title"] = generate_title(
            messages
        )

    if files is not None:

        target["files"] = files

    target["updated_at"] = now_iso()

    # Most recently updated first.
    conversations.sort(
        key=lambda item:
            item.get(
                "updated_at",
                ""
            ),
        reverse=True
    )

    save_conversations(
        conversations
    )

    return target


# =========================================================
# FILE EXTRACTION
# =========================================================

TEXT_EXTENSIONS = {

    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".tsv",
    ".json",
    ".xml",
    ".html",
    ".htm",
    ".css",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".py",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".php",
    ".rb",
    ".go",
    ".rs",
    ".swift",
    ".kt",
    ".sql",
    ".yaml",
    ".yml",
    ".ini",
    ".cfg",
    ".log",
    ".sh",
    ".bat",
    ".ps1"
}


def decode_text(data):

    for encoding in (
        "utf-8",
        "utf-8-sig",
        "cp1256",
        "latin-1"
    ):

        try:

            return data.decode(
                encoding
            )

        except UnicodeDecodeError:

            continue

    return data.decode(
        "utf-8",
        errors="replace"
    )


def extract_docx(data):

    try:

        with zipfile.ZipFile(
            io.BytesIO(data)
        ) as archive:

            xml = archive.read(
                "word/document.xml"
            )

        text = re.sub(
            r"<[^>]+>",
            " ",
            xml.decode(
                "utf-8",
                errors="ignore"
            )
        )

        text = html.unescape(
            text
        )

        text = re.sub(
            r"\s+",
            " ",
            text
        )

        return text.strip()

    except Exception as error:

        return (
            "[DOCX extraction failed: "
            + str(error)
            + "]"
        )


def extract_xlsx(data):

    try:

        with zipfile.ZipFile(
            io.BytesIO(data)
        ) as archive:

            shared_strings = []

            if (
                "xl/sharedStrings.xml"
                in archive.namelist()
            ):

                xml = archive.read(
                    "xl/sharedStrings.xml"
                ).decode(
                    "utf-8",
                    errors="ignore"
                )

                shared_strings = re.findall(
                    r"<t[^>]*>(.*?)</t>",
                    xml
                )

            sheets = []

            for name in archive.namelist():

                if name.startswith(
                    "xl/worksheets/"
                ) and name.endswith(
                    ".xml"
                ):

                    xml = archive.read(
                        name
                    ).decode(
                        "utf-8",
                        errors="ignore"
                    )

                    values = re.findall(
                        r"<v>(.*?)</v>",
                        xml
                    )

                    sheets.extend(
                        values
                    )

            output = []

            output.extend(
                shared_strings
            )

            output.extend(
                sheets
            )

            return "\n".join(
                output
            )

    except Exception as error:

        return (
            "[XLSX extraction failed: "
            + str(error)
            + "]"
        )


def extract_pdf(data):

    try:

        from pypdf import PdfReader

        reader = PdfReader(
            io.BytesIO(data)
        )

        pages = []

        for page in reader.pages:

            try:

                pages.append(
                    page.extract_text()
                    or ""
                )

            except Exception:
                pass

        return "\n\n".join(
            pages
        ).strip()

    except ImportError:

        return (
            "[PDF detected. Install "
            "pypdf to extract its text.]"
        )

    except Exception as error:

        return (
            "[PDF extraction failed: "
            + str(error)
            + "]"
        )


def extract_file_content(
    filename,
    data,
    mime_type=""
):

    extension = (
        Path(filename)
        .suffix
        .lower()
    )

    if extension in TEXT_EXTENSIONS:

        return decode_text(
            data
        )

    if extension == ".docx":

        return extract_docx(
            data
        )

    if extension == ".xlsx":

        return extract_xlsx(
            data
        )

    if extension == ".pdf":

        return extract_pdf(
            data
        )

    # Images are kept as files.
    # The browser can send them as image_url.
    if mime_type.startswith(
        "image/"
    ):

        return ""

    return ""


# =========================================================
# HTTP HANDLER
# =========================================================

class Handler(
    SimpleHTTPRequestHandler
):

    protocol_version = "HTTP/1.1"


    # =====================================================
    # HEADERS
    # =====================================================

    def end_headers(self):

        self.send_header(
            "Access-Control-Allow-Origin",
            "*"
        )

        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Authorization"
        )

        self.send_header(
            "Access-Control-Allow-Methods",
            "GET, POST, DELETE, OPTIONS"
        )

        super().end_headers()


    # =====================================================
    # OPTIONS
    # =====================================================

    def do_OPTIONS(self):

        self.send_response(
            204
        )

        self.send_header(
            "Content-Length",
            "0"
        )

        self.end_headers()


    # =====================================================
    # GET
    # =====================================================

    def do_GET(self):

        parsed = urlparse(
            self.path
        )

        path = parsed.path


        if path == "/api/health":

            self.send_json({

                "ok": True,

                "service":
                    "MONSTER AI",

                "omniroute":
                    bool(
                        os.getenv(
                            "OMNIROUTE_URL",
                            ""
                        )
                    )

            })

            return


        if path == "/api/conversations":

            conversations = (
                load_conversations()
            )

            # Only return metadata.
            result = []

            for conversation in conversations:

                result.append({

                    "id":
                        conversation.get(
                            "id"
                        ),

                    "title":
                        conversation.get(
                            "title",
                            "New Conversation"
                        ),

                    "created_at":
                        conversation.get(
                            "created_at"
                        ),

                    "updated_at":
                        conversation.get(
                            "updated_at"
                        ),

                    "message_count":
                        len(
                            conversation.get(
                                "messages",
                                []
                            )
                        ),

                    "file_count":
                        len(
                            conversation.get(
                                "files",
                                []
                            )
                        )
                })

            self.send_json(
                result
            )

            return


        if path.startswith(
            "/api/conversations/"
        ):

            conversation_id = (
                path.split(
                    "/"
                )[-1]
            )

            conversation = (
                find_conversation(
                    conversation_id
                )
            )

            if not conversation:

                self.send_json(
                    {
                        "error":
                            "Conversation not found."
                    },
                    status=404
                )

                return

            self.send_json(
                conversation
            )

            return


        if path == "/":

            self.path = "/index.html"

        return super().do_GET()


    # =====================================================
    # POST
    # =====================================================

    def do_POST(self):

        parsed = urlparse(
            self.path
        )

        path = parsed.path


        if path == "/api/conversations":

            self.handle_create_conversation()

            return


        if path.startswith(
            "/api/conversations/"
        ) and path.endswith(
            "/messages"
        ):

            conversation_id = path.split(
                "/"
            )[-2]

            self.handle_save_messages(
                conversation_id
            )

            return


        if path == "/api/files":

            self.handle_file_upload()

            return


        if path == "/api/chat":

            self.handle_chat()

            return


        self.send_json(
            {
                "error":
                    "Endpoint not found"
            },
            status=404
        )


    # =====================================================
    # DELETE
    # =====================================================

    def do_DELETE(self):

        parsed = urlparse(
            self.path
        )

        path = parsed.path


        if path.startswith(
            "/api/conversations/"
        ):

            conversation_id = (
                path.split(
                    "/"
                )[-1]
            )

            self.handle_delete_conversation(
                conversation_id
            )

            return


        self.send_json(
            {
                "error":
                    "Endpoint not found"
            },
            status=404
        )


    # =====================================================
    # CREATE CONVERSATION
    # =====================================================

    def handle_create_conversation(
        self
    ):

        conversation = (
            create_conversation()
        )

        self.send_json(
            conversation
        )


    # =====================================================
    # SAVE MESSAGES
    # =====================================================

    def handle_save_messages(
        self,
        conversation_id
    ):

        try:

            data = self.read_json()

            messages = data.get(
                "messages",
                []
            )

            if not isinstance(
                messages,
                list
            ):

                self.send_json(
                    {
                        "error":
                            "messages must be an array."
                    },
                    status=400
                )

                return

            conversation = (
                update_conversation(
                    conversation_id,
                    messages=messages
                )
            )

            if not conversation:

                self.send_json(
                    {
                        "error":
                            "Conversation not found."
                    },
                    status=404
                )

                return

            self.send_json(
                conversation
            )

        except Exception as error:

            self.send_json(
                {
                    "error":
                        str(error)
                },
                status=500
            )


    # =====================================================
    # DELETE CONVERSATION
    # =====================================================

    def handle_delete_conversation(
        self,
        conversation_id
    ):

        conversations = (
            load_conversations()
        )

        new_list = [

            item

            for item in conversations

            if item.get("id")
            != conversation_id

        ]

        if len(new_list) == len(
            conversations
        ):

            self.send_json(
                {
                    "error":
                        "Conversation not found."
                },
                status=404
            )

            return

        save_conversations(
            new_list
        )

        self.send_json({
            "ok": True
        })


    # =====================================================
    # FILE UPLOAD
    # =====================================================

    def handle_file_upload(
        self
    ):

        try:

            data = self.read_json()

            filename = str(
                data.get(
                    "filename",
                    "file"
                )
            )

            mime_type = str(
                data.get(
                    "mime_type",
                    "application/octet-stream"
                )
            )

            encoded = data.get(
                "data",
                ""
            )

            conversation_id = data.get(
                "conversation_id"
            )

            if not encoded:

                self.send_json(
                    {
                        "error":
                            "File data is missing."
                    },
                    status=400
                )

                return

            # Remove data URL prefix.
            if "," in encoded:

                encoded = encoded.split(
                    ",",
                    1
                )[1]

            file_bytes = base64.b64decode(
                encoded
            )

            safe_name = (
                Path(filename).name
            )

            file_id = str(
                uuid.uuid4()
            )

            stored_name = (
                file_id
                + "_"
                + safe_name
            )

            file_path = (
                UPLOADS_DIR
                / stored_name
            )

            file_path.write_bytes(
                file_bytes
            )

            extracted = (
                extract_file_content(
                    safe_name,
                    file_bytes,
                    mime_type
                )
            )

            file_info = {

                "id":
                    file_id,

                "name":
                    safe_name,

                "stored_name":
                    stored_name,

                "mime_type":
                    mime_type,

                "size":
                    len(file_bytes),

                "created_at":
                    now_iso(),

                "extracted_text":
                    extracted[:200000]

            }


            if conversation_id:

                conversation = (
                    find_conversation(
                        conversation_id
                    )
                )

                if conversation:

                    files = conversation.get(
                        "files",
                        []
                    )

                    files.append(
                        file_info
                    )

                    update_conversation(
                        conversation_id,
                        files=files
                    )


            self.send_json(
                file_info
            )

        except Exception as error:

            self.send_json(
                {
                    "error":
                        str(error)
                },
                status=500
            )


    # =====================================================
    # CHAT
    # =====================================================

    def handle_chat(
        self
    ):

        try:

            data = self.read_json()

            messages = data.get(
                "messages",
                []
            )

            model = data.get(
                "model",
                "auto"
            )

            conversation_id = data.get(
                "conversation_id"
            )


            if not isinstance(
                messages,
                list
            ):

                self.send_json(
                    {
                        "error":
                            "messages must be an array."
                    },
                    status=400
                )

                return


            # =================================================
            # CREATE CONVERSATION IF NECESSARY
            # =================================================

            if not conversation_id:

                conversation = (
                    create_conversation()
                )

                conversation_id = (
                    conversation["id"]
                )


            else:

                conversation = (
                    find_conversation(
                        conversation_id
                    )
                )

                if not conversation:

                    conversation = (
                        create_conversation()
                    )

                    conversation_id = (
                        conversation["id"]
                    )


            # =================================================
            # SAVE USER SIDE BEFORE AI REQUEST
            # =================================================

            update_conversation(
                conversation_id,
                messages=messages
            )


            # =================================================
            # OMNIROUTE
            # =================================================

            omni_url = os.getenv(
                "OMNIROUTE_URL",
                ""
            )

            omni_key = os.getenv(
                "OMNIROUTE_API_KEY",
                ""
            )


            if not omni_url:

                self.send_json(
                    {
                        "error":
                            "OMNIROUTE_URL is not configured."
                    },
                    status=500
                )

                return


            payload = json.dumps(
                {
                    "model":
                        model,

                    "messages":
                        messages,

                    "stream":
                        True
                },
                ensure_ascii=False
            ).encode(
                "utf-8"
            )


            request = urllib.request.Request(

                omni_url.rstrip("/")
                + "/chat/completions",

                data=payload,

                headers={

                    "Content-Type":
                        "application/json",

                    "Authorization":
                        "Bearer "
                        + omni_key

                },

                method="POST"

            )


            try:

                response = (
                    urllib.request.urlopen(
                        request,
                        timeout=300
                    )
                )

            except urllib.error.HTTPError as error:

                body = error.read().decode(
                    "utf-8",
                    errors="replace"
                )

                self.send_json(
                    {
                        "error":
                            body
                    },
                    status=error.code
                )

                return

            except Exception as error:

                self.send_json(
                    {
                        "error":
                            str(error)
                    },
                    status=502
                )

                return


            # =================================================
            # STREAM RESPONSE
            # =================================================

            self.send_response(
                200
            )

            self.send_header(
                "Content-Type",
                "text/event-stream; charset=utf-8"
            )

            self.send_header(
                "Cache-Control",
                "no-cache, no-transform"
            )

            self.send_header(
                "Connection",
                "keep-alive"
            )

            self.send_header(
                "X-Conversation-ID",
                conversation_id
            )

            self.end_headers()


            assistant_answer = ""

            buffer = ""


            while True:

                chunk = response.read(
                    4096
                )

                if not chunk:
                    break

                decoded = chunk.decode(
                    "utf-8",
                    errors="replace"
                )

                buffer += decoded

                lines = buffer.split(
                    "\n"
                )

                buffer = (
                    lines.pop()
                    or ""
                )


                for line in lines:

                    clean = line.strip()

                    if not clean:
                        continue

                    if not clean.startswith(
                        "data:"
                    ):
                        continue

                    raw = clean[5:].strip()

                    if raw == "[DONE]":

                        continue

                    try:

                        packet = json.loads(
                            raw
                        )

                        delta = (
                            packet
                            .get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content")
                        )

                        if delta:

                            assistant_answer += (
                                delta
                            )

                    except Exception:

                        pass


                # Send original SSE bytes
                # to browser.
                self.wfile.write(
                    chunk
                )

                self.wfile.flush()


            response.close()


            # =================================================
            # SAVE ASSISTANT RESPONSE
            # =================================================

            conversation = (
                find_conversation(
                    conversation_id
                )
            )

            if conversation:

                saved_messages = (
                    conversation.get(
                        "messages",
                        []
                    )
                )

                # Avoid duplicate if frontend already
                # saved the assistant response.
                if assistant_answer:

                    saved_messages.append({

                        "role":
                            "assistant",

                        "content":
                            assistant_answer

                    })

                    update_conversation(
                        conversation_id,
                        messages=saved_messages
                    )


        except Exception as error:

            try:

                self.send_json(
                    {
                        "error":
                            str(error)
                    },
                    status=500
                )

            except Exception:

                pass


    # =====================================================
    # JSON READER
    # =====================================================

    def read_json(
        self
    ):

        length = int(
            self.headers.get(
                "Content-Length",
                "0"
            )
        )

        if length <= 0:

            return {}

        raw = self.rfile.read(
            length
        )

        return json.loads(
            raw.decode(
                "utf-8"
            )
        )


    # =====================================================
    # JSON RESPONSE
    # =====================================================

    def send_json(
        self,
        data,
        status=200
    ):

        body = json.dumps(
            data,
            ensure_ascii=False
        ).encode(
            "utf-8"
        )

        self.send_response(
            status
        )

        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )

        self.send_header(
            "Content-Length",
            str(len(body))
        )

        self.end_headers()

        self.wfile.write(
            body
        )


# =========================================================
# START SERVER
# =========================================================

if __name__ == "__main__":

    os.chdir(
        BASE_DIR
    )

    server = ThreadingHTTPServer(
        (
            HOST,
            PORT
        ),
        Handler
    )

    print(
        "=========================================="
    )

    print(
        "MONSTER AI"
    )

    print(
        f"Local server:"
        f" http://127.0.0.1:{PORT}"
    )

    print(
        "OmniRoute:"
        f" {os.getenv('OMNIROUTE_URL', 'NOT CONFIGURED')}"
    )

    print(
        f"Database:"
        f" {CONVERSATIONS_FILE}"
    )

    print(
        f"Uploads:"
        f" {UPLOADS_DIR}"
    )

    print(
        "=========================================="
    )

    server.serve_forever()
