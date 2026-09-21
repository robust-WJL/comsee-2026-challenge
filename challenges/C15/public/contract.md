<!-- Generated from the private challenge catalogue; do not edit. -->
# C15 — Streaming telemetry decoder

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

The request is `{"operations":[...]}`. Operations are
`{"op":"FEED","data":"<hex>"}` or `{"op":"END"}`. The array contains at most
64 FEEDs, exactly one final END, and at most 65,536 total decoded FEED bytes. FEED
chunks form one persistent byte stream. Limits include a 4,096-byte transmitted
payload, 65,536-byte decoded payload, 64 dictionary entries, and 4,096 events.

Domain statuses are `FEED_LIMIT`, `INPUT_LIMIT`, `MAGIC`, `VERSION`, `FLAGS`,
`PAYLOAD_LIMIT`, `CHECKSUM`, `DECOMPRESS_TRUNCATED`, `DECOMPRESS_DISTANCE`,
`DECOMPRESS_LIMIT`, `RECORD_LENGTH`, `DEFINE_LENGTH`, `NAME_ASCII`, `EVENT_LENGTH`,
`RESET_LENGTH`, `RECORD_TYPE`, `UNKNOWN_ID`, `TIMESTAMP_OVERFLOW`,
`DICTIONARY_LIMIT`, `EVENT_LIMIT`, and `TRUNCATED`.

**Response.** ABI-success responses are
`{"status":status,"result":{"feeds":[{"events":[event,...]},...],"state":{"timestamp":u64,"dictionary":[entry,...]}}}`.
Each event is `{"timestamp":u64,"name":string,"value":i32}`. Dictionary entries
are `{"id":u16,"name":string}` and sorted by ascending ID. `status` is `OK` or a
domain status above.
