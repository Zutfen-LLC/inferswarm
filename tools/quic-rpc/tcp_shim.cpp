// Only ABI glue. The TCP TLS handshake and full-I/O loops are unchanged Strata code.
#include "strata/worker/tls.hpp"
#include <openssl/x509v3.h>
#include <new>
extern "C" {
bool bench_validate(const char* ca,const char* cert,const char* key,const char* peer) {
    strata::worker::TlsConfig c{ca,cert,key,peer};std::string err;return c.validate(err);
}
void* bench_tls(int fd, const char* ca, const char* cert, const char* key,
                const char* peer, bool server, int ms) {
    auto* s = new(std::nothrow) strata::worker::TlsSession;
    if (!s) return nullptr;
    strata::worker::TlsConfig c{ca, cert, key, peer};
    std::string err;
    if (!s->handshake(fd, c, server, ms, {}, err)) { delete s; return nullptr; }
    return s;
}
bool bench_send(void* s, const unsigned char* p, size_t n, int ms) {
    return static_cast<strata::worker::TlsSession*>(s)->send_all(p,n,ms,{});
}
bool bench_recv(void* s, unsigned char* p, size_t n, int ms) {
    return static_cast<strata::worker::TlsSession*>(s)->recv_all(p,n,ms,{});
}
void bench_free(void* s) { delete static_cast<strata::worker::TlsSession*>(s); }
// Apply Strata's exact SAN DNS policy to Quinn's already chain-verified certificate.
bool bench_san(const unsigned char* der, size_t n, const char* peer) {
    const unsigned char* p=der;
    X509* x=d2i_X509(nullptr,&p,n);
    bool ok=x && p==der+n && X509_check_host(x,peer,0,
        X509_CHECK_FLAG_NEVER_CHECK_SUBJECT|X509_CHECK_FLAG_NO_WILDCARDS,nullptr)==1;
    X509_free(x); return ok;
}
}
