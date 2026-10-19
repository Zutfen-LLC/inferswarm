// Offline x86 CPU helper only. No GGML execution, CUDA, network or model load.
// Equations follow llama.cpp b29c606e, not a replacement benchmark comparator.
#include <cmath>
#include <cfenv>
#include <algorithm>
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

// Conservative Q8_0 MMVQ envelope, independent of float summation order.
// Integer lane sums are exact. There are at most 4*nblocks float partials;
// 8*nblocks+64 rounding steps covers separate mul/add as well as FMA and
// all supported 1/2/4/8-token MMVQ reductions. Scales are exact F16 operands.
extern "C" void l7_dot_bounds(const uint8_t * w,const uint8_t * low,
        const uint8_t * high,int n,double * out) {
    double lower=0,upper=0,mass=0;
    const double inf=INFINITY;
    for(int b=0;b<n/32;++b) {
        int il=0,iu=0,absolute=0;
        for(int j=0;j<32;++j) {
            int a=int8_t(w[b*34+2+j]),l=int8_t(low[b*34+2+j]),h=int8_t(high[b*34+2+j]);
            il+=std::min(a*l,a*h);iu+=std::max(a*l,a*h);
            absolute+=std::abs(a)*std::max(std::abs(l),std::abs(h));
        }
        double a=double(scale(w+b*34))*scale(low+b*34);
        double c=double(scale(w+b*34))*scale(high+b*34);
        double l=std::min(std::min(a*il,a*iu),std::min(c*il,c*iu));
        double h=std::max(std::max(a*il,a*iu),std::max(c*il,c*iu));
        lower=std::nextafter(lower+l,-inf);upper=std::nextafter(upper+h,inf);
        mass=std::nextafter(mass+std::max(std::abs(a),std::abs(c))*absolute,inf);
    }
    const double nu=(8.0*(n/32)+64)*0x1p-24;
    const double error=std::nextafter((nu/(1-nu))*mass,inf);
    out[0]=std::nextafter(lower-error,-inf);out[1]=std::nextafter(upper+error,inf);
}
