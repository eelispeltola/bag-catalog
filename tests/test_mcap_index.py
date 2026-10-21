import struct

import pytest

from bag_catalog.extract import job_stats, merge_gaps, topic_gaps
from bag_catalog.mcap_index import MAGIC, encoded_image_size, image_size, read_index, read_message


def rec(op, body):
    return bytes([op]) + struct.pack("<Q", len(body)) + body


def s(text):
    b = text.encode()
    return struct.pack("<I", len(b)) + b


def channel(cid, topic):
    return rec(0x04, struct.pack("<HH", cid, 1) + s(topic) + s("cdr") + struct.pack("<I", 0))


def cdr_camera_info(w, h):
    frame = b"cam\x00"
    body = struct.pack("<iI", 0, 0) + struct.pack("<I", len(frame)) + frame  # header: stamp + frame_id
    body += b"\x00" * (-len(body) % 4) + struct.pack("<II", h, w)
    return b"\x00\x01\x00\x00" + body


def write_mcap(path, messages, chunk_size=3, finalize=True, zero_tail=0, compression=""):
    """messages: [(topic, log_time_ns, payload)]. Channel records go inside chunks, like rosbag2."""
    topics = sorted({m[0] for m in messages})
    cids = {t: i + 1 for i, t in enumerate(topics)}
    out = bytearray(MAGIC) + rec(0x01, s("ros2") + s("test"))
    chunk_index, seen = [], set()
    for i in range(0, len(messages), chunk_size):
        part = messages[i:i + chunk_size]
        records, index = bytearray(), {}
        for topic, t, data in part:
            if topic not in seen:
                seen.add(topic)
                records += channel(cids[topic], topic)
            index.setdefault(cids[topic], []).append((t, len(records)))
            records += rec(0x05, struct.pack("<HIQQ", cids[topic], 0, t, t) + data)
        stored = bytes(records)
        if compression == "lz4":
            import lz4.frame
            stored = lz4.frame.compress(stored)
        start = len(out)
        times = [m[1] for m in part]
        out += rec(0x06, struct.pack("<QQQI", min(times), max(times), len(records), 0) + s(compression)
                   + struct.pack("<Q", len(stored)) + stored)
        chunk_len, idx_start, offsets = len(out) - start, len(out), []
        for cid, entries in index.items():
            offsets.append((cid, len(out)))
            out += rec(0x07, struct.pack("<HI", cid, 16 * len(entries)) + b"".join(struct.pack("<QQ", *e) for e in entries))
        chunk_index.append((min(times), max(times), start, chunk_len, offsets, len(out) - idx_start))
    if finalize:
        out += rec(0x0F, struct.pack("<I", 0))
        summary_start = len(out)
        for topic in topics:
            out += channel(cids[topic], topic)
        for t0, t1, start, clen, offsets, ilen in chunk_index:
            m = b"".join(struct.pack("<HQ", c, o) for c, o in offsets)
            out += rec(0x08, struct.pack("<QQQQ", t0, t1, start, clen) + struct.pack("<I", len(m)) + m
                       + struct.pack("<Q", ilen) + s(compression) + struct.pack("<QQ", 0, 0))
        out += rec(0x02, struct.pack("<QQI", summary_start, 0, 0)) + MAGIC
    out += b"\x00" * zero_tail
    path.write_bytes(bytes(out))


def stream(topic, hz, seconds, start=1_000_000_000, skip=()):
    dt = int(1e9 / hz)
    return [(topic, start + i * dt, b"x") for i in range(int(hz * seconds)) if i not in skip]


@pytest.mark.parametrize("finalize", [True, False])
def test_timestamps_from_index_with_and_without_summary(tmp_path, finalize):
    msgs = sorted(stream("/imu", 100, 2) + stream("/cam", 10, 2), key=lambda m: m[1])
    write_mcap(tmp_path / "b.mcap", msgs, finalize=finalize, zero_tail=0 if finalize else 4096)
    idx = read_index(tmp_path / "b.mcap")
    assert idx.finalized is finalize
    assert len(idx.times["/imu"]) == 200 and len(idx.times["/cam"]) == 20
    assert list(idx.times["/cam"][:2]) == [1_000_000_000, 1_100_000_000]


def test_first_message_and_resolution(tmp_path):
    msgs = [("/cam/camera_info", 5, cdr_camera_info(1920, 1020)), ("/cam/camera_info", 9, cdr_camera_info(1, 1))]
    write_mcap(tmp_path / "b.mcap", msgs, compression="lz4")
    idx = read_index(tmp_path / "b.mcap")
    data = read_message(tmp_path / "b.mcap", idx.first["/cam/camera_info"])
    assert image_size("sensor_msgs/msg/CameraInfo", data) == (1920, 1020)


def test_jpeg_and_png_headers():
    jpeg = b"\xff\xd8\xff\xe0\x00\x04ab\xff\xc0\x00\x11\x08\x03\xfc\x07\x80" + b"\x00" * 12
    assert encoded_image_size(jpeg) == (1920, 1020)
    png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 640, 480)
    assert encoded_image_size(png) == (640, 480)


def test_gaps_follow_the_threshold(tmp_path):
    bag = tmp_path / "bag"
    bag.mkdir()
    # 10 Hz, one 0.5 s dropout (4 messages missing), and the stream stops 1 s before the bag ends
    msgs = stream("/cam", 10, 5, skip=range(20, 24))
    write_mcap(bag / "b.mcap", msgs)
    end = 1_000_000_000 + int(5.9e9)
    res = job_stats(str(bag), 1_000_000_000, end, {"/cam": "x/msg/Y"})
    st = res["topics"]["/cam"]
    assert res["finalized"] and st["n"] == 46 and st["median_dt"] == pytest.approx(1e8)
    gaps = topic_gaps(st, 3.0, 0.2)
    assert [round(g[1] / 1e9, 1) for g in gaps] == [0.5, 1.0]  # the dropout, then the early stop
    assert topic_gaps(st, 6.0, 0.2) == [gaps[1]]
    assert topic_gaps(st, 3.0, 2.0) == []
    assert merge_gaps({"/a": [[0, 10]], "/b": [[5, 10], [30, 1]]}) == 2
