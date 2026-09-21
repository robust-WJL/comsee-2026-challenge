#include <stdint.h>
#include <stdio.h>
#include <string.h>

uint8_t tutorial_xor(const uint8_t *input, size_t length);

static int hex_value(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

int main(int argc, char **argv) {
    uint8_t checksum = 0;
    if (argc != 2 || strlen(argv[1]) % 2 != 0) return 64;
    for (size_t i = 0; argv[1][i] != '\0'; i += 2) {
        int high = hex_value(argv[1][i]);
        int low = hex_value(argv[1][i + 1]);
        if (high < 0 || low < 0) return 65;
        uint8_t byte = (uint8_t)((high << 4) | low);
        checksum = tutorial_xor(&byte, 1) ^ checksum;
    }
    printf("%02x\n", checksum);
    return 0;
}
