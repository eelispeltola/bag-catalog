import textwrap

from bag_catalog.model import Bag, Recording, Topic, load_bag, merged_bags, scan, sensor_label, sensor_of

IMG = "sensor_msgs/msg/CompressedImage"


def test_camera_topics_collapse_to_their_sensor():
    assert sensor_of("/front_camera/image_raw/compressed", IMG) == ("camera", "front_camera")
    assert sensor_of("/front_camera/camera_info", "sensor_msgs/msg/CameraInfo") == ("camera", "front_camera")
    assert sensor_of("/stereo/left/image_raw", "sensor_msgs/msg/Image") == ("camera", "stereo/left")
    assert sensor_of("/stereo/driver/right/image", "sensor_msgs/msg/Image") == ("camera", "stereo/right")


def test_lidar_and_other_topics():
    assert sensor_of("/lidar/points", "sensor_msgs/msg/PointCloud2") == ("pointcloud", "lidar")
    assert sensor_of("/imu/data", "sensor_msgs/msg/Imu") == ("other", "imu")
    assert sensor_of("/tf_static", "tf2_msgs/msg/TFMessage") == ("other", "tf")


def test_sensor_label_splits_parent_and_leaf():
    assert sensor_label(("camera", "stereo/left")) == ("stereo", "left")
    assert sensor_label(("other", "imu")) == ("", "imu")


def bag(name, start, dur, counts):
    return Bag(path=f"/r/{name}", name=name, start_ns=start, duration_ns=dur,
               topics=[Topic(n, IMG, c, ("camera", n.strip("/"))) for n, c in counts.items()])


def test_sensor_status_and_recording_aggregation():
    a = bag("a", 0 + 1, 10, {"/cam": 5})
    b = bag("b", 20 + 1, 10, {"/cam": 0, "/other": 0})
    assert a.sensors() == {("camera", "cam"): "ok"}
    assert b.sensors() == {("camera", "cam"): "empty", ("camera", "other"): "empty"}
    rec = Recording("/r", "r", [a, b])
    assert rec.sensors()[("camera", "cam")] == "ok"  # best status across bags wins
    assert rec.start_ns == 1 and rec.end_ns == 31
    assert rec.coverage() == [(0.0, 1 / 3), (2 / 3, 1.0)]


def test_scan_groups_split_bags_by_parent_dir(tmp_path):
    for i, start in enumerate((5_000_000_000, 1_000_000_000)):
        d = tmp_path / "day1" / "run" / f"bag_{i}"
        d.mkdir(parents=True)
        (d / "bag_0.mcap").write_bytes(b"x" * 10)
        (d / "metadata.yaml").write_text(textwrap.dedent(f"""\
            rosbag2_bagfile_information:
              storage_identifier: mcap
              duration: {{nanoseconds: 2000000000}}
              starting_time: {{nanoseconds_since_epoch: {start}}}
              message_count: 3
              topics_with_message_count:
                - topic_metadata: {{name: /front_camera/image_raw/compressed, type: {IMG}}}
                  message_count: 3
            """))
    (tmp_path / "broken" / "bag").mkdir(parents=True)
    (tmp_path / "broken" / "bag" / "x.mcap").write_bytes(b"")

    recs = {r.name: r for r in scan(str(tmp_path))}
    assert set(recs) == {"day1/run", "broken"}
    run = recs["day1/run"]
    assert [b.name for b in run.bags] == ["bag_0", "bag_1"]
    assert run.start_ns == 1_000_000_000 and run.end_ns == 7_000_000_000
    assert run.bags[0].size == 10 and run.bags[0].storage == "mcap"  # the .mcap only, not metadata.yaml
    assert "metadata.yaml" in recs["broken"].bags[0].error


def test_bags_directly_in_root_are_separate_recordings(tmp_path):
    write_bag(tmp_path / "rosbag2_a", 1_000_000_000)
    write_bag(tmp_path / "rosbag2_b", 9_000_000_000)
    recs = scan(str(tmp_path))
    assert [(r.name, len(r.bags)) for r in recs] == [("rosbag2_a", 1), ("rosbag2_b", 1)]
    assert recs[0].path == str(tmp_path / "rosbag2_a")


def write_bag(d, start):
    d.mkdir(parents=True)
    (d / "metadata.yaml").write_text(textwrap.dedent(f"""\
        rosbag2_bagfile_information:
          storage_identifier: mcap
          duration: {{nanoseconds: 1000000000}}
          starting_time: {{nanoseconds_since_epoch: {start}}}
          topics_with_message_count: []
        """))


def test_scan_all_merges_folders_and_skips_duplicates(tmp_path):
    from bag_catalog.model import scan_all
    write_bag(tmp_path / "a" / "rec1" / "bag", 3_000_000_000)
    write_bag(tmp_path / "b" / "rec2" / "bag", 1_000_000_000)
    a, b = str(tmp_path / "a"), str(tmp_path / "b")
    recs = scan_all([a, b, str(tmp_path / "a" / "rec1"), str(tmp_path / "missing")])
    assert [(r.name, r.root) for r in recs] == [("rec2", b), ("rec1", a)]  # by start time, nested not repeated


def test_root_labels_disambiguate_clashing_basenames():
    from bag_catalog.model import root_labels
    assert root_labels(["/data/rosbags", "/mnt/usb/more_rosbags"]) == {"/data/rosbags": "rosbags", "/mnt/usb/more_rosbags": "more_rosbags"}
    assert root_labels(["/data/rosbags", "/mnt/usb/rosbags", "/home/me/Downloads"]) == \
        {"/data/rosbags": "data/rosbags", "/mnt/usb/rosbags": "usb/rosbags", "/home/me/Downloads": "Downloads"}


def test_thumbnail_camera_follows_the_given_order():
    a = bag("a", 1, 10, {"/front_camera": 5, "/rear_camera": 5})
    b = bag("b", 20, 10, {"/rear_camera": 5})
    b.size = -1  # smallest bag first when several have the camera
    rec = Recording("/r", "r", [a, b])
    assert a.thumb_topic().name == "/front_camera"  # built-in default list
    assert a.thumb_topic(["rear_camera", "front_camera"]).name == "/rear_camera"
    assert rec.thumb_bag(["rear_camera"]) is b
    assert rec.thumb_bag(["front_camera"]) is a
    assert rec.thumb_bag(["side_camera"]) is None and a.thumb_topic([]) is None


def test_merged_bags_are_found_from_their_contents():
    # split by time: two bags one after the other, and a copy holding both
    a = bag("rec_0", 1_000, 100, {"/cam": 10, "/imu": 100})
    b = bag("rec_1", 1_100, 100, {"/cam": 10, "/imu": 100})
    whole = bag("all", 1_000, 200, {"/cam": 20, "/imu": 200})
    assert merged_bags([a, b, whole]) == [(whole, [a, b])]
    # split by topic: cameras and lidar recorded side by side, then merged
    cams = bag("cams", 1_000, 200, {"/cam": 20})
    lidar = bag("lidar", 1_000, 200, {"/lidar": 20})
    both = bag("both", 1_000, 200, {"/cam": 20, "/lidar": 20})
    assert merged_bags([cams, lidar, both]) == [(both, [cams, lidar])]
    gps = bag("gps", 1_050, 10, {"/gps": 5})  # another sensor's short bag inside the span doesn't get in the way
    assert merged_bags([cams, lidar, both, gps]) == [(both, [cams, lidar])]
    # not merged: counts that don't add up, a plain copy of one bag, or bags in other folders
    assert merged_bags([a, b, bag("all", 1_000, 200, {"/cam": 20, "/imu": 199})]) == []
    assert merged_bags([a, bag("copy", 1_000, 100, {"/cam": 10, "/imu": 100})]) == []
    assert merged_bags([whole]) == []


def test_merged_flag_from_name_or_contents(tmp_path):
    for name, start, dur, n in (("bag_0", 1, 10, 3), ("bag_1", 11, 10, 3), ("combined", 1, 20, 6), ("x_merged", 1, 5, 1)):
        d = tmp_path / "run" / name
        d.mkdir(parents=True)
        (d / "metadata.yaml").write_text(textwrap.dedent(f"""\
            rosbag2_bagfile_information:
              storage_identifier: mcap
              duration: {{nanoseconds: {dur * 1_000_000_000}}}
              starting_time: {{nanoseconds_since_epoch: {start * 1_000_000_000}}}
              message_count: {n}
              topics_with_message_count:
                - topic_metadata: {{name: /imu, type: sensor_msgs/msg/Imu}}
                  message_count: {n}
            """))
    bags = {b.name: b for b in scan(str(tmp_path))[0].bags}
    assert bags["combined"].merged and bags["combined"].merged_from == ["bag_0", "bag_1"]
    assert bags["x_merged"].merged and bags["x_merged"].merged_from == []  # by name, as before
    assert not bags["bag_0"].merged and not bags["bag_1"].merged


def test_bag_size_counts_only_its_data_files(tmp_path):
    d = tmp_path / "rec" / "bag"
    d.mkdir(parents=True)
    (d / "bag_0.mcap").write_bytes(b"x" * 100)
    (d / "bag_0.mcap.zstd").write_bytes(b"x" * 40)  # compressed file mode: named in metadata.yaml
    (d / "old_copy.mcap").write_bytes(b"x" * 1000)  # a backup lying in the folder
    (d / "notes.txt").write_bytes(b"x" * 7)
    (d / "metadata.yaml").write_text(textwrap.dedent(f"""\
        rosbag2_bagfile_information:
          storage_identifier: mcap
          duration: {{nanoseconds: 1}}
          starting_time: {{nanoseconds_since_epoch: 1}}
          relative_file_paths: [bag_0.mcap, bag_0.mcap.zstd, missing_1.mcap]
          topics_with_message_count: []
        """))
    assert load_bag(str(d)).size == 140
    (d / "metadata.yaml").unlink()  # without the list: the .mcap / .db3 files
    assert load_bag(str(d)).size == 1100
