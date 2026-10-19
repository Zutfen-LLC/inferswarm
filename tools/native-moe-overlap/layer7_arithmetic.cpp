// Offline x86 CPU helper only. No GGML execution, CUDA, network or model load.
// Equations follow llama.cpp b29c606e, not a replacement benchmark comparator.
#include <cmath>
#include <cfenv>
#include <cstdint>
#include <cstring>
#include <immintrin.h>

// Read-only guard for the exact operand-check profile. Existing reconstruction
// entry points retain their historical behavior.
extern "C" int l7_environment_ok() {
    return std::fegetround()==FE_TONEAREST && (_mm_getcsr() & 0xe040)==0;
}

static float scale(const uint8_t * p) {
    uint16_t h; std::memcpy(&h,p,2); return _cvtsh_ss(h);
}
extern "C" void l7_quantize(const float * x, int n, uint8_t * out, int cuda_rn) {
    for (int b=0;b<n/32;++b) {
        float a=0;
        for (int j=0;j<32;++j) a=std::fmax(a,std::fabs(x[b*32+j]));
        const float d=a/127.0f, inverse=a?127.0f/a:0;
        const uint16_t h=_cvtss_sh(d,0); std::memcpy(out+b*34,&h,2);
        for (int j=0;j<32;++j) {
            const float v=x[b*32+j];
            // CUDA model uses correctly rounded host division here. The actual
            // -use_fast_math device quotient/quantized bytes were NOT retained.
            const int q=a?(cuda_rn?int(std::round(v/d)):int(std::nearbyint(v*inverse))):0;
            out[b*34+2+j]=uint8_t(int8_t(q));
        }
    }
}
extern "C" float l7_dot_cpu(const uint8_t * w,const uint8_t * q,int n) {
    float lanes[8]={};
    for (int b=0;b<n/32;++b) {
        const float d=scale(w+b*34)*scale(q+b*34);
        for (int l=0;l<8;++l) {
            int s=0;
            for (int j=0;j<4;++j) s+=int8_t(w[b*34+2+4*l+j])*int8_t(q[b*34+2+4*l+j]);
            lanes[l]=std::fma(d,float(s),lanes[l]);
        }
    }
    float s[4];for(int j=0;j<4;++j)s[j]=lanes[j+4]+lanes[j];
    return (s[0]+s[2])+(s[1]+s[3]);
}
extern "C" float l7_dot_cuda(const uint8_t * w,const uint8_t * q,int n,int fused) {
    // Q8_0 qi=8,vdr=2;32-lane dedicated multi-token MMVQ MoE kernel.
    float lanes[32]={};
    for (int l=0;l<32;++l) {
        for (int b=l/4;b<n/32;b+=8) {
            int s=0;
            for(int j=0;j<8;++j) s+=int8_t(w[b*34+2+(l%4)*8+j])*int8_t(q[b*34+2+(l%4)*8+j]);
            const float d=scale(w+b*34)*scale(q+b*34);
            if(fused) lanes[l]=std::fma(d,float(s),lanes[l]);
            else { volatile float product=d*float(s);lanes[l]+=product; }
        }
    }
    for(int offset=16;offset;offset/=2) {
        float previous[32];std::memcpy(previous,lanes,sizeof(lanes));
        for(int l=0;l<32;++l)lanes[l]=previous[l]+previous[l^offset];
    }
    return lanes[0];
}
