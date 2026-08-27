from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os
import json
import urllib.request
import urllib.error

HOST = "0.0.0.0"
PORT = int(os.getenv("PORT", "8765"))

BASE_DIR = Path(__file__).resolve().parent


class Handler(SimpleHTTPRequestHandler):

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):

        if self.path == "/api/health":
            self.send_json({
                "ok": True,
                "service": "MONSTER AI"
            })
            return

        if self.path == "/":
            self.path = "/index.html"

        return super().do_GET()

    def do_POST(self):

        if self.path == "/api/chat":
            self.handle_chat()
            return

        self.send_json(
            {
                "error": "Endpoint not found"
            },
            status=404
        )

    def handle_chat(self):

        try:
            length = int(
                self.headers.get(
                    "Content-Length",
                    "0"
                )
            )

            raw = self.rfile.read(length)

            data = json.loads(
                raw.decode("utf-8")
            )

            messages = data.get(
                "messages",
                []
            )

            model = data.get(
                "model",
                "auto"
            )

            # ضع هنا رابط OmniRoute الحالي
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
                    "model": model,
                    "messages": messages,
                    "stream": True
                }
            ).encode("utf-8")

            request = urllib.request.Request(
                omni_url.rstrip("/")
                + "/chat/completions",
                data=payload,
                headers={
                    "Content-Type":
                        "application/json",
                    "Authorization":
                        "Bearer " + omni_key
                },
                method="POST"
            )

            try:

                response = urllib.request.urlopen(
                    request,
                    timeout=300
                )

            except urllib.error.HTTPError as error:

                body = error.read().decode(
                    "utf-8",
                    errors="replace"
                )

                self.send_json(
                    {
                        "error": body
                    },
                    status=error.code
                )

                return

            except Exception as error:

                self.send_json(
                    {
                        "error": str(error)
                    },
                    status=502
                )

                return

            self.send_response(200)

            self.send_header(
                "Content-Type",
                "text/event-stream"
            )

            self.send_header(
                "Cache-Control",
                "no-cache"
            )

            self.send_header(
                "Connection",
                "keep-alive"
            )

            self.end_headers()

            while True:

                chunk = response.read(
                    4096
                )

                if not chunk:
                    break

                self.wfile.write(chunk)
                self.wfile.flush()

            response.close()

        except Exception as error:

            self.send_json(
                {
                    "error": str(error)
                },
                status=500
            )

    def send_json(
        self,
        data,
        status=200
    ):

        body = json.dumps(
            data,
            ensure_ascii=False
        ).encode("utf-8")

        self.send_response(status)

        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )

        self.send_header(
            "Content-Length",
            str(len(body))
        )

        self.end_headers()

        self.wfile.write(body)


if __name__ == "__main__":

    os.chdir(BASE_DIR)

    server = ThreadingHTTPServer(
        (HOST, PORT),
        Handler
    )

    print(
        f"MONSTER AI running at "
        f"http://127.0.0.1:{PORT}"
    )

    server.serve_forever()
