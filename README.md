# BHTTP/1.0 — Binary HTTP Protocol

A binary application-layer protocol and implementation of static file serving over persistent TCP connections.

## Features

- **64-bit Aligned Framing:** 8-byte fixed frame header (`24-bit Length / 8-bit Type / 8-bit Flags / 24-bit Request ID`) designed for memory safety and word alignment.
- **Static Header Compression:** HPACK-inspired indexing of the 10 most common HTTP headers with length-prefixed fallback for custom headers.
- **Forward Compatibility:** Strict unknown-frame skipping rule allowing future protocol extensions without breaking existing clients or servers.
- **Persistent Connection:** Sequential request pipelining over a single persistent TCP connection.

## Deliverables

- [SPEC.md](SPEC.md): Full protocol specification.
- [HEXDUMP.md](HEXDUMP.md): Annotated byte-by-byte hexdump of a complete exchange.
- `bhttp.py`: Shared framing codec and header serialization.
- `bserve`: Standalone server executable (`./bserve <root_dir> <port>`).
- `bcurl`: Standalone client executable with frame-level tracing (`./bcurl [-v] <host:port/path>`).

## Quickstart

### 1. Start the Server
```bash
./bserve ./www 9000
```

### 2. Run the Client
```bash
# Fetch with annotated frame hexdump
./bcurl -v localhost:9000/hello.txt

# Fetch multiple files sequentially over a single connection
./bcurl localhost:9000/hello.txt localhost:9000/index.html

# Verify forward-compatible unknown-frame handling
./bcurl -v --send-unknown localhost:9000/hello.txt
```
