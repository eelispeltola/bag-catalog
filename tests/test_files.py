import os

import pytest

from bag_catalog.files import atomic_write, read_cache, write_cache


def test_atomic_write_replaces_the_file_and_leaves_nothing_behind(tmp_path):
    path = tmp_path / "a.yaml"
    path.write_text("old")
    atomic_write(str(path), "new")
    assert path.read_text() == "new" and os.listdir(tmp_path) == ["a.yaml"]
    assert oct(path.stat().st_mode & 0o777) == "0o644"


def test_a_failed_write_keeps_the_old_file(tmp_path):
    path = tmp_path / "a.yaml"
    path.write_text("old")
    with pytest.raises(TypeError):
        atomic_write(str(path), b"not text")
    assert path.read_text() == "old" and os.listdir(tmp_path) == ["a.yaml"]


def test_caches_that_are_missing_or_damaged_read_as_none(tmp_path):
    f = tmp_path / "stats" / "x.json"
    assert read_cache(str(f)) is None
    write_cache(str(f), {"finalized": True})
    assert read_cache(str(f)) == {"finalized": True}
    f.write_text('{"finalized": tr')  # as if the app was killed while writing it
    assert read_cache(str(f)) is None
