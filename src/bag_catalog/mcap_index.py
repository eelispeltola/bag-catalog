"""Minimal MCAP reader for what the catalog needs, without decoding message payloads:

  - per-topic message timestamps, from the message indexes (a tiny fraction of the file)
  - the first message of a topic, e.g. to read an image's resolution

Finalized files are read through their summary section. Files whose recorder stopped before writing
the summary are walked record by record instead: chunk bodies are skipped, and the message index
written after each chunk is read. Data ends at the first invalid record; recordings that were cut
off often end in a long run of zero bytes.

No ROS needed; runs in the background worker processes.
"""
import struct
from dataclasses import dataclass, field

import numpy as np

MAGIC = b"\x89MCAP0\r\n"
OP_FOOTER, OP_SCHEMA, OP_CHANNEL, OP_MESSAGE, OP_CHUNK, OP_MSG_INDEX, OP_CHUNK_INDEX, OP_DATA_END = \
    0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x0F
FOOTER_LEN = 1 + 8 + 20 + len(MAGIC)


@dataclass
class Index:
    times: dict = field(default_factory=dict)  # topic -> sorted uint64 array of log times (ns)
    first: dict = field(default_factory=dict)  # topic -> (log_time, chunk_offset or None, offset)
    finalized: bool = True
    data_end: int = 0  # file offset where valid data stops


def _str(b, o):
    n, = struct.unpack_from("<I", b, o)
    return bytes(b[o + 4:o + 4 + n]).decode(errors="replace"), o + 4 + n


def _channel(body):
    cid, = struct.unpack_from("<H", body, 0)
    topic, _ = _str(body, 4)
    return cid, topic


def _records(buf):
    """(opcode, body memoryview) for each record in a byte buffer."""
    o = 0
    while o + 9 <= len(buf):
        op, n = buf[o], struct.unpack_from("<Q", buf, o + 1)[0]
        if op == 0 or o + 9 + n > len(buf):
            return
        yield op, memoryview(buf)[o + 9:o + 9 + n]
        o += 9 + n


def _chunk_records(f, chunk_offset):
    """Decompressed records of the chunk whose record starts at chunk_offset."""
    # chunk body: start_time u64, end_time u64, uncompressed_size u64, crc u32, compression str, records
    f.seek(chunk_offset)
    head = f.read(9 + 32)
    if len(head) < 41 or head[0] != OP_CHUNK:
        raise ValueError("not a chunk")
    uncompressed_size, = struct.unpack_from("<Q", head, 9 + 16)
    clen, = struct.unpack_from("<I", head, 9 + 28)
    compression = f.read(clen).decode()
    rlen, = struct.unpack("<Q", f.read(8))
    data = f.read(rlen)
    if compression in ("", "none"):
        return data
    if compression == "lz4":
        import lz4.frame
        return lz4.frame.decompress(data)
    if compression == "zstd":
        import zstandard
        return zstandard.ZstdDecompressor().decompress(data, max_output_size=uncompressed_size)
    raise ValueError(f"unsupported chunk compression {compression!r}")


class _Collector:
    def __init__(self):
        self.channels, self.parts, self.first = {}, {}, {}

    def add_index(self, body, chunk_offset):
        cid, = struct.unpack_from("<H", body, 0)
        rl, = struct.unpack_from("<I", body, 2)
        if not rl:
            return
        arr = np.frombuffer(body, dtype="<u8", count=rl // 8, offset=6).reshape(-1, 2)
        self.parts.setdefault(cid, []).append(arr[:, 0])
        i = int(np.argmin(arr[:, 0]))
        t = int(arr[i, 0])
        if cid not in self.first or t < self.first[cid][0]:
            self.first[cid] = (t, chunk_offset, int(arr[i, 1]))

    def add_message(self, body, record_offset):
        cid, _seq, t = struct.unpack_from("<HIQ", body, 0)
        self.parts.setdefault(cid, []).append(np.array([t], dtype=np.uint64))
        if cid not in self.first or t < self.first[cid][0]:
            self.first[cid] = (t, None, record_offset)

    def result(self, finalized, data_end):
        idx = Index(finalized=finalized, data_end=data_end)
        for cid, parts in self.parts.items():
            topic = self.channels.get(cid, f"<channel {cid}>")
            arr = np.concatenate(parts + ([idx.times[topic]] if topic in idx.times else []))
            idx.times[topic] = np.sort(arr)
            if topic not in idx.first or self.first[cid][0] < idx.first[topic][0]:
                idx.first[topic] = self.first[cid]
        return idx


def read_index(path):
    with open(path, "rb") as f:
        size = f.seek(0, 2)
        f.seek(0)
        if f.read(8) != MAGIC:
            raise ValueError("not an MCAP file")
        if size >= 8 + FOOTER_LEN:
            f.seek(size - FOOTER_LEN)
            tail = f.read(FOOTER_LEN)
            if tail[-8:] == MAGIC and tail[0] == OP_FOOTER:
                summary_start, summary_offset_start, _ = struct.unpack_from("<QQI", tail, 9)
                if summary_start:
                    idx = _from_summary(f, summary_start, (summary_offset_start or size - FOOTER_LEN), size)
                    if idx is not None:
                        return idx
        return _from_scan(f, size)


def _from_summary(f, start, end, size):
    f.seek(start)
    summary = f.read(end - start)
    col, chunks = _Collector(), []
    for op, body in _records(summary):
        if op == OP_CHANNEL:
            cid, topic = _channel(body)
            col.channels[cid] = topic
        elif op == OP_CHUNK_INDEX:
            chunk_offset, = struct.unpack_from("<Q", body, 16)
            mlen, = struct.unpack_from("<I", body, 32)
            offsets = [struct.unpack_from("<HQ", body, 36 + i * 10)[1] for i in range(mlen // 10)]
            idx_len, = struct.unpack_from("<Q", body, 36 + mlen)
            if offsets:
                chunks.append((chunk_offset, min(offsets), idx_len))
    if not chunks:
        return None  # unchunked file: walk it instead
    for chunk_offset, idx_start, idx_len in chunks:
        f.seek(idx_start)
        for op, body in _records(f.read(idx_len)):
            if op == OP_MSG_INDEX:
                col.add_index(body, chunk_offset)
    return col.result(True, size)


def _from_scan(f, size):
    col = _Collector()
    pos, last_chunk = 8, None
    f.seek(pos)
    while True:
        head = f.read(9)
        if len(head) < 9:
            break
        op, n = head[0], struct.unpack_from("<Q", head, 1)[0]
        if op == 0 or pos + 9 + n > size or op in (OP_DATA_END, OP_FOOTER):
            break
        if op == OP_CHANNEL:
            cid, topic = _channel(f.read(n))
            col.channels[cid] = topic
        elif op == OP_MSG_INDEX:
            body = f.read(n)
            cid, = struct.unpack_from("<H", body, 0)
            if cid not in col.channels and last_chunk is not None:
                _channels_in_chunk(f, last_chunk, col)  # rosbag2 writes channel records inside chunks
            col.add_index(body, last_chunk)
        elif op == OP_MESSAGE:
            col.add_message(f.read(min(n, 22)), pos)
        elif op == OP_CHUNK:
            last_chunk = pos
        pos += 9 + n
        f.seek(pos)
    return col.result(False, pos)


def _channels_in_chunk(f, chunk_offset, col):
    here = f.tell()
    try:
        for op, body in _records(_chunk_records(f, chunk_offset)):
            if op == OP_CHANNEL:
                cid, topic = _channel(body)
                col.channels[cid] = topic
    except (ValueError, ImportError, OSError):
        pass
    f.seek(here)


def read_message(path, location):
    """Payload bytes of the message at `location` (an Index.first value)."""
    _t, chunk_offset, offset = location
    with open(path, "rb") as f:
        if chunk_offset is None:
            f.seek(offset)
            head = f.read(9)
            body = f.read(struct.unpack_from("<Q", head, 1)[0])
        else:
            records = _chunk_records(f, chunk_offset)
            n, = struct.unpack_from("<Q", records, offset + 1)
            if records[offset] != OP_MESSAGE:
                raise ValueError("index points at a non-message record")
            body = records[offset + 9:offset + 9 + n]
    return bytes(body[22:])


# --- image resolution from CDR-encoded messages ------------------------------------------
IMAGE_SIZE_TYPES = ("sensor_msgs/msg/CameraInfo", "sensor_msgs/msg/Image", "sensor_msgs/msg/CompressedImage")

def _cdr_header_end(b, end):
    """Offset after std_msgs/Header (stamp + frame_id), relative to the CDR payload start."""
    n, = struct.unpack_from(end + "I", b, 8)
    o = 12 + n
    return o + (-o % 4)


def image_size(msg_type, data):
    """(width, height) from a message of one of IMAGE_SIZE_TYPES, or None."""
    end = "<" if data[1] & 1 else ">"
    b = data[4:]  # skip the CDR encapsulation header; alignment is relative to here
    o = _cdr_header_end(b, end)
    if msg_type in ("sensor_msgs/msg/CameraInfo", "sensor_msgs/msg/Image"):
        h, w = struct.unpack_from(end + "II", b, o)
        return (w, h) if w and h else None
    if msg_type == "sensor_msgs/msg/CompressedImage":
        n, = struct.unpack_from(end + "I", b, o)
        o += 4 + n
        o += -o % 4
        size, = struct.unpack_from(end + "I", b, o)
        return encoded_image_size(bytes(b[o + 4:o + 4 + size]))
    return None


def encoded_image_size(d):
    """(width, height) from the header of a JPEG or PNG, or None."""
    if d[:8] == b"\x89PNG\r\n\x1a\n" and len(d) >= 24:
        return struct.unpack(">II", d[16:24])
    if d[:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 9 < len(d):
        if d[i] != 0xFF:
            i += 1
            continue
        m = d[i + 1]
        if m == 0xFF or m == 0x01 or 0xD0 <= m <= 0xD8:
            i += 1 if m == 0xFF else 2
            continue
        if 0xC0 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):
            h, w = struct.unpack(">HH", d[i + 5:i + 9])
            return w, h
        i += 2 + struct.unpack(">H", d[i + 2:i + 4])[0]
    return None
