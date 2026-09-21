#define _POSIX_C_SOURCE 200809L
#include "comsee.h"

#include <stdio.h>
#include <stdlib.h>

#define INITIAL_OUTPUT 4096u
#define MAX_LINE (1024u * 1024u)
#define MAX_OUTPUT (4u * 1024u * 1024u)

static int read_record(uint8_t *line, size_t *length) {
    size_t used = 0;
    for (;;) {
        int c = fgetc(stdin);
        if (c == EOF) {
            if (ferror(stdin)) return -1;
            if (used == 0) return 0;
            *length = used;
            return 1;
        }
        if (c == '\n') {
            *length = used;
            return 1;
        }
        if (used == MAX_LINE) return -2;
        line[used++] = (uint8_t)c;
    }
}

int main(void) {
    uint8_t *line = malloc(MAX_LINE);
    if (!line) return 70;
    for (;;) {
        size_t len = 0;
        int read_status = read_record(line, &len);
        if (read_status == 0) break;
        if (read_status == -2) { free(line); return 66; }
        if (read_status < 0) { free(line); return 74; }
        size_t cap = INITIAL_OUTPUT, out_len = 0;
        uint8_t *out = malloc(cap + 1);
        if (!out) { free(line); return 70; }
        int rc = solve(line, len, out, cap, &out_len);
        if (rc == COMSEE_OUTPUT_TOO_SMALL) {
            if (out_len > MAX_OUTPUT) { free(out); free(line); return 66; }
            cap = out_len;
            uint8_t *larger = realloc(out, cap + 1);
            if (!larger) { free(out); free(line); return 70; }
            out = larger;
            rc = solve((const uint8_t *)line, len, out, cap, &out_len);
        }
        if (rc != COMSEE_OK || out_len > cap || out_len > MAX_OUTPUT) {
            free(out); free(line); return rc == COMSEE_MALFORMED_TRANSPORT ? 65 : 70;
        }
        if (fwrite(out, 1, out_len, stdout) != out_len || fputc('\n', stdout) == EOF ||
            fflush(stdout) != 0) { free(out); free(line); return 74; }
        free(out);
    }
    free(line);
    return ferror(stdin) ? 74 : 0;
}
