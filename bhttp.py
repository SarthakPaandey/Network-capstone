"""BHTTP/1.0 shared framing + header codec. Stdlib only."""
import struct

HEADER_LEN = 8
MAX_PAYLOAD = 16_777_215          # 24-bit max
MAX_REQ_PAYLOAD = 64 * 1024       # server rejects REQUEST bigger than this (then 400/close)
DATA_CHUNK = 64 * 1024            # max bytes per DATA frame

# Frame types
T_REQUEST = 0x01
T_RESPONSE = 0x02
T_DATA = 0x03
T_PING = 0x00                     # connection-level, id must be 0

F_FIN = 0x01
F_ACK = 0x01  # for PING

STATIC_TABLE = {
    1: "content-type",
    2: "content-length",
    3: "server",
    4: "date",
    5: "last-modified",
    6: "connection",
    7: "host",
    8: "user-agent",
    9: "accept",
    10: "cache-control",
}
STATIC_REVERSE = {v: k for k, v in STATIC_TABLE.items()}


def encode_header(payload_len: int, ftype: int, flags: int, req_id: int) -> bytes:
    assert 0 <= payload_len <= MAX_PAYLOAD
    assert 0 <= ftype <= 255
    assert 0 <= flags <= 255
    assert 0 <= req_id <= 0xFFFFFF
    return bytes([
        (payload_len >> 16) & 0xFF,
        (payload_len >> 8) & 0xFF,
        payload_len & 0xFF,
        ftype & 0xFF,
        flags & 0xFF,
        (req_id >> 16) & 0xFF,
        (req_id >> 8) & 0xFF,
        req_id & 0xFF,
    ])


def decode_header(buf: bytes):
    assert len(buf) == 8
    length = (buf[0] << 16) | (buf[1] << 8) | buf[2]
    return length, buf[3], buf[4], (buf[5] << 16) | (buf[6] << 8) | buf[7]


def encode_headers(headers: list[tuple[str, str]]) -> bytes:
    """headers: list of (name, value), names case-insensitive. Returns nheaders+entries."""
    out = bytearray()
    out += struct.pack("!H", len(headers))
    for name, value in headers:
        lname = name.lower()
        vbytes = value.encode("utf-8")
        if len(vbytes) > 0xFFFF:
            raise ValueError("header value too long")
        idx = STATIC_REVERSE.get(lname)
        if idx is not None:
            out += bytes([idx])
        else:
            nb = lname.encode("ascii", errors="strict")
            if not (1 <= len(nb) <= 255):
                raise ValueError("literal header name length 1..255")
            out += bytes([0, len(nb)]) + nb
        out += struct.pack("!H", len(vbytes)) + vbytes
    return bytes(out)


def decode_headers(buf: bytes, off: int, count: int):
    """Returns (headers_list, new_off). Raises ValueError on malformed."""
    headers = []
    if count > 100:
        raise ValueError("too many headers")
    for _ in range(count):
        if off >= len(buf):
            raise ValueError("truncated header name_ref")
        ref = buf[off]
        off += 1
        if 1 <= ref <= 10:
            name = STATIC_TABLE[ref]
        elif ref == 0:
            if off >= len(buf):
                raise ValueError("truncated literal name len")
            nl = buf[off]
            off += 1
            if nl == 0 or off + nl > len(buf):
                raise ValueError("bad literal name len")
            try:
                name = buf[off:off + nl].decode("ascii").lower()
            except UnicodeError:
                raise ValueError("non-ascii header name")
            off += nl
        else:
            raise ValueError(f"unknown header name_ref {ref}")
        if off + 2 > len(buf):
            raise ValueError("truncated value len")
        (vl,) = struct.unpack_from("!H", buf, off)
        off += 2
        if off + vl > len(buf):
            raise ValueError("truncated header value")
        try:
            value = buf[off:off + vl].decode("utf-8")
        except UnicodeError:
            raise ValueError("non-utf8 header value")
        off += vl
        headers.append((name, value))
    return headers, off


def encode_request(method: str, path: str, headers: list[tuple[str, str]]) -> bytes:
    mb = method.encode("ascii")
    pb = path.encode("utf-8")
    if not (1 <= len(mb) <= 16):
        raise ValueError("method len")
    if not (1 <= len(pb) <= 0xFFFF):
        raise ValueError("path len")
    out = bytearray()
    out += bytes([len(mb)]) + mb
    out += struct.pack("!H", len(pb)) + pb
    out += encode_headers(headers)
    return bytes(out)


def decode_request(payload: bytes):
    if len(payload) < 1:
        raise ValueError("empty request")
    ml = payload[0]
    off = 1
    if not (1 <= ml <= 16) or off + ml > len(payload):
        raise ValueError("bad method")
    try:
        method = payload[off:off + ml].decode("ascii")
    except UnicodeError:
        raise ValueError("non-ascii method")
    off += ml
    if off + 2 > len(payload):
        raise ValueError("no path len")
    (pl,) = struct.unpack_from("!H", payload, off)
    off += 2
    if pl == 0 or off + pl > len(payload):
        raise ValueError("bad path")
    try:
        path = payload[off:off + pl].decode("utf-8")
    except UnicodeError:
        raise ValueError("non-utf8 path")
    off += pl
    if off + 2 > len(payload):
        raise ValueError("no nheaders")
    (nh,) = struct.unpack_from("!H", payload, off)
    off += 2
    headers, off = decode_headers(payload, off, nh)
    if off != len(payload):
        raise ValueError("trailing bytes in request")
    return method, path, headers


def encode_response(status: int, headers: list[tuple[str, str]]) -> bytes:
    out = bytearray()
    out += struct.pack("!H", status)
    out += encode_headers(headers)
    return bytes(out)


def decode_response(payload: bytes):
    if len(payload) < 4:
        raise ValueError("short response")
    (status,) = struct.unpack_from("!H", payload, 0)
    (nh,) = struct.unpack_from("!H", payload, 2)
    headers, off = decode_headers(payload, 4, nh)
    if off != len(payload):
        raise ValueError("trailing bytes in response")
    return status, headers


def hexdump(data: bytes) -> str:
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        hexpart = " ".join(f"{b:02x}" for b in chunk)
        hexpart = hexpart.ljust(16 * 3 - 1)
        asciipart = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{i:08x}  {hexpart}  |{asciipart}|")
    return "\n".join(lines)
