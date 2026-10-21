"""Revalidated web assets, with the ordered CSS manifest served as one response."""

import gzip
import re
import threading
from pathlib import Path
from urllib.parse import urlsplit

from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers
from starlette.responses import Response


_IMPORT = re.compile(r"@import\s+url\(\s*(['\"])(/styles/[^'\"]+)\1\s*\)\s*;")


class NoCacheStaticFiles(StaticFiles):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._css_lock = threading.Lock()
        self._css_signature = None
        self._css = None

    def _stylesheet(self):
        root = Path(self.directory).resolve()
        manifest = (root / "style.css").read_text(encoding="utf-8")
        matches = list(_IMPORT.finditer(manifest))
        if not matches:
            raise ValueError("No local stylesheet manifest")
        files = []
        for match in matches:
            path = (root / urlsplit(match[2]).path.lstrip("/")).resolve(strict=True)
            if not path.is_relative_to(root / "styles") or path.suffix != ".css":
                raise ValueError("Unsupported stylesheet import")
            files.append(path)
        signature = (manifest, tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size) for path in files))
        with self._css_lock:
            if signature != self._css_signature:
                # Preserve the exact cascade and all declarations. No minifier,
                # build dependency or change to the editable source manifest.
                contents = iter(path.read_text(encoding="utf-8") for path in files)
                combined = _IMPORT.sub(lambda _match: next(contents), manifest)
                if "@import" in re.sub(r"/\*.*?\*/", "", combined, flags=re.S):
                    raise ValueError("Nested stylesheet imports need the original manifest")
                plain = combined.encode("utf-8")
                self._css = (plain, gzip.compress(plain, compresslevel=5, mtime=0))
                self._css_signature = signature
            return self._css

    async def get_response(self, path, scope):
        response = None
        if path == "style.css" and scope["method"] in {"GET", "HEAD"}:
            try:
                plain, compressed = await run_in_threadpool(self._stylesheet)
                accepted = Headers(scope=scope).get("accept-encoding", "")
                # Explicit q=0 and complex weight negotiation safely use plain CSS.
                zipped = any(part.strip().lower() == "gzip" for part in accepted.split(","))
                body = compressed if zipped else plain
                headers = {"Vary": "Accept-Encoding", "Content-Length": str(len(body))}
                if zipped:
                    headers["Content-Encoding"] = "gzip"
                response = Response(b"" if scope["method"] == "HEAD" else body,
                                    media_type="text/css", headers=headers)
            except (OSError, ValueError, UnicodeError):
                # An in-progress source update retains normal static serving.
                response = None
        if response is None:
            response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
