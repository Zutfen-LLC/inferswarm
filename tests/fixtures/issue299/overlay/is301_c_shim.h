// C-compatible observation shim for the #301 overlay (C translation units).
// The linked is301_sink.cpp owns the real state and implements these as
// no-ops unless IS301_OBSERVE=1. Observation-only; never changes behavior.
#ifndef IS301_C_SHIM_H
#define IS301_C_SHIM_H
#ifdef __cplusplus
extern "C" {
#endif
int is301_is_enabled(void);
void is301_record_event(const char * name);
void is301_fact_num(const char * key, long long value);
void is301_fact_str(const char * key, const char * value);
void is301_fact_alloc(long long buffer_bytes, const char * backend);
#ifdef __cplusplus
}
#endif
#endif
