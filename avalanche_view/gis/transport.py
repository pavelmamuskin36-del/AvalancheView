"""Process-owned loopback server: static assets, bounded binary frames and DEM tiles."""

import hashlib
import json
import logging
import mimetypes
import secrets
import threading
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

from avalanche_view.config import PROJECT_ROOT

logger = logging.getLogger(__name__)


class AssetStore:
    def __init__(self, limit=192 * 1024 * 1024):
        self.limit = limit
        self.assets = OrderedDict()
        self.size = 0
        self.lock = threading.RLock()

    def put(self, data, content_type="application/octet-stream"):
        if len(data) > self.limit:
            raise ValueError("Слой превышает лимит передачи. Выберите меньший домен.")
        key = hashlib.sha256(content_type.encode() + data).hexdigest()[:32]
        with self.lock:
            if key in self.assets:
                self.assets.move_to_end(key)
                return key
            while self.assets and self.size + len(data) > self.limit:
                _, old = self.assets.popitem(last=False)
                self.size -= len(old[0])
            self.assets[key] = (data, content_type)
            self.size += len(data)
        return key

    def get(self, key):
        with self.lock:
            value = self.assets[key]
            self.assets.move_to_end(key)
            return value

    def json(self, value):
        return self.put(
            json.dumps(value, ensure_ascii=False, allow_nan=False).encode(), "application/json"
        )


class LocalDataService:
    def __init__(self, terrain):
        self.store = AssetStore()
        self.terrain = terrain
        self.token = secrets.token_urlsafe(24)
        self.static = PROJECT_ROOT / "avalanche_view" / "resources" / "web"
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                path = unquote(urlsplit(self.path).path).split("/")
                if len(path) < 3 or path[1] != owner.token:
                    self.send_error(403)
                    return
                try:
                    if path[2] == "data":
                        data, mime = owner.store.get(path[3])
                    elif path[2] == "dem":
                        data = owner.terrain.tile(
                            path[3], int(path[4]), int(path[5]), int(path[6].split(".")[0])
                        )
                        mime = "image/png"
                    else:
                        relative = "/".join(path[2:]) or "index.html"
                        file = (owner.static / relative).resolve()
                        if not file.is_relative_to(owner.static.resolve()):
                            self.send_error(403)
                            return
                        data = file.read_bytes()
                        mime = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
                    self.send_response(200)
                    self.send_header("Content-Type", mime)
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header(
                        "Cache-Control", "private, max-age=3600" if path[2] == "dem" else "no-store"
                    )
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    self.wfile.write(data)
                except (FileNotFoundError, KeyError, ValueError, IndexError):
                    self.send_error(404)
                except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                    logger.debug("WebEngine request cancelled")
                except Exception:
                    logger.exception("Local GIS service failed")
                    self.send_error(500)

            def log_message(self, *args):
                # Do not log tokenized URLs or provider credentials.
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.base_url = f"http://127.0.0.1:{self.server.server_port}/{self.token}/"
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True, name="GIS data"
        )
        self.thread.start()

    def asset_url(self, key):
        return self.base_url + "data/" + key

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
