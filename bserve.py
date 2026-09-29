#!/usr/bin/env python3
"""bserve: BHTTP/1.0 static file server. Usage: python bserve.py ./www 9000"""
import mimetypes
import os
import socket
import sys
import threading
import time
from email.utils import formatdate

import bhttp  # noqa: F401  (keeps shared module explicitly required)
from bhttp import (
    T_REQUEST, T_RESPONSE, T_DATA, T_PING,
    F_FIN, F_ACK, HEADER_LEN, MAX_PAYLOAD, MAX_REQ_PAYLOAD, DATA_CHUNK,
    encode_header, decode_header, decode_request, encode_response,
)

SERVER_NAME = "bserve/1.0"


def http_date_now() -> str:
    return formatdate(time.time(), usegmt=True)


def recvall(conn: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("peer closed")
        buf += chunk
    return bytes(buf)


def send_response(conn, req_id: int, status: int, headers: list, body: bytes = b""):
    # Always send RESPONSE, then DATA frames as needed.
    resp_payload = encode_response(status, headers)
    has_body = len(body) > 0
    conn.sendall(encode_header(len(resp_payload), T_RESPONSE, 0 if has_body else F_FIN, req_id) + resp_payload)
    if has_body:
        for i in range(0, len(body), DATA_CHUNK):
            chunk = body[i:i + DATA_CHUNK]
            last = (i + DATA_CHUNK) >= len(body)
            conn.sendall(encode_header(len(chunk), T_DATA, F_FIN if last else 0, req_id) + chunk)


def safe_join(root: str, path: str):
    # Strip query and fragment components, reject NUL bytes
    raw = path.split("?", 1)[0].split("#", 1)[0]
    if not raw.startswith("/"):
        return None
    if "\x00" in raw:
        return None
    rel = raw.lstrip("/")
    # normalize
    norm = os.path.normpath(rel) if rel else "."
    if norm == ".":
        norm = "index.html"
    # block traversal
    if norm.startswith("..") or os.path.isabs(norm):
        return None
    full = os.path.normpath(os.path.join(root, norm))
    root_abs = os.path.abspath(root)
    full_abs = os.path.abspath(full)
    if full_abs != root_abs and not full_abs.startswith(root_abs + os.sep):
        return None
    if os.path.isdir(full_abs):
        full_abs = os.path.join(full_abs, "index.html")
    return full_abs


def handle_conn(conn: socket.socket, addr, root: str):
    try:
        while True:
            try:
                hdr = recvall(conn, HEADER_LEN)
            except ConnectionError:
                break  # client closed -> normal for keep-alive end
            length, ftype, flags, req_id = decode_header(hdr)
            if length > MAX_PAYLOAD:
                break  # cannot resync; close
            payload = recvall(conn, length) if length else b""

            # Unknown-type rule: MUST skip cleanly (applies to any type we don't implement).
            if ftype not in (T_REQUEST, T_PING):
                # T_RESPONSE/T_DATA from client are unexpected in v1 but also skipped, not errors.
                sys.stderr.write(f"[{addr}] skip unknown/opposite-dir frame type=0x{ftype:02x} len={length} id={req_id}\n")
                sys.stderr.flush()
                continue

            if ftype == T_PING:
                # connection-level only; echo with ACK, same payload
                if req_id != 0:
                    continue  # ignore malformed ping, keep open
                if flags & F_ACK:
                    continue  # ack of our ack; ignore
                conn.sendall(encode_header(len(payload), T_PING, F_ACK, 0) + payload)
                continue

            # --- REQUEST ---
            if req_id == 0:
                send_response(conn, 0, 400, [("content-type", "text/plain"), ("content-length", "11"), ("server", SERVER_NAME), ("date", http_date_now()), ("connection", "keep-alive")], b"bad req id")
                continue
            if length > MAX_REQ_PAYLOAD:
                send_response(conn, req_id, 400, [("content-type", "text/plain"), ("content-length", "16"), ("server", SERVER_NAME), ("date", http_date_now()), ("connection", "keep-alive")], b"request too big")
                continue
            try:
                method, path, req_headers = decode_request(payload)
            except ValueError as e:
                send_response(conn, req_id, 400, [("content-type", "text/plain"), ("content-length", str(len(f"bad frame: {e}"))), ("server", SERVER_NAME), ("date", http_date_now()), ("connection", "keep-alive")], f"bad frame: {e}".encode())
                continue

            if method.upper() != "GET":
                body = b"only GET supported"
                send_response(conn, req_id, 405, [("content-type", "text/plain"), ("content-length", str(len(body))), ("server", SERVER_NAME), ("date", http_date_now()), ("connection", "keep-alive")], body)
                continue

            full = safe_join(root, path)
            if full is None:
                body = b"forbidden"
                send_response(conn, req_id, 403, [("content-type", "text/plain"), ("content-length", str(len(body))), ("server", SERVER_NAME), ("date", http_date_now()), ("connection", "keep-alive")], body)
                continue
            if not os.path.isfile(full):
                body = b"not found: " + path.encode()[:200]
                send_response(conn, req_id, 404, [("content-type", "text/plain"), ("content-length", str(len(body))), ("server", SERVER_NAME), ("date", http_date_now()), ("connection", "keep-alive")], body)
                continue
            try:
                with open(full, "rb") as f:
                    body = f.read()
                if len(body) > 16 * 1024 * 1024:
                    send_response(conn, req_id, 500, [("content-type", "text/plain"), ("server", SERVER_NAME), ("date", http_date_now()), ("connection", "keep-alive")], b"file too large for v1")
                    continue
                ctype, _ = mimetypes.guess_type(full)
                ctype = ctype or "application/octet-stream"
                mtime = formatdate(os.path.getmtime(full), usegmt=True)
                send_response(conn, req_id, 200, [
                    ("content-type", ctype),
                    ("content-length", str(len(body))),
                    ("server", SERVER_NAME),
                    ("date", http_date_now()),
                    ("last-modified", mtime),
                    ("connection", "keep-alive"),
                ], body)
                sys.stderr.write(f"[{addr}] id={req_id} GET {path} -> 200 ({len(body)}B)\n")
            except OSError:
                send_response(conn, req_id, 500, [("content-type", "text/plain"), ("server", SERVER_NAME), ("date", http_date_now()), ("connection", "keep-alive")], b"read error")
    except (ConnectionError, BrokenPipeError, ConnectionResetError):
        pass
    finally:
        try:
            conn.close()
        except OSError:
            pass


def main():
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <root> <port>", file=sys.stderr)
        sys.exit(2)
    root = sys.argv[1]
    port = int(sys.argv[2])
    if not os.path.isdir(root):
        print(f"root not a directory: {root}", file=sys.stderr)
        sys.exit(2)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", port))
    srv.listen(50)
    print(f"bserve/1.0 serving {os.path.abspath(root)} on :{port}", file=sys.stderr)
    try:
        while True:
            conn, addr = srv.accept()
            t = threading.Thread(target=handle_conn, args=(conn, addr, root), daemon=True)
            t.start()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
