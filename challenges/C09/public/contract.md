<!-- Generated from the private challenge catalogue; do not edit. -->
# C09 — Memory-arena simulator

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

The request is `{"arena":integer,"commands":[command,...]}`. Commands are
`{"op":"ALLOC","id":uint32,"size":integer}` or
`{"op":"FREE","id":uint32}`. The arena is `8..65536` bytes and divisible by
eight; allocation sizes are `1..65536`; at most 1,024 commands are allowed. The
top-level domain statuses are `INVALID_ARENA` and `LIMIT`. Command event statuses
are `OK`, `INVALID_SIZE`, `DUPLICATE_ID`, `NO_SPACE`, and `UNKNOWN_ID`. Success is
`{"status":"OK","result":{"events":[...],"free":[{"offset":u,"size":u},...]}}`.
ALLOC success is `{"status":"OK","offset":u}`; FREE success is
`{"status":"OK"}`; an error event contains only its `status`.
