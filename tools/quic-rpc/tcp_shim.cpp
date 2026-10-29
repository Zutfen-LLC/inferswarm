// Only ABI glue. The TCP TLS handshake and full-I/O loops are unchanged Strata code.
#include "strata/worker/tls.hpp"
#include <openssl/x509v3.h>
#include <openssl/err.h>
#include <openssl/sslerr.h>
#include <new>
#include <cerrno>
#ifdef __linux__
#include <sys/socket.h>
#include <netinet/in.h>
#include <linux/tcp.h>
#endif
namespace { thread_local int last_verify_failure = 0; }
extern "C" {
// Read-only diagnostic on the caller-owned descriptor. Raw ABI bytes avoid
// silently treating fields absent from an older kernel's tcp_info as zeros.
int bench_tcp_info(int fd, unsigned char* data, size_t capacity, size_t* length) {
    *length = 0;
#ifdef __linux__
    socklen_t n = static_cast<socklen_t>(capacity);
    if (static_cast<size_t>(n) != capacity) return EINVAL;
    if (getsockopt(fd, IPPROTO_TCP, TCP_INFO, data, &n) != 0) return errno;
    *length = n;
    return 0;
#else
    (void)fd; (void)data; (void)capacity;
    return ENOTSUP;
#endif
}
int bench_tls_verify_failure() { return last_verify_failure; }
bool bench_validate(const char* ca,const char* cert,const char* key,const char* peer) {
    strata::worker::TlsConfig c{ca,cert,key,peer};std::string err;return c.validate(err);
}
void* bench_tls(int fd, const char* ca, const char* cert, const char* key,
                const char* peer, bool server, int ms) {
    last_verify_failure = 0;
    auto* s = new(std::nothrow) strata::worker::TlsSession;
    if (!s) return nullptr;
    strata::worker::TlsConfig c{ca, cert, key, peer};
    std::string err;
    if (!s->handshake(fd, c, server, ms, {}, err)) {
        // Diagnostic only. Remote alerts/timeouts are not local verification proof.
        for (unsigned long code; (code = ERR_get_error()) != 0;) {
            if (ERR_GET_LIB(code) != ERR_LIB_SSL) continue;
            const int reason = ERR_GET_REASON(code);
            if (reason == SSL_R_CERTIFICATE_VERIFY_FAILED) last_verify_failure = 1;
            if (reason == SSL_R_PEER_DID_NOT_RETURN_A_CERTIFICATE) last_verify_failure = 2;
        }
        delete s; return nullptr;
    }
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
