from uw_scan.audit import compress_json_payload, sha256_text


def test_compress_json_payload_round_trip():
    encoded = compress_json_payload({"ticker": "NVDA", "value": "123.45"})
    assert encoded.content_encoding == "gzip"
    assert encoded.payload_size_bytes > 0
    assert encoded.decompressed_json() == {"ticker": "NVDA", "value": "123.45"}


def test_sha256_text_is_stable():
    assert sha256_text("abc") == sha256_text("abc")
    assert sha256_text("abc") != sha256_text("abcd")
