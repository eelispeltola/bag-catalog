import os

import pytest
import yaml

from bag_catalog.model import load_bag, scan
from bag_catalog.notes import NOTES_FILE, read_notes, write_notes


def test_roundtrip_is_plain_readable_yaml(tmp_path):
    assert write_notes(str(tmp_path), True, "Fogged lens\nafter 5 min\n\n") == ""
    text = (tmp_path / NOTES_FILE).read_text()
    assert "notes: |" in text  # multi-line notes stay readable as a block
    data = yaml.safe_load(text)
    assert data["favorite"] is True and data["notes"] == "Fogged lens\nafter 5 min"
    assert read_notes(str(tmp_path)) == (True, "Fogged lens\nafter 5 min", "")


def test_unknown_keys_survive_and_empty_file_is_removed(tmp_path):
    (tmp_path / NOTES_FILE).write_text("rating: 4\nnotes: old\n")
    write_notes(str(tmp_path), False, "new")
    assert yaml.safe_load((tmp_path / NOTES_FILE).read_text())["rating"] == 4
    (tmp_path / NOTES_FILE).write_text("notes: x\n")
    write_notes(str(tmp_path), False, "  ")
    assert not (tmp_path / NOTES_FILE).exists()
    assert read_notes(str(tmp_path)) == (False, "", "")


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permissions")
def test_read_only_folder_reports_error(tmp_path):
    tmp_path.chmod(0o555)
    try:
        assert "Couldn't save" in write_notes(str(tmp_path), True, "x")
        assert os.listdir(tmp_path) == []
    finally:
        tmp_path.chmod(0o755)


def write_meta(d):
    d.mkdir(parents=True)
    (d / "metadata.yaml").write_text("rosbag2_bagfile_information:\n  duration: {nanoseconds: 1}\n"
                                     "  starting_time: {nanoseconds_since_epoch: 1}\n")
    (d / "data.mcap").write_bytes(b"x" * 5)


def test_notes_belong_to_the_recording_folder(tmp_path):
    write_meta(tmp_path / "16_21" / "bag_a")
    write_meta(tmp_path / "16_21" / "bag_b")
    write_meta(tmp_path / "loose_bag")
    write_notes(str(tmp_path / "16_21"), True, "split recording")
    write_notes(str(tmp_path / "loose_bag"), False, "single bag")
    recs = {r.name: r for r in scan(str(tmp_path))}
    assert (recs["16_21"].favorite, recs["16_21"].notes) == (True, "split recording")
    assert (recs["loose_bag"].favorite, recs["loose_bag"].notes) == (False, "single bag")
    assert len(recs) == 2  # the notes file doesn't make 16_21 look like a bag


def test_loose_bag_notes_dont_touch_cache_keys(tmp_path):
    write_meta(tmp_path / "bag")
    os.utime(tmp_path / "bag" / "data.mcap", (1, 1))
    os.utime(tmp_path / "bag" / "metadata.yaml", (1, 1))
    before = load_bag(str(tmp_path / "bag"))
    write_notes(str(tmp_path / "bag"), True, "hello")
    after = load_bag(str(tmp_path / "bag"))
    assert (after.size, after.mtime, after.extras) == (before.size, before.mtime, before.extras)
