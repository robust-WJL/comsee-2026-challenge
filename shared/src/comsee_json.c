#include "comsee_json.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    const uint8_t *p;
    size_t n;
    size_t i;
} parser;

static void ws(parser *p) {
    while (p->i < p->n) {
        uint8_t c = p->p[p->i];
        if (c != ' ' && c != '\t' && c != '\r' && c != '\n') break;
        p->i++;
    }
}

static int hexval(uint8_t c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static int parse_u4(parser *p, unsigned *v) {
    unsigned x = 0;
    if (p->n - p->i < 4) return 0;
    for (unsigned j = 0; j < 4; j++) {
        int h = hexval(p->p[p->i++]);
        if (h < 0) return 0;
        x = (x << 4) | (unsigned)h;
    }
    *v = x;
    return 1;
}

static int append_utf8(uint8_t *out, size_t cap, size_t *len, unsigned cp) {
    uint8_t bytes[3];
    size_t count;
    if (cp <= 0x7f) { bytes[0] = (uint8_t)cp; count = 1; }
    else if (cp <= 0x7ff) {
        bytes[0] = (uint8_t)(0xc0 | (cp >> 6));
        bytes[1] = (uint8_t)(0x80 | (cp & 0x3f)); count = 2;
    } else {
        bytes[0] = (uint8_t)(0xe0 | (cp >> 12));
        bytes[1] = (uint8_t)(0x80 | ((cp >> 6) & 0x3f));
        bytes[2] = (uint8_t)(0x80 | (cp & 0x3f)); count = 3;
    }
    if (*len > cap || count > cap - *len) return 0;
    memcpy(out + *len, bytes, count); *len += count;
    return 1;
}

static int string(parser *p, uint8_t *out, size_t cap, size_t *len) {
    *len = 0;
    if (p->i >= p->n || p->p[p->i++] != '"') return 0;
    while (p->i < p->n) {
        uint8_t c = p->p[p->i++];
        if (c == '"') return 1;
        if (c < 0x20) return 0;
        if (c != '\\') {
            if (*len >= cap) return 0;
            out[(*len)++] = c;
            continue;
        }
        if (p->i >= p->n) return 0;
        c = p->p[p->i++];
        if (c == '"' || c == '\\' || c == '/') {
            if (*len >= cap) return 0;
            out[(*len)++] = c;
        } else if (c == 'b' || c == 'f' || c == 'n' || c == 'r' || c == 't') {
            static const uint8_t esc[] = {'\b','\f','\n','\r','\t'};
            const char *names = "bfnrt";
            const char *at = strchr(names, c);
            if (*len >= cap || at == NULL) return 0;
            out[(*len)++] = esc[(size_t)(at - names)];
        } else if (c == 'u') {
            unsigned cp;
            if (!parse_u4(p, &cp)) return 0;
            if (cp >= 0xd800 && cp <= 0xdbff) {
                unsigned low;
                if (p->n - p->i < 6 || p->p[p->i++] != '\\' ||
                    p->p[p->i++] != 'u' || !parse_u4(p, &low) ||
                    low < 0xdc00 || low > 0xdfff) return 0;
                cp = 0x10000u + ((cp - 0xd800u) << 10) + (low - 0xdc00u);
                /* This helper's fields are ASCII; reject four-byte codepoints. */
                return 0;
            }
            if (cp >= 0xdc00 && cp <= 0xdfff) return 0;
            if (!append_utf8(out, cap, len, cp)) return 0;
        } else return 0;
    }
    return 0;
}

int comsee_parse_hex_input(const uint8_t *json, size_t json_len,
                           uint8_t *decoded, size_t decoded_cap,
                           size_t *decoded_len) {
    parser p = {json, json_len, 0};
    uint8_t key[32];
    uint8_t *value = NULL;
    size_t key_len, value_len;
    int seen = 0;
    if (!json || !decoded_len || (!decoded && decoded_cap)) return 0;
    if (json_len > 1024u * 1024u) return 0;
    value = malloc(json_len ? json_len : 1);
    if (!value) return 0;
    ws(&p); if (p.i >= p.n || p.p[p.i++] != '{') goto invalid; ws(&p);
    if (p.i < p.n && p.p[p.i] == '}') goto invalid;
    for (;;) {
        if (!string(&p, key, sizeof key, &key_len)) goto invalid;
        ws(&p); if (p.i >= p.n || p.p[p.i++] != ':') goto invalid; ws(&p);
        if (!string(&p, value, json_len, &value_len)) goto invalid;
        if (key_len != 5 || memcmp(key, "input", 5) != 0 || seen) goto invalid;
        seen = 1;
        if (value_len & 1u) goto invalid;
        for (size_t j = 0; j < value_len; j += 2) {
            int a = hexval(value[j]), b = hexval(value[j + 1]);
            if (a < 0 || b < 0) goto invalid;
            if (j / 2 < decoded_cap)
                decoded[j / 2] = (uint8_t)((a << 4) | b);
        }
        *decoded_len = value_len / 2;
        ws(&p); if (p.i >= p.n) goto invalid;
        if (p.p[p.i++] == '}') break;
        if (p.p[p.i - 1] != ',') goto invalid;
        ws(&p);
    }
    ws(&p);
    if (!seen || p.i != p.n) goto invalid;
    free(value);
    return 1;
invalid:
    free(value);
    return 0;
}

static size_t formatted(char *dst, size_t cap, const char *fmt,
                        unsigned a, unsigned b, unsigned c, int d) {
    char temp[160];
    int n = snprintf(temp, sizeof temp, fmt, a, b, c, d);
    if (n < 0 || (size_t)n >= sizeof temp) return 0;
    size_t need = (size_t)n;
    if (dst && cap >= need) memcpy(dst, temp, need);
    return need;
}

size_t comsee_json_c01_ok(char *dst, size_t cap, unsigned version,
                          unsigned kind, unsigned flags, int measurement) {
    return formatted(dst, cap,
        "{\"status\":\"OK\",\"result\":{\"version\":%u,\"kind\":%u,\"flags\":%u,\"measurement\":%d}}",
        version, kind, flags, measurement);
}

size_t comsee_json_status(char *dst, size_t cap, const char *status) {
    char temp[128];
    int n = snprintf(temp, sizeof temp, "{\"status\":\"%s\",\"result\":null}",
                     status ? status : "");
    if (n < 0 || (size_t)n >= sizeof temp) return 0;
    size_t need = (size_t)n;
    if (dst && cap >= need) memcpy(dst, temp, need);
    return need;
}
