#include "comsee.h"
#include "comsee_json.h"

/* Implement the shared solve ABI. The supplied parser and writers handle C17's
 * transport; replace this function body with your recovered replay engine. */
int solve(const uint8_t *input, size_t input_len,
          uint8_t *output, size_t output_cap, size_t *output_len) {
    (void)input; (void)input_len; (void)output; (void)output_cap;
    if (output_len) *output_len = 0;
    return COMSEE_INTERNAL_FAILURE;
}
