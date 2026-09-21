<!-- Generated from the private challenge catalogue; do not edit. -->
# C10 — Minimal-edit patch generator

Implement this C entry point:

```c
int solve(const uint8_t *input, size_t input_len,
          uint8_t *output, size_t output_cap, size_t *output_len);
```

Each buffer contains one UTF-8 JSON document without a terminating NUL. Input is
immutable, buffers do not overlap, and a failed call publishes no partial output.
Return `0` for a complete response, including domain errors; `1` when the output
buffer is too small and set `*output_len` to the exact required size; `2` for
malformed transport; and `3` for internal failure. The JSONL wrapper accepts one
request per line and emits one response per line. Each graded case starts a fresh
process.

Requests must match the stated schema exactly. Reject malformed JSON, duplicate or
unknown keys, missing fields, wrong types, malformed hex, and booleans used as
integers as transport errors. Integers are exact mathematical integers. Hex byte
strings have two unspaced digits per byte, accept either letter case, and are emitted
in lowercase. The shared JSONL limit is 1 MiB with at most 64 nested containers.

Responses use `{"status":"...","result":...}`. Comparisons ignore JSON object
order and whitespace but preserve array order, bytes, and exact integer values.

The request is `{"source":"<hex>","target":"<hex>"}`. Each decoded string is at
most 128 bytes; otherwise return `LIMIT` with a null result.

Success is `{"status":"OK","result":{"cost":N,"operations":[...]}}`.
Operations apply left-to-right. `{"op":"KEEP"}` consumes and emits the next source
byte; `{"op":"DELETE"}` consumes without emitting; `{"op":"REPLACE","byte":N}`
consumes and emits byte N; `{"op":"INSERT","byte":N}` emits without consuming.
Byte values are integers in `0..255`. Cost counts every operation except KEEP.
