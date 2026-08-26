from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import webbrowser

HOST = "127.0.0.1"
PORT = 8765

WEB_DIR = Path(__file__).parent / "web"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(
            *args,
            directory=str(WEB_DIR),
            **kwargs
        )


server = ThreadingHTTPServer(
    (HOST, PORT),
    Handler
)

url = f"http://{HOST}:{PORT}"

print("OmniChat running at:", url)

webbrowser.open(url)

server.serve_forever()