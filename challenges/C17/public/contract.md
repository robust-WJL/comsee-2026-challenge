<!-- Generated from the private challenge catalogue; do not edit. -->
# C17 — Falling-block game engine

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

**Wire request.** The shared ABI receives exactly
`{"board":[22 rows],"queue":[pieces...],"actions":[actions...]}`. Every board row
is an integer in `0..1023`; bit x is column x. Pieces are `I`, `O`, `T`, `J`, `L`,
`S`, or `Z`. Actions are `WAIT`, `LEFT`, `RIGHT`, `SOFT_DROP`, `HARD_DROP`,
`ROTATE_CW`, `ROTATE_CCW`, or `HOLD`. Duplicate/unknown fields, missing/wrong
types, booleans, out-of-range rows, or an unknown enum anywhere are malformed
transport (ABI return 2, no output).

The board has ten columns and 22 downward-positive rows; rows 0 and 1 are hidden.
The queue has at most 2,049 entries and actions at most 2,048. An initial board with
a complete row returns `INVALID_BOARD`; either collection limit returns `LIMIT`.
Both statuses have a null result.

**Result.** Semantic errors above have null result. A valid simulation returns
`{"status":"OK","result":{"states":[initial,after each processed tick...]}}`.
Each state is exactly `{"board":[22 rows],"active":null|{"piece":"O",` plus
`"orientation":0,"x":3,"y":0},"hold":null|"<piece>","queue_index":N,`
`"gravity":N,"grounded":N,"lines":N,"score":N,"status":"RUNNING"}`.
Terminal state status is `FINISHED` or `GAME_OVER`; null-active states have zero
gravity and grounded counters. Board rows contain locked cells only.
