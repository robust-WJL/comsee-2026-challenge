#ifndef COMSEE_JSON_H
#define COMSEE_JSON_H

#include <stddef.h>
#include <stdint.h>

/* Parses exactly {"input":"<hex>"}. JSON whitespace and key order are
 * immaterial; unknown/missing/duplicate keys and malformed hex are rejected.
 * JSON escapes are decoded before field-name and hexadecimal validation. */
int comsee_parse_hex_input(const uint8_t *json, size_t json_len,
                           uint8_t *decoded, size_t decoded_cap,
                           size_t *decoded_len);

/* JSON writers return the exact byte length excluding any NUL. They never write
 * partially when cap is too small. */
size_t comsee_json_c01_ok(char *dst, size_t cap, unsigned version,
                          unsigned kind, unsigned flags, int measurement);
size_t comsee_json_status(char *dst, size_t cap, const char *status);

typedef struct comsee_json_doc comsee_json_doc;
typedef struct comsee_json_writer comsee_json_writer;

enum comsee_json_type {
    COMSEE_JSON_OBJECT,
    COMSEE_JSON_ARRAY,
    COMSEE_JSON_STRING,
    COMSEE_JSON_INTEGER,
    COMSEE_JSON_NULL,
    COMSEE_JSON_BOOL
};

/* Generic strict JSON transport. parse returns 1 on success, 0 for malformed
 * transport, and -1 for allocation/internal failure. All object keys are decoded
 * and duplicate decoded keys are rejected at every depth. */
int comsee_json_parse(const uint8_t *data, size_t len, size_t max_nodes,
                      size_t max_depth, comsee_json_doc **out);
void comsee_json_doc_free(comsee_json_doc *doc);
size_t comsee_json_root(const comsee_json_doc *doc);
enum comsee_json_type comsee_json_typeof(const comsee_json_doc *doc, size_t node);
size_t comsee_json_array_size(const comsee_json_doc *doc, size_t node);
int comsee_json_array_at(const comsee_json_doc *doc, size_t node, size_t index,
                         size_t *value);
/* Linear array iteration. Set cursor to SIZE_MAX before the first call. Each
 * successful call stores one child in value and advances cursor. */
int comsee_json_array_next(const comsee_json_doc *doc, size_t node,
                           size_t *cursor, size_t *value);
size_t comsee_json_object_size(const comsee_json_doc *doc, size_t node);
int comsee_json_object_get(const comsee_json_doc *doc, size_t node,
                           const char *ascii_key, size_t *value);
int comsee_json_object_only(const comsee_json_doc *doc, size_t node,
                            const char *const *ascii_keys, size_t key_count);
int comsee_json_string(const comsee_json_doc *doc, size_t node,
                       const uint8_t **bytes, size_t *len);
int comsee_json_string_equal(const comsee_json_doc *doc, size_t node,
                             const char *ascii);
int comsee_json_i64(const comsee_json_doc *doc, size_t node, int64_t *value);
int comsee_json_u64(const comsee_json_doc *doc, size_t node, uint64_t *value);
int comsee_json_hex_size(const comsee_json_doc *doc, size_t node,
                         size_t *decoded_len);
int comsee_json_hex_decode(const comsee_json_doc *doc, size_t node,
                           uint8_t *output, size_t output_cap);

/* The writer owns a private bounded buffer. Functions return 0 after any misuse,
 * size-limit, or allocation failure; callers map that to COMSEE_INTERNAL_FAILURE.
 * finish returns COMSEE_OK or COMSEE_OUTPUT_TOO_SMALL and never partially writes. */
comsee_json_writer *comsee_json_writer_new(size_t max_bytes);
void comsee_json_writer_free(comsee_json_writer *writer);
int comsee_json_object_begin(comsee_json_writer *writer);
int comsee_json_object_end(comsee_json_writer *writer);
int comsee_json_array_begin(comsee_json_writer *writer);
int comsee_json_array_end(comsee_json_writer *writer);
int comsee_json_key(comsee_json_writer *writer, const char *ascii_key);
int comsee_json_string_value(comsee_json_writer *writer,
                             const uint8_t *bytes, size_t len);
int comsee_json_cstring_value(comsee_json_writer *writer, const char *value);
int comsee_json_hex_value(comsee_json_writer *writer,
                          const uint8_t *bytes, size_t len);
int comsee_json_u64_value(comsee_json_writer *writer, uint64_t value);
int comsee_json_i64_value(comsee_json_writer *writer, int64_t value);
int comsee_json_null_value(comsee_json_writer *writer);
int comsee_json_bool_value(comsee_json_writer *writer, int value);
int comsee_json_writer_finish(comsee_json_writer *writer, uint8_t *output,
                              size_t output_cap, size_t *output_len);

#endif
