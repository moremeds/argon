from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass
from typing import Any


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CompressedPayload:
    payload_compressed: bytes
    content_encoding: str
    content_sha256: str
    payload_size_bytes: int

    def decompressed_json(self) -> Any:
        return json.loads(gzip.decompress(self.payload_compressed).decode("utf-8"))


def compress_json_payload(payload: Any) -> CompressedPayload:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return CompressedPayload(
        payload_compressed=gzip.compress(raw),
        content_encoding="gzip",
        content_sha256=hashlib.sha256(raw).hexdigest(),
        payload_size_bytes=len(raw),
    )
