#include <stddef.h>
#include <stdint.h>

/* Unscored, unrelated worked tutorial: XOR all input bytes. */
uint8_t tutorial_xor(const uint8_t *input, size_t length) {
    uint8_t value = 0;
    for (size_t i = 0; i < length; i++) value ^= input[i];
    return value;
}
