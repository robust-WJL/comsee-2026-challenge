# Worked tutorial: XOR checksum

This unscored example is unrelated to the 17 challenge algorithms and is never
included in scoring. There is no stripped tutorial binary to query: both sources
are supplied, and the point is to confirm that your toolchain compiles and runs a
C program the same way the grader will.

`main.c` decodes one hexadecimal byte string from `argv[1]`; `reference.c`
implements the core, which XORs all decoded bytes into an eight-bit accumulator.
The result prints as two lowercase hex digits.

Build and run it through the helper for your platform:

```sh
# Docker on macOS or Windows/WSL2
python3 student/comsee_docker.py tutorial --input deadbeef

# Native Debian 13 Linux x86-64
mkdir -p build
gcc-14 -std=c17 -O1 -Wall -Wextra -Werror \
  tutorial/X01-xor/main.c tutorial/X01-xor/reference.c -o build/tutorial-xor
./build/tutorial-xor deadbeef
```

The expected checksum is `22`. An empty string is valid and prints `00`; equal
bytes cancel, so `--input aaaa` also prints `00`. An odd-length argument exits
64 and a non-hexadecimal argument exits 65.

To practice the workflow you will actually use on the challenges — querying a
stripped binary, recording observations, and comparing parsed output — read
`challenges/C01/public/contract.md` and query `binaries/C01`.
