"""Agent URL path helpers."""

from urllib.parse import unquote

from app.core.agent_client import agent_path_with_file_id


def test_agent_path_encodes_colon_in_path_id():
    fid = "path:YWJjL3Rlc3Q"
    path = agent_path_with_file_id("/files/stream", fid)
    assert path == "/files/stream/path%3AYWJjL3Rlc3Q"
    assert unquote(path.split("/")[-1]) == fid


def test_agent_path_preserves_plain_uuid():
    fid = "507f1f77bcf86cd799439011"
    assert agent_path_with_file_id("/files", fid) == f"/files/{fid}"
