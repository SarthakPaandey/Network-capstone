# BHTTP/1.0 — Binary HTTP: Specification

**Status:** v1.0. **Transport:** TCP (default port 9000), no TLS. **Endian:** network order (big-endian).
**Goal:** same semantics as HTTP/1.0 GET static-file serving, but every message is length-prefixed binary frames on a persistent connection.

## 1. Framing

Every byte on the wire belongs to a frame: an 8-byte fixed header + `LENGTH` payload bytes.

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|              Payload Length (24)              |     Type (8)  |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|   Flags (8)   |               Request ID (24)                 |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                          Payload (LENGTH bytes) ...
```

* `LENGTH` uint24 BE, 0..16,777,215. Length of payload only.
* `TYPE` uint8. `0x01` REQUEST, `0x02` RESPONSE, `0x03` DATA, `0x00` PING. All other values are **unknown**.
* `FLAGS` uint8. Only bit `0x01` (`FIN`) is defined: last frame of this `Request ID`. All other bits MUST be 0 on send, MUST be ignored on receive.
* `Request ID` uint24 BE. Client picks `1,2,3…` per request on a connection; server echoes it. `0` is reserved for connection-level frames (PING) and is illegal for REQUEST/RESPONSE/DATA.

Receiver MUST read exactly 8 bytes, then exactly LENGTH bytes (loop on partial `recv`). If LENGTH > 16 MiB, close the connection (cannot resync).

### Why 24 / 8 / 8 / 24?

HTTP/2 chose 24 / 8 / 8 / 31 (16 MiB max frame, 256 types, 8 flags, ~2B streams). We keep the first three for the same reasons and shrink the last:

* **24-bit length:** 64 KiB (16-bit) would fragment every image; 32-bit would let one frame claim 4 GiB and OOM the receiver. 16 MiB is large enough for any v1 chunk, small enough to bound allocation. Implementation further caps REQUEST at 64 KiB and DATA chunks at 64 KiB.
* **8-bit type:** 4 types used, 252 left for v2. 4-bit would already be cramped.
* **8-bit flags:** one FIN bit today, 7 spare booleans without a version bump.
* **24-bit ID instead of 31:** v1 has no multiplexing — one exchange at a time per connection, IDs are just sequential counters. 16M exchanges per connection is inexhaustible in practice, and 24+8+8+24 = 64 bits = an 8-byte aligned header (vs HTTP/2's 9-byte unaligned header). Cheaper to parse, 1 byte saved per frame.

## 2. Payload formats

### REQUEST (client → server, `FIN=1` always)

```
method_len u8 (1..16) + method ASCII            # only GET in v1
path_len u16 BE + path UTF-8                    # must start with '/', no NUL
nheaders u16 BE + nheaders × header
```

### RESPONSE (server → client)

```
status u16 BE  # 200,400,403,404,405,500
nheaders u16 BE + nheaders × header
```

Body is **never** inside RESPONSE. If `FIN=1` on RESPONSE there is no body; else 1+ DATA frames with the same ID follow, the last with `FIN=1`.

### DATA (server → client)

Raw file bytes, `LENGTH` bytes. Concatenation of all DATA payloads for the ID = response body. MUST match `content-length` if present.

### PING (optional, `ID=0`)

Any payload; receiver replies same payload with `FLAGS=ACK(0x01)`. Used for keep-alive probes. Unknown to v1-minimal peers it is simply skipped (see below).

## 3. Headers: indexed ten + literal rest

`nheaders` is u16 (receiver MUST reject >100 with 400). Each header:

```
name_ref u8
  1..10  -> static table name (no name bytes on wire)
  0      -> literal: name_len u8 (1..255) + name ASCII lowercase
  11..255 -> MALFORMED (→ 400)
value_len u16 BE + value UTF-8 (0..65535)
```

Static table:

```
1 content-type  2 content-length  3 server  4 date  5 last-modified
6 connection    7 host            8 user-agent  9 accept  10 cache-control
```

This implements HPACK's first two mechanisms (static table index + literal without indexing) without the complexity of dynamic table management or Huffman coding. The ten indexed headers cover all standard headers transmitted by bserve and bcurl.

## 4. Server mapping

`GET path` → strip `?query`/`#frag`, `normpath`, reject `..` escaping root or NUL → **403**. Directory → `index.html`. Missing → **404**. Non-GET → **405**. Undecodable frame/header, `ID=0`, bad name_ref, trailing bytes → **400** (send RESPONSE 400 with same ID, keep connection open). Always include `server`, `date`, `connection: keep-alive`, plus `content-type` (via `mimetypes`, default `application/octet-stream`), `content-length`, `last-modified` on 200.

## 5. Connection lifecycle

Persistent. After a response's final `FIN`, both sides keep the socket open; the next REQUEST reuses it with `ID+1`. Client opens **exactly one** TCP connection per run (even for multiple paths). Server handles each connection in a loop until client closes or a fatal framing error (short read, LENGTH > max).

## 6. Unknown Frame Handling & Forward Compatibility

**A receiver meeting a frame type it does not know MUST skip it cleanly: read LENGTH bytes, discard, continue processing — never close, never send 400 for it.** Same for PING to a peer that doesn't implement it, and for non-zero reserved flag bits (ignore). That is how v2 adds types without breaking v1.
