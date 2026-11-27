"""Static frontend server for Joshu (.open-design) with directory listings disabled."""

from __future__ import annotations

import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

FRONTEND_DIR = (Path(__file__).resolve().parent / ".open-design").resolve()


class JoshuFrontendHandler(SimpleHTTPRequestHandler):
    """Serve the Joshu web UI directly at / and block directory listings."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def _rewrite_root_path(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path in ("", "/", "/index.html"):
            query = f"?{parsed.query}" if parsed.query else ""
            self.path = f"/auth.html{query}"

    def do_GET(self) -> None:
        self._rewrite_root_path()
        super().do_GET()

    def do_HEAD(self) -> None:
        self._rewrite_root_path()
        super().do_HEAD()

    def list_directory(self, path):  # type: ignore[override]
        self.send_error(404, "Not Found")
        return None


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


def main() -> None:
    raw_port = sys.argv[1] if len(sys.argv) > 1 else os.getenv("FRONTEND_PORT", "3000")
    port = int(raw_port)
    server = ReusableThreadingHTTPServer(("0.0.0.0", port), JoshuFrontendHandler)
    print(f"Serving Joshu frontend on http://localhost:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
