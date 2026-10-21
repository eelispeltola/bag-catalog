from pathlib import Path

import yaml

from bag_catalog import profile
from bag_catalog.model import sensor_of

IMG = "sensor_msgs/msg/Image"


def test_dump_reads_back_unchanged():
    errors = []
    assert profile.overlay(profile.DEFAULTS, profile.parse(yaml.safe_load(profile.dump(profile.DEFAULTS)), "dump",
                                                           errors)) == profile.DEFAULTS
    assert errors == []
    partial = {"gaps": {"min_s": 0.5}}
    assert profile.parse(yaml.safe_load(profile.dump(partial)), "dump", errors) == partial


def test_parse_keeps_valid_settings_and_reports_the_rest():
    errors = []
    out = profile.parse({
        "thumbnails": {"cameras": ["rear"], "offset_s": 2},  # an int is fine for a number
        "gaps": {"factor": 1.0, "min_s": "0.5"},  # below the floor; text
        "map": {"tile_url": "https://example.org/tiles.png"},  # no {z}/{x}/{y}
        "sensors": {"aliases": ["tf"], "cameras": []},  # wrong type; unknown key
        "colours": {},
    }, "test.yaml", errors)
    assert out == {"thumbnails": {"cameras": ["rear"], "offset_s": 2.0}}
    assert errors == [
        "test.yaml: gaps.factor should be at least 1.5",
        "test.yaml: gaps.min_s should be a number",
        "test.yaml: map.tile_url should contain {z}, {x} and {y}",
        "test.yaml: sensors.aliases should be a mapping of names, like  old: new",
        "test.yaml: unknown setting 'sensors.cameras'",
        "test.yaml: unknown section 'colours'",
    ]


def test_layers_folder_files_then_your_own(tmp_path, monkeypatch):
    monkeypatch.setattr(profile, "USER_FILE", str(tmp_path / "user.yaml"))
    (tmp_path / "user.yaml").write_text("thumbnails: {offset_s: 3}\n")
    for name, factor in (("a", 5), ("b", 6)):
        (tmp_path / name / "day1").mkdir(parents=True)
        (tmp_path / name / profile.FOLDER_FILE).write_text(f"gaps: {{factor: {factor}, min_s: 1}}\n")
    (tmp_path / "c").mkdir()
    (tmp_path / "c" / profile.FOLDER_FILE).write_text("gaps: [")

    layers = profile.load([str(tmp_path / "a" / "day1"), str(tmp_path / "b")])
    assert layers.used == [str(tmp_path / f) for f in ("b/bag_catalog.yaml", "a/bag_catalog.yaml", "user.yaml")]
    assert layers.errors == []
    assert layers.values["gaps"] == {"factor": 5.0, "min_s": 1.0}  # the first folder wins
    assert layers.origin["gaps", "factor"] == str(tmp_path / "a" / profile.FOLDER_FILE)
    assert layers.values["thumbnails"]["offset_s"] == 3.0 and layers.base["thumbnails"]["offset_s"] == 1.0

    layers = profile.load([str(tmp_path / "c")])
    assert layers.values["gaps"] == profile.DEFAULTS["gaps"]
    assert len(layers.errors) == 1 and "bag_catalog.yaml" in layers.errors[0]


def test_your_changes_are_kept_only_where_they_differ_from_below():
    base = profile.overlay(profile.DEFAULTS, {"gaps": {"factor": 5.0}})
    user = profile.apply_changes({}, {("gaps", "factor"): 4.0, ("gaps", "min_s"): base["gaps"]["min_s"]}, base)
    assert user == {"gaps": {"factor": 4.0}}
    assert profile.apply_changes(user, {("gaps", "factor"): 5.0}, base) == {}  # back to the folder's value


def test_written_files_read_back(tmp_path):
    settings = {"sensors": {"aliases": {"stereo/left": "left_camera"}}, "map": {"attribution": "© Example"}}
    profile.write(str(tmp_path / "p.yaml"), settings, profile.USER_HEADER)
    errors = []
    assert profile.read(str(tmp_path / "p.yaml"), errors) == settings and errors == []


def test_sensor_rules_from_a_profile():
    rules = profile.overlay(profile.DEFAULTS, {"sensors": {
        "ignored_segments": ["sensing"], "camera_suffixes": ["image_rect"],
        "aliases": {"stereo/left": "left_camera", "tf_static": "tf_static"},
    }})["sensors"]
    assert sensor_of("/sensing/stereo/left/image_rect", IMG, rules) == ("camera", "left_camera")
    assert sensor_of("/stereo/left/image_raw", IMG, rules) == ("camera", "stereo/left/image_raw")
    assert sensor_of("/tf_static", "tf2_msgs/msg/TFMessage", rules) == ("other", "tf_static")


def test_example_profile_is_valid():
    errors = []
    example = Path(__file__).parent.parent / "examples" / profile.FOLDER_FILE
    settings = profile.read(str(example), errors)
    assert errors == []
    assert set(settings) == set(yaml.safe_load(example.read_text()))  # every section in the file was accepted
