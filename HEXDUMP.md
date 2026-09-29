# Annotated hexdump — one complete exchange

Captured with `python bcurl.py -v localhost:9000/hello.txt` (body 30 B).
`-->` = client → server, `<--` = server → client. Dates vary per run.

## 1. REQUEST (ID=1, 8 + 61 bytes)

```
--> frame type=0x01 len=61 flags=0x01 id=1 (REQUEST /hello.txt)
00000000  00 00 3d 01 01 00 00 01 03 47 45 54 00 0a 2f 68  |..=......GET../h|
00000010  65 6c 6c 6f 2e 74 78 74 00 04 07 00 09 6c 6f 63  |ello.txt.....loc|
00000020  61 6c 68 6f 73 74 08 00 09 62 63 75 72 6c 2f 31  |alhost...bcurl/1|
00000030  2e 30 09 00 03 2a 2f 2a 06 00 0a 6b 65 65 70 2d  |.0...*/*...keep-|
00000040  61 6c 69 76 65                                   |alive|
```

* Header: `00 00 3d` = LENGTH 61, `01` = REQUEST, `01` = FIN, `00 00 01` = ID 1.
* Payload:
  * `03` + `47 45 54` = method_len 3 + "GET".
  * `00 0a` + `2f 68 65 6c 6c 6f 2e 74 78 74` = path_len 10 + "/hello.txt".
  * `00 04` = 4 headers.
  * `07` + `00 09` + "localhost" = table[7]=host, len 9.
  * `08` + `00 09` + "bcurl/1.0" = table[8]=user-agent.
  * `09` + `00 03` + "2a 2f 2a" (`*/*`) = table[9]=accept.
  * `06` + `00 0a` + "keep-alive" = table[6]=connection.

## 2. RESPONSE (ID=1, 8 + 112 bytes, FIN=0 → body follows)

```
<-- frame type=0x02 len=112 flags=0x00 id=1 (RESPONSE 200)
00000000  00 00 70 02 00 00 00 01 00 c8 00 06 01 00 0a 74  |..p............t|
00000010  65 78 74 2f 70 6c 61 69 6e 02 00 02 33 30 03 00  |ext/plain...30..|
00000020  0a 62 73 65 72 76 65 2f 31 2e 30 04 00 1d 54 75  |.bserve/1.0...Tu|
00000030  65 2c 20 32 39 20 53 65 70 20 32 30 32 36 20 31  |e, 29 Sep 2026 1|
00000040  32 3a 30 39 3a 33 39 20 47 4d 54 05 00 1d 4d 6f  |2:09:39 GMT...Mo|
00000050  6e 2c 20 32 38 20 53 65 70 20 32 30 32 36 20 31  |n, 28 Sep 2026 1|
00000060  32 3a 32 32 3a 34 30 20 47 4d 54 06 00 0a 6b 65  |2:22:40 GMT...ke|
00000070  65 70 2d 61 6c 69 76 65                          |ep-alive|
```

* Header: `00 00 70` = 112 (0x70) payload length, `02` = RESPONSE, `00` = no FIN (DATA frames follow), `00 00 01` = Request ID 1.
* Payload:
  * `00 c8` = HTTP status 200.
  * `00 06` = 6 headers.
  * `01` + `00 0a` + "text/plain" = table[1]=content-type, len 10.
  * `02` + `00 02` + "30" = table[2]=content-length, len 2 ("30").
  * `03` + `00 0a` + "bserve/1.0" = table[3]=server, len 10.
  * `04` + `00 1d` + "Tue, 29 Sep 2026 12:09:39 GMT" = table[4]=date, len 29.
  * `05` + `00 1d` + "Mon, 28 Sep 2026 12:22:40 GMT" = table[5]=last-modified, len 29.
  * `06` + `00 0a` + "keep-alive" = table[6]=connection, len 10.

## 3. DATA (ID=1, 8 + 30 bytes, FIN=1, connection stays open)

```
<-- frame type=0x03 len=30 flags=0x01 id=1 (DATA 30B FIN)
00000000  00 00 1e 03 01 00 00 01 68 65 6c 6c 6f 20 62 69  |........hello bi|
00000010  6e 61 72 79 20 68 74 74 70 0a 73 65 63 6f 6e 64  |nary http.second|
00000020  20 6c 69 6e 65 0a                                | line.|
```

* Header: `00 00 1e` = 30, `03` = DATA, `01` = FIN (last frame of ID 1, **not** end of connection), ID 1.
* Payload is the file bytes: `hello binary http\nsecond line\n` → written to stdout. Exit 0.

## 4. Unknown-type skip (forward-compat proof)

```
--> 00 00 0f aa 00 00 00 01 66 75 74 75 72 65 2d 76 32 2d 70 72 6f 62 65
```

Type `0xaa` is undefined. Server reads LENGTH 15, discards `future-v2-probe`, sends no error, and still answers the following REQUEST with 200. Reproduce: `python bcurl.py -v --send-unknown localhost:9000/hello.txt`.
