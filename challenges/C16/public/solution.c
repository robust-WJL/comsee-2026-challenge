#include "comsee.h"
#include "comsee_json.h"

int solve(const uint8_t *input, size_t input_len, uint8_t *output,
          size_t output_cap, size_t *output_len) {
  (void)input;
  (void)input_len;
  (void)output;
  (void)output_cap;
  if (output_len != NULL)
    *output_len = 0;
  return COMSEE_INTERNAL_FAILURE;
}
