import pytest

from bag_catalog import extract
from bag_catalog.extract import cacheable, geo_dist, job_stats, job_track, track_distance
from bag_catalog.fmt import fmt_dist, fmt_dur, fmt_size, plural


def test_formatting():
    assert fmt_dur(3_725e9) == "1:02:05"
    assert fmt_size(512) == "512 B"
    assert fmt_size(1_500_000_000) == "1.5 GB"
    assert fmt_size(8_687_183_281) == "8.7 GB"  # a bag as GNOME Files shows it
    assert fmt_size(999_949) == "999.9 kB" and fmt_size(999_950) == "1.0 MB"
    assert fmt_dist(950) == "950 m"
    assert fmt_dist(2604) == "2.60 km"
    assert (plural(1, "gap"), plural(0, "gap"), plural(3, "topic")) == ("1 gap", "0 gaps", "3 topics")


def test_geo_dist_one_degree_of_latitude():
    assert geo_dist((35.0, 139.0), (36.0, 139.0)) == pytest.approx(111_195, rel=1e-3)


def test_track_distance_respects_time_window():
    track = {"source": "odom", "pts": [[0, 0, 0], [10, 3, 4], [20, 3, 14]]}
    assert track_distance(track) == pytest.approx(15)
    assert track_distance(track, 10, 20) == pytest.approx(10)


def test_a_failing_route_candidate_falls_through_to_the_next(monkeypatch):
    def points(path, storage, topic, typ, gnss):
        if gnss:
            raise LookupError("my_msgs/msg/GnssFix is not installed")
        return [[0, 0.0, 0.0], [1, 5.0, 0.0]]
    monkeypatch.setattr(extract, "_track_points", points)
    cands = [("/b", "mcap", "/gnss", "my_msgs/msg/GnssFix", 0), ("/b", "mcap", "/odom", "nav_msgs/msg/Odometry", 0)]
    res = job_track(cands, gnss_types={"my_msgs/msg/GnssFix"})
    assert res["source"] == "odom" and res["topic"] == "/odom" and "error" not in res and cacheable(res)
    res = job_track(cands[:1], gnss_types={"my_msgs/msg/GnssFix"})
    assert res["source"] is None and "not installed" in res["error"] and not cacheable(res)  # retried next time


def test_bags_without_mcap_files_are_not_measured_again(tmp_path):
    (tmp_path / "bag_0.db3").write_bytes(b"")
    res = job_stats(str(tmp_path), 0, 1, {})
    assert res["error"] == "not an MCAP bag" and cacheable(res)
    (tmp_path / "bag_0.mcap").write_bytes(b"not mcap")
    assert not cacheable(job_stats(str(tmp_path), 0, 1, {}))  # a damaged file might be readable later
