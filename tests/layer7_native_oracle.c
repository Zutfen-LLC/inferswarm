// Test adapter for the authenticated pinned x86/quants.c, not a GGML graph.
#include <immintrin.h>
#include <stdint.h>
#include <stddef.h>
float ggml_table_f32_f16[1 << 16];
__attribute__((constructor)) static void init_half_table(void) {
    for (int i=0;i<(1<<16);++i) ggml_table_f32_f16[i]=_cvtsh_ss((uint16_t)i);
}
void quantize_row_q8_0(const float *,void *,int64_t);
void ggml_vec_dot_q8_0_q8_0(int,float *,size_t,const void *,size_t,const void *,size_t,int);
__attribute__((visibility("default"))) void oracle_quant(const float*x,void*q,int n) {
    quantize_row_q8_0(x,q,n);
}
__attribute__((visibility("default"))) float oracle_dot(const void*w,const void*q,int n) {
    float s;ggml_vec_dot_q8_0_q8_0(n,&s,0,w,0,q,0,1);return s;
}
