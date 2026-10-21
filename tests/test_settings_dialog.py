import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # no display needed

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from bag_catalog import profile  # noqa: E402
from bag_catalog.ui.settings import SettingsDialog  # noqa: E402


@pytest.fixture
def dialog(tmp_path, monkeypatch):
    monkeypatch.setattr(profile, "USER_FILE", str(tmp_path / "user.yaml"))
    app = QApplication.instance() or QApplication([])
    dlg = SettingsDialog(profile.load([str(tmp_path)]), {"front_camera", "rear_camera"}, [str(tmp_path)])
    yield dlg
    dlg.deleteLater()
    app.processEvents()


def test_import_fills_the_pages_with_the_files_settings(dialog, tmp_path):
    f = tmp_path / "shared.yaml"
    f.write_text("gaps: {factor: 4}\nthumbnails: {cameras: [rear_camera]}\nsensors: {aliases: {a: b}, bogus: 1}\n")
    dialog.import_file(str(f))
    assert dialog.file_status.text().startswith("Imported 3 settings from")
    assert "unknown setting 'sensors.bogus'" in dialog.error.text()
    values = dialog.collect()
    assert values["gaps", "factor"] == 4.0 and values["thumbnails", "cameras"] == ["rear_camera"]
    assert values["sensors", "aliases"] == {"a": "b"}
    assert values["gaps", "min_s"] == profile.DEFAULTS["gaps"]["min_s"]  # not in the file: unchanged
    assert not dialog.fields["gaps", "factor"][1].isHidden()  # its Reset link shows it differs now


def test_import_of_a_broken_file_changes_nothing(dialog, tmp_path):
    f = tmp_path / "broken.yaml"
    f.write_text("gaps: [")
    before = dialog.collect()
    dialog.import_file(str(f))
    assert dialog.file_status.text().startswith("No settings found") and "broken.yaml" in dialog.error.text()
    assert dialog.collect() == before


def test_export_writes_what_differs_from_the_defaults(dialog, tmp_path):
    dialog.fields["gaps", "factor"][0].set(4.0)  # an edit not saved yet is exported too
    out = tmp_path / "mine.yaml"
    dialog.export_file(str(out))
    assert dialog.file_status.text() == f"Exported 1 setting to {out}."
    text = out.read_text()
    assert text.startswith("# bag-catalog settings.") and "factor: 4.0" in text
    assert profile.read(str(out), []) == {"gaps": {"factor": 4.0}}  # and imports back


def test_export_as_a_folder_profile_says_where_it_applies(dialog, tmp_path):
    dialog.fields["gaps", "min_s"][0].set(0.5)
    dialog.export_file(str(tmp_path / profile.FOLDER_FILE))
    assert "applies to that folder and the folders inside it" in dialog.file_status.text()


def test_nothing_to_export(dialog, tmp_path):
    dialog.export_file(str(tmp_path / "x.yaml"))
    assert dialog.file_status.text().startswith("Nothing to export") and not (tmp_path / "x.yaml").exists()


def test_number_limits_are_checked(dialog):
    errors = []
    assert profile.parse({"gaps": {"factor": 51}}, "f", errors) == {} and errors == ["f: gaps.factor should be at most 50"]
    assert dialog.fields["gaps", "factor"][0].widget.maximum() == 50  # the same limit as the Gaps menu
