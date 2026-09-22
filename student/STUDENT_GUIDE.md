# Binary decompilation challenge — student guide

This guide covers the complete local workflow for the
[challenge repository](https://github.com/robust-WJL/comsee-2026-challenge),
introduced at the ComSee 2026.
Run commands from the repository root.

| | |
| --- | --- |
| **Deadline** | **2026-09-29 00:00 KST (UTC+09:00)** |
| **Submit** | [Submission form](https://forms.gle/v8NCbYbLSU1UW5CD8) |
| **Support** | [woojin@friendli.ai](mailto:woojin@friendli.ai) |

You should query binaries, build solutions, run public cases, and package source code on your own machine.
The included tools do not upload your solutions or local test results.

## 1. Set up GLM-5.3

Using **GLM-5.3 through FriendliAI Model API is required on an honor basis**.
The competition submission does not ask for API keys, prompts, transcripts, or
model-usage evidence. Never commit credentials or place them in a submission ZIP.

1. Redeem the **$10 coupon provided at the ComSee 2026 booth** using the
   [promo-code guide](https://friendli.ai/docs/guides/suite/credits#redeeming-promo-codes).
2. Follow the [Model API quickstart](https://friendli.ai/docs/guides/model-apis/quickstart)
   and select model `zai-org/GLM-5.3`.
3. Connect your preferred agent using
   [FriendliLink](https://friendli.ai/docs/examples/agents/friendlilink) (one-click integration setup) or the
   [general agent integration guides](https://friendli.ai/docs/examples/agents/overview).

## 2. Set up and verify your toolchain

```sh
git clone https://github.com/robust-WJL/comsee-2026-challenge.git
cd comsee-2026-challenge
```

The C language standard is **C17**. Grading uses Debian 13 Linux x86-64 with
GCC 14: EASY challenges compile with `-O1`; all others use `-O2`.

The organizer verified the Docker workflow end to end on Apple Silicon macOS.
Intel macOS, Windows/WSL2, and native Linux are documented but were not
independently verified. Contact support if a command behaves differently.

### macOS: Docker Desktop

Install and start [Docker Desktop](https://www.docker.com/products/docker-desktop/).
The helper runs `linux/amd64`; Apple Silicon uses Docker's emulation.

```sh
python3 student/comsee_docker.py build-image
python3 student/comsee_docker.py tutorial --input deadbeef
```

### Windows: Docker Desktop with WSL2

Enable Docker Desktop's WSL2 backend. Keep the repository in the WSL2 Linux
filesystem, install Python, and run all commands inside WSL2 rather than
PowerShell or Command Prompt.

```sh
sudo apt-get update && sudo apt-get install -y python3
python3 student/comsee_docker.py build-image
python3 student/comsee_docker.py tutorial --input deadbeef
```

### Native Debian 13 Linux x86-64

The native workflow uses `student/comsee_tool.py`, not the Docker wrapper.

```sh
sudo apt-get update && sudo apt-get install -y gcc-14 libc6-dev binutils python3
mkdir -p build
gcc-14 -std=c17 -O1 -Wall -Wextra -Werror \
  tutorial/X01-xor/main.c tutorial/X01-xor/reference.c -o build/tutorial-xor
./build/tutorial-xor deadbeef
```

Every setup should print `22`. After a Docker Desktop restart or update, verify
the existing image without rebuilding it:

```sh
python3 student/comsee_docker.py check-image
```

## 3. Query, implement, and validate

Each `challenges/Cxx/public/` directory contains a contract, public cases, and a
solution skeleton. The corresponding stripped reference binary is
`binaries/Cxx`; its digest is listed in `binaries/SHA256SUMS`.

Read the contract first, then query the reference binary:

```sh
# Docker on macOS or Windows/WSL2
python3 student/comsee_docker.py query C01 --binary binaries/C01 \
  --request '{"input":"feff0321"}'

# Native Linux equivalent
python3 student/comsee_tool.py query C01 --binary binaries/C01 \
  --request '{"input":"feff0321"}'
```

The native query command also accepts `--request-file request.json`; the Docker
wrapper accepts inline `--request` only.

Create and edit your solution:

```sh
mkdir -p solutions/C01
cp challenges/C01/public/solution.c solutions/C01/solution.c
```

Extra `.c` and `.h` files may live beside `solution.c`; shared headers may live
under `common/`. Build and validate with the wrapper for your platform:

```sh
# Docker
python3 student/comsee_docker.py build C01
python3 student/comsee_docker.py validate C01

# Native Linux
python3 student/comsee_tool.py build C01
python3 student/comsee_tool.py validate C01
```

`validate` builds the solution and runs every public case in a fresh process.
Passing is provisional: private cases determine the score.

### ABI and JSON rules

```c
int solve(const uint8_t *input, size_t input_len,
          uint8_t *output, size_t output_cap, size_t *output_len);
```

Each buffer contains one UTF-8 JSON document without a terminating NUL. The
input is immutable, buffers never overlap, and a failed call must not publish
partial output.

| Return | Meaning |
| --- | --- |
| `0` | Complete result, including documented domain errors |
| `1` | Output too small; set `*output_len` to the exact required size |
| `2` | Malformed transport |
| `3` | Internal failure |

Reject duplicate keys, unknown fields, missing fields, wrong types, booleans in
place of integers, and non-integer JSON numbers. Accept either hex letter case
on input and emit lowercase. Validate in the order specified by each contract.
Object key order and whitespace do not affect comparison; array order and exact
integer values do.

## 4. Package your source

Run both commands from the repository root:

```sh
python3 student/comsee_zip.py package submission.zip
python3 student/comsee_zip.py check submission.zip
```

The packager accepts only:

- `solutions/Cxx/solution.c`, required for every attempted challenge;
- additional flat `solutions/Cxx/*.c` and `solutions/Cxx/*.h` files; and
- optional flat `common/*.h` files.

Executables, build scripts, symlinks, and other paths are rejected. The limits
are 1 MiB compressed, 4 MiB expanded, 128 files, and 256 KiB per file. `check`
verifies ZIP structure only; validate each challenge separately before upload.

## 5. Submit

Upload a complete ZIP through the [submission form](https://forms.gle/v8NCbYbLSU1UW5CD8)
using the same verified email account and the same Nickname every time.

- At most **10 responses** are counted per verified account. Invalid ZIPs also
  consume a response.
- Among the first ten responses, the latest structurally valid ZIP received
  strictly before the deadline replaces earlier valid submissions.
- Every response must be complete. Files and challenges are never merged across
  responses.
- Structural validity means the ZIP passes the checks above; it does not mean
  the C compiles. A structurally valid replacement remains selected even if a
  challenge fails to compile. That challenge scores zero; other challenges are
  graded independently. The organizer does not fall back to an older ZIP.
- Keep solutions out of public GitHub issues and pull requests.

A Google Forms receipt confirms receipt only. It does not confirm validity,
compilation, acceptance, points, or prize eligibility.

## 6. Scoring and grading limits

C01–C14 are all-or-nothing per challenge: every private case must pass to earn
the points in `student/public_manifest.json`. C15–C17 have cumulative milestones
worth 300, 300, and 400 points. A milestone earns points only when all its cases
and every earlier milestone pass; passing the first two earns 600, while failing
the second leaves 300 even if the third passes.

| Stage | CPU | Wall clock | Memory | Processes | Temp space |
| --- | --- | --- | --- | --- | --- |
| Compile | 30 s | 60 s | 512 MiB | 32 | 64 MiB |
| Each case | 2 s | 5 s | 256 MiB | 8 | 16 MiB |

Each case also caps stdout at 4 MiB and stderr at 64 KiB. Local validation uses
the same 60-second compile and 5-second case wall-clock limits plus output caps,
but does not enforce the final memory, process, CPU, or temporary-space limits.

## Troubleshooting

- If a binary from a downloaded ZIP reports `Permission denied`, run
  `chmod +x binaries/C??` from the repository root. Git clones preserve the mode.
- If Docker rejects a folder mount, allow the folder in Docker Desktop or move
  the repository to an already shared location. On Windows, prefer the WSL2
  Linux filesystem over `/mnt/c/`.
- A `query` that reports `"outcome":"runtime_failure"` with `"returncode":65`
  means the binary rejected the request as malformed transport (ABI return 2).
- Use `python3 student/comsee_docker.py check-image` after Docker updates.
- For unresolved setup or submission problems, contact
  [woojin@friendli.ai](mailto:woojin@friendli.ai).
