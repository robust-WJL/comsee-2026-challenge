#ifndef COMSEE_H
#define COMSEE_H

#include <stddef.h>
#include <stdint.h>

enum {
    COMSEE_OK = 0,
    COMSEE_OUTPUT_TOO_SMALL = 1,
    COMSEE_MALFORMED_TRANSPORT = 2,
    COMSEE_INTERNAL_FAILURE = 3
};

int solve(const uint8_t *input, size_t input_len,
          uint8_t *output, size_t output_cap, size_t *output_len);

#endif
