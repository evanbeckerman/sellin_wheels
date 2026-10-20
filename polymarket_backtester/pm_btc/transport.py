"""Verified TLS, bounded retries, raw-response retention, and request provenance."""
import hashlib
import json
import time
import threading
from datetime import datetime, timezone
from pathlib import Path

import httpx


class SourceError(RuntimeError):
    def __init__(self, message, category="source_error"):
        super().__init__(message)
        self.category = category


class PublicHTTP:
    def __init__(self, directory: Path, client=None, interval=0.05):
        self.directory = Path(directory)
        self.raw = self.directory / "raw"
        self.raw.mkdir(parents=True, exist_ok=True)
        # httpx honors the platform's HTTPS proxy and SSL_CERT_FILE trust configuration.
        # Never set verify=False or copy any credential into artifacts.
        self.client = client or httpx.Client(timeout=25, follow_redirects=True)
        self.interval = interval
        self.last_request = 0.0
        self.rate_lock = threading.Lock()
        self.journal_lock = threading.Lock()

    def close(self):
        self.client.close()

    def get(self, url, params=None, refresh=False):
        request = self.client.build_request("GET", url, params=params)
        public_url = str(request.url)
        key = hashlib.sha256(public_url.encode()).hexdigest()
        receipt_path = self.raw / f"{key}.receipt.json"
        if not refresh and receipt_path.exists():
            receipt = json.loads(receipt_path.read_text())
            body_path = self.raw / receipt["body_file"]
            if body_path.exists() and hashlib.sha256(body_path.read_bytes()).hexdigest() == receipt["sha256"]:
                return json.loads(body_path.read_bytes()), receipt
            raise SourceError("Cached response failed its integrity check", "integrity_error")
        for attempt in range(3):
            with self.rate_lock:
                time.sleep(max(0, self.interval - (time.monotonic() - self.last_request)))
                self.last_request = time.monotonic()
            receipt = {"url": public_url, "retrieved_at": datetime.now(timezone.utc).isoformat(),
                       "attempt": attempt + 1, "status_code": None}
            try:
                response = self.client.send(request)
            except httpx.HTTPError as exc:
                category = "network_policy_denied" if "403" in str(exc) else "network_error"
                receipt.update(error=str(exc), category=category)
                self._journal(receipt)
                raise SourceError(f"{url}: {exc}", category) from exc
            body = response.content
            digest = hashlib.sha256(body).hexdigest()
            body_name = f"{digest}.body"
            (self.raw / body_name).write_bytes(body)
            receipt.update(status_code=response.status_code, sha256=digest, body_file=body_name)
            self._journal(receipt)
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < 2:
                    retry = response.headers.get("Retry-After", "")
                    time.sleep(min(float(retry), 30) if retry.isdecimal() else 2 ** attempt)
                    continue
            if not response.is_success:
                raise SourceError(f"{url}: HTTP {response.status_code}", f"http_{response.status_code}")
            try:
                payload = response.json()
            except ValueError as exc:
                raise SourceError(f"{url}: non-JSON response", "schema_error") from exc
            receipt_path.write_text(json.dumps(receipt, indent=2))
            return payload, receipt
        raise SourceError(f"{url}: retry limit reached")

    def _journal(self, row):
        with self.journal_lock:
            with (self.directory / "requests.jsonl").open("a") as out:
                out.write(json.dumps(row) + "\n")
