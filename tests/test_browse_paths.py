"""Browse filepath helpers (human-readable STORAGE_PATH layout)."""

from __future__ import annotations

import re

from app.services import browse_service as bs


def test_direct_children_filepath_regex_root():
    pattern = bs._direct_children_filepath_regex("")
    assert re.match(pattern, "readme.pdf")
    assert not re.match(pattern, "Tes/foo.pdf")


def test_direct_children_filepath_regex_nested():
    pattern = bs._direct_children_filepath_regex("Tes")
    assert re.match(pattern, "Tes/foo.pdf")
    assert not re.match(pattern, "Tes/sub/foo.pdf")
    assert not re.match(pattern, "Other/foo.pdf")


def test_normalize_rel_path_strips_backslashes():
    assert bs.normalize_rel_path(r"Tes\Mobile") == "Tes/Mobile"
