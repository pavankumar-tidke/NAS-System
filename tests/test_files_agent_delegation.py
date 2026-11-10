"""File-manager routes must delegate to the agent when agent_mode_enabled()."""

from __future__ import annotations

import inspect

from app.routes import files, files_browse


def _route_paths(module) -> set[str]:
    out: set[str] = set()
    for name, obj in inspect.getmembers(module):
        if name == "router":
            for route in obj.routes:
                if hasattr(route, "path"):
                    out.add(route.path)
    return out


def test_file_manager_browse_routes_registered():
    browse = _route_paths(files_browse)
    assert "/files/browse" in browse
    assert "/files/folders" in browse
    assert "/files/folders/tree" in browse
    assert "/files/move" in browse
    assert "/files/copy" in browse
    assert "/files/rename" in browse
    assert "/files/folders/rename" in browse


def test_file_manager_core_routes_registered():
    core = _route_paths(files)
    assert "/files/upload" in core
    assert "/files" in core  # list files
    assert "/files/download/{file_id}" in core
    assert "/files/preview/{file_id}" in core
    assert "/files/stream/{file_id}" in core
    assert "/files/{file_id}" in core


def test_agent_delegation_guard_present():
    for fn_name in (
        "browse_files",
        "create_folder",
        "move_files",
        "copy_file_route",
        "rename_file_route",
        "rename_folder_route",
        "folder_tree",
        "upload_file",
        "list_files",
        "delete_file",
    ):
        fn = getattr(files_browse, fn_name, None) or getattr(files, fn_name, None)
        assert fn is not None, fn_name
        src = inspect.getsource(fn)
        assert "agent_mode_enabled()" in src, fn_name
