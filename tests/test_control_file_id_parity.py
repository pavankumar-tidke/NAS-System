"""Shared contract with NAS-Control internal/server/file_id.go (edge agent encoding)."""

from urllib.parse import quote, unquote

COLON_PATH_ID = "path:YWJjL3Rlc3Q"
PLAIN_ID = "507f1f77bcf86cd799439011"


def encode_file_id_for_url(file_id: str) -> str:
    """Match dashboard encodeFileIdForUrl and Go fileIDFromRequest decoding."""
    return quote(file_id, safe="")


def test_path_colon_id_is_url_encoded():
    enc = encode_file_id_for_url(COLON_PATH_ID)
    assert enc == "path%3AYWJjL3Rlc3Q"
    assert unquote(enc) == COLON_PATH_ID


def test_plain_mongo_id_unchanged_when_encoded():
    enc = encode_file_id_for_url(PLAIN_ID)
    assert unquote(enc) == PLAIN_ID
