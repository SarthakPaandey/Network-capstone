#!/usr/bin/env python3
"""bcurl: BHTTP/1.0 client. Usage: python bcurl.py [-v] host:port/path [host:port/path ...]"""
import socket
import sys

from bhttp import (
    T_REQUEST, T_RESPONSE, T_DATA, T_PING,
    F_FIN, HEADER_LEN,
    encode_header, decode_header, encode_request, decode_response, hexdump,
)


def parse_target(s: str):
    # Accept: host:port/path, host/path, http://host:port/path
    if "://" in s:
        s = s.split("://", 1)[1]
    # split host:port vs path
    if "/" in s:
        hostport, path = s.split("/", 1)
        path = "/" + path
    else:
        hostport, path = s, "/"
    if ":" in hostport:
        host, port_s = hostport.rsplit(":", 1)
        port = int(port_s)
    else:
        host, port = hostport, 9000
    if not path.startswith("/"):
        path = "/" + path
    return host, port, path


def recvall(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("server closed")
        buf += chunk
    return bytes(buf)


def log_frame(direction: str, hdr_bytes: bytes, payload: bytes, extra: str = ""):
    length, ftype, flags, req_id = decode_header(hdr_bytes)
    sys.stderr.write(f"{direction} frame type=0x{ftype:02x} len={length} flags=0x{flags:02x} id={req_id} {extra}\n")
    sys.stderr.write(hexdump(hdr_bytes + payload) + "\n")
    sys.stderr.flush()


def fetch_on_sock(sock, req_id: int, path: str, host: str, verbose: bool, send_unknown_first: bool = False):
    headers = [("host", host), ("user-agent", "bcurl/1.0"), ("accept", "*/*"), ("connection", "keep-alive")]
    req_payload = encode_request("GET", path, headers)

    if send_unknown_first:
        # Inject an unknown frame (type 0xAA) to prove server skips it.
        junk = b"future-v2-probe"
        frame = encode_header(len(junk), 0xAA, 0x00, req_id) + junk
        if verbose:
            log_frame("-->", frame[:HEADER_LEN], frame[HEADER_LEN:], "(injected UNKNOWN, server MUST skip)")
        sock.sendall(frame)

    frame = encode_header(len(req_payload), T_REQUEST, F_FIN, req_id) + req_payload
    if verbose:
        log_frame("-->", frame[:HEADER_LEN], frame[HEADER_LEN:], f"(REQUEST {path})")
    sock.sendall(frame)

    status = None
    resp_headers = []
    body = bytearray()
    while True:
        hdr = recvall(sock, HEADER_LEN)
        length, ftype, flags, rid = decode_header(hdr)
        payload = recvall(sock, length) if length else b""
        if ftype not in (T_RESPONSE, T_DATA, T_PING):
            if verbose:
                log_frame("<--", hdr, payload, "(UNKNOWN, skipped)")
            continue  # MUST skip unknown
        if ftype == T_PING:
            if verbose:
                log_frame("<--", hdr, payload, "(PING, ignored)")
            continue
        if rid != req_id:
            # Out-of-order from pipelining; v1 client is sequential so this shouldn't happen.
            # Skip frames for other ids rather than fail (forward-compatible).
            if verbose:
                log_frame("<--", hdr, payload, f"(id mismatch want={req_id}, skipped)")
            continue
        if ftype == T_RESPONSE:
            try:
                status, resp_headers = decode_response(payload)
            except ValueError as e:
                raise RuntimeError(f"malformed RESPONSE: {e}")
            if verbose:
                log_frame("<--", hdr, payload, f"(RESPONSE {status})")
            if flags & F_FIN:
                break
        elif ftype == T_DATA:
            body += payload
            if verbose:
                log_frame("<--", hdr, payload,
                          f"(DATA {len(payload)}B total={len(body)}B{' FIN' if flags & F_FIN else ''})")
            if flags & F_FIN:
                break
    if status is None:
        raise RuntimeError("connection ended without RESPONSE")
    return status, resp_headers, bytes(body)


def main():
    verbose = False
    send_unknown = False
    targets = []
    for a in sys.argv[1:]:
        if a == "-v":
            verbose = True
        elif a == "--send-unknown":
            send_unknown = True
        elif a.startswith("-"):
            print(f"unknown flag {a}", file=sys.stderr)
            sys.exit(2)
        else:
            targets.append(a)
    if not targets:
        print(f"usage: {sys.argv[0]} [-v] [--send-unknown] host:port/path [...]", file=sys.stderr)
        sys.exit(2)

    # NEVER open a second connection: one socket for all targets.
    first_host, first_port, _ = parse_target(targets[0])
    for t in targets[1:]:
        h, p, _ = parse_target(t)
        if h != first_host or p != first_port:
            print("bcurl v1: all targets must share host:port (single connection)", file=sys.stderr)
            sys.exit(2)

    sock = socket.create_connection((first_host, first_port))
    try:
        worst = 0
        for i, t in enumerate(targets):
            host, port, path = parse_target(t)
            status, resp_headers, body = fetch_on_sock(
                sock, i + 1, path, host, verbose,
                send_unknown_first=(send_unknown and i == 0))
            if verbose:
                sys.stderr.write(f"== id={i+1} status={status} headers={resp_headers} body={len(body)}B ==\n")
            # body to stdout (binary). For multiple targets, concatenate.
            sys.stdout.buffer.write(body)
            sys.stdout.buffer.flush()
            if status >= 400:
                worst = max(worst, 2)
        sys.exit(worst)
    finally:
        try:
            sock.close()
        except OSError:
            pass


if __name__ == "__main__":
    main()
