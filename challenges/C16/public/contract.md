<!-- Generated from the private challenge catalogue; do not edit. -->
# C16 — Mini-kernel scheduler

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

**Wire request.** The request is exactly `{"tasks":[task,...]}`. A task is exactly
`{"priority":u8,"arrival":0..10000,"script":[instruction,...]}` and its array
index is its task ID. Instructions are exactly `{"op":"CPU"|"SLEEP","ticks":1..10000}`,
`{"op":"LOCK"|"UNLOCK","mutex":0..3}`, or `{"op":"END"}`. Each script is
nonempty and contains exactly one END in final position. Unknown/duplicate/missing fields,
wrong types, booleans, out-of-range scalar values, unknown operations, or misplaced
END are malformed transport (ABI return 2, no output). Validate every task and
instruction before semantic limits. More than eight tasks or more than 128
instructions in any task returns `{"status":"LIMIT","result":null}`.

Runtime statuses are `OK`, `DEADLOCK`, `PROGRAM_ERROR`, and `BUDGET_EXHAUSTED`.
`LIMIT` has a null result; runtime statuses retain scheduler state.

The response is
`{"status":"OK"|"DEADLOCK"|"PROGRAM_ERROR"|"BUDGET_EXHAUSTED","result":{"time":u16,"timeline":[task_id|"IDLE",...],"tasks":[task_state,...],"mutexes":[owner|null,...]}}`.
Each task state is exactly `{"state":"FUTURE"|"READY"|"RUNNING"|"SLEEPING"|"WAITING"|"DONE","completion":time|null,"effective_priority":u8,"waiting_mutex":0..3|null}`.
There are exactly four mutex owner entries. Completion is the boundary time at
which final END executes. Timeline index `t` names the task or IDLE interval
`[t,t+1)`.
