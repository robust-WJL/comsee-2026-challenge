# [FriendliAI] Binary Decompilation Challenge at ComSee 2026

This repository contains a binary decompilation challenge introduced at the
ComSee 2026 event. For each task, you receive a stripped Linux x86-64 binary, a public
behavioral contract, and a C solution skeleton. Use GLM-5.3 and your own
judgment to reconstruct a behaviorally equivalent implementation of `solve`,
test it locally, and submit your source code as a ZIP. Grading happens privately
after the deadline.

| | |
| ---- | -------- |
| **Deadline** | **2026-09-29 00:00 KST (UTC+09:00)** |
| **Submit** | [Submission form](https://forms.gle/v8NCbYbLSU1UW5CD8) |
| **Support** | [woojin@friendli.ai](mailto:woojin@friendli.ai) |

For platform-specific setup, the ABI, limits, troubleshooting, and the complete
submission rules, read the [student guide](student/STUDENT_GUIDE.md).

## Use GLM-5.3

Using **GLM-5.3 through FriendliAI Model API is required on an honor basis**.
The competition submission does not ask for API keys, prompts, transcripts, or
model-usage evidence. Never commit an API key or include one in your submission.

Students can use the **$10 promo coupon provided at the ComSee 2026 booth**:

- [Redeem a promo code](https://friendli.ai/docs/guides/suite/credits#redeeming-promo-codes)
- [Set up Model API access](https://friendli.ai/docs/guides/model-apis/quickstart)
- Connect an agent with [FriendliLink](https://friendli.ai/docs/examples/agents/friendlilink)
  or another supported tool using the [agent integration guides](https://friendli.ai/docs/examples/agents/overview)

Select model `zai-org/GLM-5.3`. Human judgment and AI collaboration are central
to this challenge and important when competing for prizes; using the model does
not itself guarantee points or a prize.

## Quick start

```sh
git clone https://github.com/robust-WJL/comsee-2026-challenge.git
cd comsee-2026-challenge
```

The C language standard is **C17**. Grading uses Debian 13 Linux x86-64 and
GCC 14. On macOS and Windows, use Docker Desktop; on Windows, run the commands
inside WSL2.

```sh
# macOS or Windows/WSL2
python3 student/comsee_docker.py build-image
python3 student/comsee_docker.py check-image
python3 student/comsee_docker.py tutorial --input deadbeef
```

Native Debian 13 x86-64 users can use the direct toolchain instead; see the
[setup guide](student/STUDENT_GUIDE.md#2-set-up-and-verify-your-toolchain).
The tutorial should print `22`.

## Solve a challenge

Read `challenges/Cxx/public/contract.md`, then query the supplied binary to
observe its behavior:

```sh
# Docker path; use student/comsee_tool.py instead on native Linux
python3 student/comsee_docker.py query C01 --binary binaries/C01 \
  --request '{"input":"feff0321"}'

mkdir -p solutions/C01
cp challenges/C01/public/solution.c solutions/C01/solution.c
```

Each contract defines the exact request, response, validation order, and error
behavior for that challenge. Query small, boundary, and malformed inputs; record
the results; and use them with the contract to infer the missing behavior. The
binary digests in `binaries/SHA256SUMS` let you confirm that your local copies
match the release.

Implement `solutions/C01/solution.c`. You may add `.c` and `.h` files beside it
and shared headers under `common/`. Then build and run the public cases:

```sh
python3 student/comsee_docker.py build C01
python3 student/comsee_docker.py validate C01
```

Passing public cases is provisional. Private cases determine the score, and
there is no instant private-test feedback. Native Linux uses the matching
`student/comsee_tool.py` commands. The full guide explains the shared `solve`
ABI, strict JSON rules, and common errors.

## Package and submit

From the repository root:

```sh
python3 student/comsee_zip.py package submission.zip
python3 student/comsee_zip.py check submission.zip
```

The ZIP must contain only attempted challenges under `solutions/Cxx/` and
optional shared headers under `common/`. `check` verifies structure, not whether
the C compiles, so validate every attempted challenge before uploading.

Submission rules:

- You may submit at most **10 responses per verified email account**. Every
  response counts, including one with an invalid ZIP.
- Among the first ten responses, the latest structurally valid ZIP received
  strictly before the deadline replaces earlier valid submissions. Upload a
  complete ZIP every time; revisions are never merged.
- A structurally valid ZIP replaces the prior submission even if some C fails
  to compile. A failed challenge scores zero; other challenges are graded
  independently. The organizer does not fall back to an older ZIP.
- C01–C14 are all-or-nothing per challenge. C15–C17 have cumulative milestones
  worth 300, 300, and 400 points: a later milestone earns points only if every
  earlier milestone also passed.
- Use the same verified email account (the same email you signed up for Friendli
  Suite with) and the same Nickname for every response, and keep solutions out of
  public issues and pull requests.

A Google Forms receipt confirms receipt only. It does not confirm structural
validity, compilation, acceptance, points, or prize eligibility.
