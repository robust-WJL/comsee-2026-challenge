#include "comsee.h"
#include "comsee_json.h"

#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define NONE ((size_t)-1)

typedef struct {
    enum comsee_json_type type;
    size_t first;
    size_t next;
    size_t count;
    size_t key_at;
    size_t key_len;
    size_t value_at;
    size_t value_len;
    int bool_value;
} node;

struct comsee_json_doc {
    const uint8_t *input;
    size_t input_len;
    node *nodes;
    size_t node_count;
    size_t node_cap;
    uint8_t *strings;
    size_t strings_len;
    size_t strings_cap;
    size_t root;
};

typedef struct {
    comsee_json_doc *doc;
    size_t at;
    size_t max_depth;
    int internal;
} parser2;

static void skip_ws(parser2 *p) {
    while (p->at < p->doc->input_len) {
        uint8_t c = p->doc->input[p->at];
        if (c != ' ' && c != '\t' && c != '\r' && c != '\n') break;
        p->at++;
    }
}

static int reserve_string(comsee_json_doc *d, size_t add) {
    if (add > d->strings_cap - d->strings_len) return 0;
    return 1;
}

static int push_byte(comsee_json_doc *d, uint8_t value) {
    if (!reserve_string(d, 1)) return 0;
    d->strings[d->strings_len++] = value;
    return 1;
}

static int hex_digit2(uint8_t c) {
    if (c >= '0' && c <= '9') return (int)(c - '0');
    if (c >= 'a' && c <= 'f') return (int)(c - 'a' + 10);
    if (c >= 'A' && c <= 'F') return (int)(c - 'A' + 10);
    return -1;
}

static int u4(parser2 *p, uint32_t *value) {
    uint32_t result = 0;
    if (p->doc->input_len - p->at < 4) return 0;
    for (unsigned i = 0; i < 4; i++) {
        int digit = hex_digit2(p->doc->input[p->at++]);
        if (digit < 0) return 0;
        result = (result << 4) | (uint32_t)digit;
    }
    *value = result;
    return 1;
}

static int utf8(parser2 *p, uint8_t first) {
    const uint8_t *s = p->doc->input;
    size_t n = p->doc->input_len;
    unsigned extra;
    if (first >= 0xc2 && first <= 0xdf) extra = 1;
    else if (first >= 0xe0 && first <= 0xef) extra = 2;
    else if (first >= 0xf0 && first <= 0xf4) extra = 3;
    else return 0;
    if (n - p->at < extra) return 0;
    uint8_t second = s[p->at];
    if ((second & 0xc0u) != 0x80u) return 0;
    if (first == 0xe0 && second < 0xa0) return 0;
    if (first == 0xed && second >= 0xa0) return 0;
    if (first == 0xf0 && second < 0x90) return 0;
    if (first == 0xf4 && second >= 0x90) return 0;
    for (unsigned i = 1; i < extra; i++)
        if ((s[p->at + i] & 0xc0u) != 0x80u) return 0;
    if (!push_byte(p->doc, first) || !reserve_string(p->doc, extra)) return 0;
    for (unsigned i = 0; i < extra; i++)
        p->doc->strings[p->doc->strings_len++] = s[p->at++];
    return 1;
}

static int codepoint(comsee_json_doc *d, uint32_t cp) {
    if (cp <= 0x7f) return push_byte(d, (uint8_t)cp);
    if (cp <= 0x7ff)
        return push_byte(d, (uint8_t)(0xc0 | (cp >> 6))) &&
               push_byte(d, (uint8_t)(0x80 | (cp & 0x3f)));
    if (cp <= 0xffff)
        return push_byte(d, (uint8_t)(0xe0 | (cp >> 12))) &&
               push_byte(d, (uint8_t)(0x80 | ((cp >> 6) & 0x3f))) &&
               push_byte(d, (uint8_t)(0x80 | (cp & 0x3f)));
    return push_byte(d, (uint8_t)(0xf0 | (cp >> 18))) &&
           push_byte(d, (uint8_t)(0x80 | ((cp >> 12) & 0x3f))) &&
           push_byte(d, (uint8_t)(0x80 | ((cp >> 6) & 0x3f))) &&
           push_byte(d, (uint8_t)(0x80 | (cp & 0x3f)));
}

static int decoded_string(parser2 *p, size_t *at, size_t *len) {
    if (p->at >= p->doc->input_len || p->doc->input[p->at++] != '"') return 0;
    *at = p->doc->strings_len;
    while (p->at < p->doc->input_len) {
        uint8_t c = p->doc->input[p->at++];
        if (c == '"') { *len = p->doc->strings_len - *at; return 1; }
        if (c < 0x20) return 0;
        if (c >= 0x80) {
            if (!utf8(p, c)) return 0;
            continue;
        }
        if (c != '\\') {
            if (!push_byte(p->doc, c)) return 0;
            continue;
        }
        if (p->at >= p->doc->input_len) return 0;
        c = p->doc->input[p->at++];
        if (c == '"' || c == '\\' || c == '/') {
            if (!push_byte(p->doc, c)) return 0;
        } else if (c == 'b' || c == 'f' || c == 'n' || c == 'r' || c == 't') {
            const char *names = "bfnrt";
            const uint8_t values[] = {'\b','\f','\n','\r','\t'};
            const char *found = strchr(names, (int)c);
            if (!found || !push_byte(p->doc, values[(size_t)(found - names)])) return 0;
        } else if (c == 'u') {
            uint32_t cp, low;
            if (!u4(p, &cp)) return 0;
            if (cp >= 0xd800 && cp <= 0xdbff) {
                if (p->doc->input_len - p->at < 6 ||
                    p->doc->input[p->at++] != '\\' ||
                    p->doc->input[p->at++] != 'u' || !u4(p, &low) ||
                    low < 0xdc00 || low > 0xdfff) return 0;
                cp = 0x10000u + ((cp - 0xd800u) << 10) + low - 0xdc00u;
            } else if (cp >= 0xdc00 && cp <= 0xdfff) return 0;
            if (!codepoint(p->doc, cp)) return 0;
        } else return 0;
    }
    return 0;
}

static size_t new_node(parser2 *p, enum comsee_json_type type) {
    if (p->doc->node_count >= p->doc->node_cap) return NONE;
    size_t index = p->doc->node_count++;
    node *n = &p->doc->nodes[index];
    memset(n, 0, sizeof *n);
    n->type = type; n->first = NONE; n->next = NONE; n->key_at = NONE;
    return index;
}

static int same_key(const comsee_json_doc *d, size_t child,
                    size_t key_at, size_t key_len) {
    const node *n = &d->nodes[child];
    return n->key_len == key_len &&
           memcmp(d->strings + n->key_at, d->strings + key_at, key_len) == 0;
}

static size_t parse_value(parser2 *p, size_t depth);

static size_t parse_object(parser2 *p, size_t depth) {
    size_t index = new_node(p, COMSEE_JSON_OBJECT), last = NONE;
    if (index == NONE) return NONE;
    p->at++; skip_ws(p);
    if (p->at < p->doc->input_len && p->doc->input[p->at] == '}') { p->at++; return index; }
    for (;;) {
        size_t key_at, key_len;
        if (!decoded_string(p, &key_at, &key_len)) return NONE;
        for (size_t child = p->doc->nodes[index].first; child != NONE;
             child = p->doc->nodes[child].next)
            if (same_key(p->doc, child, key_at, key_len)) return NONE;
        skip_ws(p);
        if (p->at >= p->doc->input_len || p->doc->input[p->at++] != ':') return NONE;
        skip_ws(p);
        size_t child = parse_value(p, depth + 1);
        if (child == NONE) return NONE;
        p->doc->nodes[child].key_at = key_at;
        p->doc->nodes[child].key_len = key_len;
        if (last == NONE) p->doc->nodes[index].first = child;
        else p->doc->nodes[last].next = child;
        last = child; p->doc->nodes[index].count++;
        skip_ws(p);
        if (p->at >= p->doc->input_len) return NONE;
        uint8_t c = p->doc->input[p->at++];
        if (c == '}') return index;
        if (c != ',') return NONE;
        skip_ws(p);
    }
}

static size_t parse_array(parser2 *p, size_t depth) {
    size_t index = new_node(p, COMSEE_JSON_ARRAY), last = NONE;
    if (index == NONE) return NONE;
    p->at++; skip_ws(p);
    if (p->at < p->doc->input_len && p->doc->input[p->at] == ']') { p->at++; return index; }
    for (;;) {
        size_t child = parse_value(p, depth + 1);
        if (child == NONE) return NONE;
        if (last == NONE) p->doc->nodes[index].first = child;
        else p->doc->nodes[last].next = child;
        last = child; p->doc->nodes[index].count++;
        skip_ws(p);
        if (p->at >= p->doc->input_len) return NONE;
        uint8_t c = p->doc->input[p->at++];
        if (c == ']') return index;
        if (c != ',') return NONE;
        skip_ws(p);
    }
}

static int literal(parser2 *p, const char *text) {
    size_t n = strlen(text);
    if (p->doc->input_len - p->at < n ||
        memcmp(p->doc->input + p->at, text, n) != 0) return 0;
    p->at += n;
    return 1;
}

static size_t parse_value(parser2 *p, size_t depth) {
    if (depth > p->max_depth || p->at >= p->doc->input_len) return NONE;
    uint8_t c = p->doc->input[p->at];
    if (c == '{') return parse_object(p, depth);
    if (c == '[') return parse_array(p, depth);
    if (c == '"') {
        size_t index = new_node(p, COMSEE_JSON_STRING);
        if (index == NONE || !decoded_string(p, &p->doc->nodes[index].value_at,
                                              &p->doc->nodes[index].value_len)) return NONE;
        return index;
    }
    if (c == 'n') {
        if (!literal(p, "null")) return NONE;
        return new_node(p, COMSEE_JSON_NULL);
    }
    if (c == 't' || c == 'f') {
        int value = c == 't';
        if (!literal(p, value ? "true" : "false")) return NONE;
        size_t index = new_node(p, COMSEE_JSON_BOOL);
        if (index != NONE) p->doc->nodes[index].bool_value = value;
        return index;
    }
    size_t start = p->at;
    if (c == '-') p->at++;
    if (p->at >= p->doc->input_len) return NONE;
    c = p->doc->input[p->at];
    if (c == '0') p->at++;
    else if (c >= '1' && c <= '9') {
        do { p->at++; } while (p->at < p->doc->input_len &&
            p->doc->input[p->at] >= '0' && p->doc->input[p->at] <= '9');
    } else return NONE;
    if (p->at < p->doc->input_len) {
        c = p->doc->input[p->at];
        if (c == '.' || c == 'e' || c == 'E' || (c >= '0' && c <= '9')) return NONE;
    }
    size_t index = new_node(p, COMSEE_JSON_INTEGER);
    if (index != NONE) {
        p->doc->nodes[index].value_at = start;
        p->doc->nodes[index].value_len = p->at - start;
    }
    return index;
}

int comsee_json_parse(const uint8_t *data, size_t len, size_t max_nodes,
                      size_t max_depth, comsee_json_doc **out) {
    if (!out || (!data && len) || len > 1024u * 1024u || max_nodes == 0 || max_depth == 0)
        return 0;
    *out = NULL;
    comsee_json_doc *d = calloc(1, sizeof *d);
    if (!d) return -1;
    if (max_nodes > SIZE_MAX / sizeof(node)) { free(d); return -1; }
    d->nodes = calloc(max_nodes, sizeof(node));
    d->strings = malloc(len ? len : 1);
    if (!d->nodes || !d->strings) {
        free(d->nodes); free(d->strings); free(d); return -1;
    }
    d->input = data; d->input_len = len; d->node_cap = max_nodes; d->strings_cap = len;
    parser2 p = {d, 0, max_depth, 0};
    skip_ws(&p);
    size_t root = parse_value(&p, 0);
    skip_ws(&p);
    if (root == NONE || p.at != len) {
        comsee_json_doc_free(d); return 0;
    }
    d->root = root; *out = d; return 1;
}

void comsee_json_doc_free(comsee_json_doc *d) {
    if (!d) return;
    free(d->nodes); free(d->strings); free(d);
}

static int valid_node(const comsee_json_doc *d, size_t n) { return d && n < d->node_count; }
size_t comsee_json_root(const comsee_json_doc *d) { return d ? d->root : NONE; }
enum comsee_json_type comsee_json_typeof(const comsee_json_doc *d, size_t n) {
    return valid_node(d, n) ? d->nodes[n].type : COMSEE_JSON_NULL;
}
size_t comsee_json_array_size(const comsee_json_doc *d, size_t n) {
    return valid_node(d,n) && d->nodes[n].type == COMSEE_JSON_ARRAY ? d->nodes[n].count : 0;
}
size_t comsee_json_object_size(const comsee_json_doc *d, size_t n) {
    return valid_node(d,n) && d->nodes[n].type == COMSEE_JSON_OBJECT ? d->nodes[n].count : 0;
}

static int child_at(const comsee_json_doc *d, size_t n, size_t at, size_t *value) {
    if (!value || !valid_node(d,n)) return 0;
    size_t child = d->nodes[n].first;
    while (child != NONE && at) { child = d->nodes[child].next; at--; }
    if (child == NONE) return 0;
    *value = child; return 1;
}
int comsee_json_array_at(const comsee_json_doc *d, size_t n, size_t at, size_t *value) {
    return valid_node(d,n) && d->nodes[n].type == COMSEE_JSON_ARRAY &&
           child_at(d,n,at,value);
}

int comsee_json_array_next(const comsee_json_doc *d, size_t n,
                           size_t *cursor, size_t *value) {
    if (!valid_node(d, n) || d->nodes[n].type != COMSEE_JSON_ARRAY ||
        !cursor || !value) {
        return 0;
    }
    size_t child;
    if (*cursor == SIZE_MAX) {
        child = d->nodes[n].first;
    } else if (*cursor >= d->node_count) {
        return 0;
    } else {
        child = *cursor;
    }
    if (child == NONE || !valid_node(d, child)) {
        return 0;
    }
    *value = child;
    *cursor = d->nodes[child].next == NONE
        ? d->node_count
        : d->nodes[child].next;
    return 1;
}
int comsee_json_object_get(const comsee_json_doc *d, size_t n,
                           const char *key, size_t *value) {
    if (!valid_node(d,n) || d->nodes[n].type != COMSEE_JSON_OBJECT || !key || !value) return 0;
    size_t key_len = strlen(key);
    for (size_t child=d->nodes[n].first; child!=NONE; child=d->nodes[child].next) {
        node *item = &d->nodes[child];
        if (item->key_len == key_len && memcmp(d->strings+item->key_at,key,key_len)==0) {
            *value=child; return 1;
        }
    }
    return 0;
}
int comsee_json_object_only(const comsee_json_doc *d, size_t n,
                            const char *const *keys, size_t key_count) {
    if (!valid_node(d,n) || d->nodes[n].type != COMSEE_JSON_OBJECT) return 0;
    for (size_t child=d->nodes[n].first; child!=NONE; child=d->nodes[child].next) {
        int found=0;
        for (size_t k=0;k<key_count;k++) {
            size_t len=strlen(keys[k]); node *item=&d->nodes[child];
            if (item->key_len==len && memcmp(d->strings+item->key_at,keys[k],len)==0) {found=1;break;}
        }
        if (!found) return 0;
    }
    return 1;
}
int comsee_json_string(const comsee_json_doc *d,size_t n,const uint8_t **bytes,size_t *len){
    if(!valid_node(d,n)||d->nodes[n].type!=COMSEE_JSON_STRING||!bytes||!len)return 0;
    *bytes=d->strings+d->nodes[n].value_at;*len=d->nodes[n].value_len;return 1;
}
int comsee_json_string_equal(const comsee_json_doc*d,size_t n,const char*s){
    const uint8_t*b;size_t len,want=s?strlen(s):0;
    return s&&comsee_json_string(d,n,&b,&len)&&len==want&&memcmp(b,s,len)==0;
}

static int magnitude(const comsee_json_doc *d, size_t n, uint64_t *value,
                     int *negative) {
    if (!valid_node(d, n) || d->nodes[n].type != COMSEE_JSON_INTEGER ||
        !value || !negative) return 0;
    const node *item = &d->nodes[n];
    size_t i = 0;
    uint64_t result = 0;
    *negative = 0;
    if (d->input[item->value_at] == '-') { *negative = 1; i++; }
    for (; i < item->value_len; i++) {
        unsigned digit = d->input[item->value_at + i] - '0';
        if (result > (UINT64_MAX - digit) / 10) return 0;
        result = result * 10 + digit;
    }
    *value = result;
    return 1;
}

int comsee_json_u64(const comsee_json_doc *d, size_t n, uint64_t *value) {
    int negative;
    if (!magnitude(d, n, value, &negative)) return 0;
    return !negative || *value == 0;
}

int comsee_json_i64(const comsee_json_doc *d, size_t n, int64_t *value) {
    uint64_t mag;
    int negative;
    if (!value || !magnitude(d, n, &mag, &negative)) return 0;
    if (!negative) {
        if (mag > INT64_MAX) return 0;
        *value = (int64_t)mag;
        return 1;
    }
    if (mag > (uint64_t)INT64_MAX + 1u) return 0;
    *value = mag == (uint64_t)INT64_MAX + 1u ? INT64_MIN : -(int64_t)mag;
    return 1;
}

int comsee_json_hex_size(const comsee_json_doc *d, size_t n, size_t *decoded) {
    const uint8_t *bytes;
    size_t len;
    if (!decoded || !comsee_json_string(d, n, &bytes, &len) || (len & 1u)) return 0;
    for (size_t i = 0; i < len; i++)
        if (hex_digit2(bytes[i]) < 0) return 0;
    *decoded = len / 2;
    return 1;
}

int comsee_json_hex_decode(const comsee_json_doc *d, size_t n, uint8_t *out,
                           size_t cap) {
    const uint8_t *bytes;
    size_t len, decoded;
    if (!comsee_json_string(d, n, &bytes, &len) ||
        !comsee_json_hex_size(d, n, &decoded) || decoded > cap || (!out && decoded))
        return 0;
    for (size_t i = 0; i < decoded; i++)
        out[i] = (uint8_t)((hex_digit2(bytes[2*i]) << 4) |
                           hex_digit2(bytes[2*i+1]));
    return 1;
}

typedef struct { char kind; size_t count; int pending; } frame;
struct comsee_json_writer {
    uint8_t *data;
    size_t len, cap, max;
    frame stack[64];
    size_t depth;
    int root, error;
};

static int grow(comsee_json_writer *w, size_t add) {
    if (!w || w->error || add > w->max - w->len) {
        if (w) w->error = 1;
        return 0;
    }
    size_t need = w->len + add;
    if (need <= w->cap) return 1;
    size_t cap = w->cap ? w->cap : 128;
    while (cap < need) {
        if (cap > w->max / 2) { cap = w->max; break; }
        cap *= 2;
    }
    uint8_t *data = realloc(w->data, cap);
    if (!data) { w->error = 1; return 0; }
    w->data = data; w->cap = cap;
    return 1;
}

static int raw(comsee_json_writer *w, const void *data, size_t len) {
    if (!grow(w, len)) return 0;
    memcpy(w->data + w->len, data, len);
    w->len += len;
    return 1;
}

static int before(comsee_json_writer *w) {
    if (!w || w->error) return 0;
    if (!w->depth) {
        if (w->root) { w->error = 1; return 0; }
        w->root = 1;
        return 1;
    }
    frame *top = &w->stack[w->depth - 1];
    if (top->kind == 'a') {
        if (top->count && !raw(w, ",", 1)) return 0;
        top->count++;
        return 1;
    }
    if (!top->pending) { w->error = 1; return 0; }
    top->pending = 0;
    top->count++;
    return 1;
}

static int valid_utf8(const uint8_t *s, size_t n) {
    if (!s && n) return 0;
    for (size_t i = 0; i < n;) {
        uint8_t first = s[i++];
        if (first < 0x80) continue;
        unsigned extra;
        if (first >= 0xc2 && first <= 0xdf) extra = 1;
        else if (first >= 0xe0 && first <= 0xef) extra = 2;
        else if (first >= 0xf0 && first <= 0xf4) extra = 3;
        else return 0;
        if (n - i < extra || (s[i] & 0xc0u) != 0x80u) return 0;
        if (first == 0xe0 && s[i] < 0xa0) return 0;
        if (first == 0xed && s[i] >= 0xa0) return 0;
        if (first == 0xf0 && s[i] < 0x90) return 0;
        if (first == 0xf4 && s[i] >= 0x90) return 0;
        for (unsigned j = 1; j < extra; j++)
            if ((s[i + j] & 0xc0u) != 0x80u) return 0;
        i += extra;
    }
    return 1;
}

static int quoted(comsee_json_writer *w, const uint8_t *s, size_t n) {
    if (!valid_utf8(s, n)) { if (w) w->error = 1; return 0; }
    if (!raw(w, "\"", 1)) return 0;
    for (size_t i = 0; i < n; i++) {
        uint8_t c = s[i];
        const char *escape = NULL;
        if (c == '"') escape = "\\\"";
        else if (c == '\\') escape = "\\\\";
        else if (c == '\b') escape = "\\b";
        else if (c == '\f') escape = "\\f";
        else if (c == '\n') escape = "\\n";
        else if (c == '\r') escape = "\\r";
        else if (c == '\t') escape = "\\t";
        if (escape) {
            if (!raw(w, escape, 2)) return 0;
        } else if (c < 0x20) {
            char buffer[7];
            int count = snprintf(buffer, sizeof buffer, "\\u%04x", c);
            if (count != 6 || !raw(w, buffer, 6)) return 0;
        } else if (!raw(w, &c, 1)) return 0;
    }
    return raw(w, "\"", 1);
}

comsee_json_writer *comsee_json_writer_new(size_t max) {
    if (!max) return NULL;
    comsee_json_writer *writer = calloc(1, sizeof *writer);
    if (writer) writer->max = max;
    return writer;
}
void comsee_json_writer_free(comsee_json_writer *w) {
    if (w) { free(w->data); free(w); }
}
static int begin(comsee_json_writer *w, char kind, char open) {
    if (!before(w) || w->depth >= 64 || !raw(w, &open, 1)) {
        if (w) w->error = 1;
        return 0;
    }
    w->stack[w->depth++] = (frame){kind, 0, 0};
    return 1;
}
int comsee_json_object_begin(comsee_json_writer *w) { return begin(w, 'o', '{'); }
int comsee_json_array_begin(comsee_json_writer *w) { return begin(w, 'a', '['); }
static int end(comsee_json_writer *w, char kind, char close) {
    if (!w || w->error || !w->depth || w->stack[w->depth-1].kind != kind ||
        w->stack[w->depth-1].pending) {
        if (w) w->error = 1;
        return 0;
    }
    w->depth--;
    return raw(w, &close, 1);
}
int comsee_json_object_end(comsee_json_writer *w) { return end(w, 'o', '}'); }
int comsee_json_array_end(comsee_json_writer *w) { return end(w, 'a', ']'); }
int comsee_json_key(comsee_json_writer *w, const char *key) {
    if (!w || !key || w->error || !w->depth) {
        if (w) w->error = 1;
        return 0;
    }
    frame *top = &w->stack[w->depth-1];
    if (top->kind != 'o' || top->pending) { w->error = 1; return 0; }
    if (top->count && !raw(w, ",", 1)) return 0;
    if (!quoted(w, (const uint8_t *)key, strlen(key)) || !raw(w, ":", 1)) return 0;
    top->pending = 1;
    return 1;
}
int comsee_json_string_value(comsee_json_writer *w, const uint8_t *bytes, size_t len) {
    return before(w) && quoted(w, bytes, len);
}
int comsee_json_cstring_value(comsee_json_writer *w, const char *value) {
    if (!value) { if (w) w->error = 1; return 0; }
    return comsee_json_string_value(w, (const uint8_t *)value, strlen(value));
}
int comsee_json_hex_value(comsee_json_writer *w, const uint8_t *bytes, size_t len) {
    static const uint8_t digits[] = "0123456789abcdef";
    if ((!bytes && len) || len > (SIZE_MAX - 2) / 2 || !before(w) ||
        !raw(w, "\"", 1)) {
        if (w) w->error = 1;
        return 0;
    }
    for (size_t i = 0; i < len; i++) {
        uint8_t pair[2] = {digits[bytes[i] >> 4], digits[bytes[i] & 15u]};
        if (!raw(w, pair, 2)) return 0;
    }
    return raw(w, "\"", 1);
}
static int number(comsee_json_writer *w, const char *text, size_t len) {
    return before(w) && raw(w, text, len);
}
int comsee_json_u64_value(comsee_json_writer *w, uint64_t value) {
    char buffer[32];
    int count = snprintf(buffer, sizeof buffer, "%" PRIu64, value);
    return count > 0 && number(w, buffer, (size_t)count);
}
int comsee_json_i64_value(comsee_json_writer *w, int64_t value) {
    char buffer[32];
    int count = snprintf(buffer, sizeof buffer, "%" PRId64, value);
    return count > 0 && number(w, buffer, (size_t)count);
}
int comsee_json_null_value(comsee_json_writer *w) { return number(w, "null", 4); }
int comsee_json_bool_value(comsee_json_writer *w, int value) {
    return number(w, value ? "true" : "false", value ? 4 : 5);
}
int comsee_json_writer_finish(comsee_json_writer *w, uint8_t *out, size_t cap,
                              size_t *len) {
    if (!w || !len || w->error || w->depth || !w->root || (!out && cap))
        return COMSEE_INTERNAL_FAILURE;
    *len = w->len;
    if (cap < w->len) return COMSEE_OUTPUT_TOO_SMALL;
    memcpy(out, w->data, w->len);
    return COMSEE_OK;
}
