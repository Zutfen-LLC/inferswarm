#pragma once
// Linux/TCP-only bounded wire engine shared verbatim by production and proofs.
// One dispatcher queue item owns fd. There is one poll loop, one writer and one
// reader; no concurrent socket_t buffering and no change to fd blocking flags.
#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

namespace is_factorial_io {
inline uint64_t now_ns() {
    return (uint64_t) std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}
struct trace {
    uint64_t write_begin_ns = 0, write_end_ns = 0;
    uint64_t reply_first_ns = 0, reply_end_ns = 0;
    uint64_t sent_bytes = 0, received_bytes = 0;
};
struct frame {
    uint8_t command;
    const void * header;
    size_t header_size;
    const void * payload;
    size_t payload_size;
    bool reply;
    void * output;
    size_t output_size;
    bool admission;
    trace timing;
};
enum class error { none, deadline, poll_failed, write_failed, read_failed, eof,
                   malformed, refused, invalid };
inline const char * name(error e) {
    switch (e) {
        case error::none: return "none";
        case error::deadline: return "deadline";
        case error::poll_failed: return "poll";
        case error::write_failed: return "write";
        case error::read_failed: return "read";
        case error::eof: return "eof";
        case error::malformed: return "malformed response";
        case error::refused: return "admission refused";
        default: return "invalid arguments";
    }
}
// Every frame is |u8 cmd|u64 size|header|payload|; reply is |u64 size|data|.
// A serial window permits frame N+1 only after ACK N; pipeline permits it while
// ACKs are drained in order. Both directions use MSG_DONTWAIT, so a peer blocked
// writing a reply can always be drained even when our send buffers are full.
// Failure poisons the whole connection via shutdown (ownership closes it later).
inline error exchange(int fd, frame * frames, size_t count, bool pipeline, uint64_t deadline_ns) {
    auto fail = [fd](error e) { if (fd >= 0) ::shutdown(fd, SHUT_RDWR); return e; };
    if (fd < 0 || !frames || count == 0 || count > 3) return fail(error::invalid);
    uint64_t lengths[3] = {};
    for (size_t i = 0; i < count; ++i) {
        auto & f = frames[i];
        if ((f.header_size && !f.header) || (f.payload_size && !f.payload) ||
            (f.reply && f.output_size && !f.output) ||
            (f.admission && (!f.reply || f.output_size != 1))) return fail(error::invalid);
        lengths[i] = f.header_size + f.payload_size;
    }
    size_t wi = 0, part = 0, written = 0, ri = 0, read = 0;
    uint64_t reply_length = 0;
    bool reading_length = true;
    while (wi < count || ri < count) {
        while (ri < wi && !frames[ri].reply) {
            ++ri; read = 0; reading_length = true;
        }
        if (wi == count && ri == count) return error::none;
        const uint64_t now = now_ns();
        if (now >= deadline_ns) return fail(error::deadline);
        const bool can_write = wi < count && (pipeline || wi <= ri);
        const bool can_read = ri < wi && frames[ri].reply;
        pollfd pfd{fd, (short)((can_write ? POLLOUT : 0) | (can_read ? POLLIN : 0)), 0};
        const int wait_ms = (int) std::min<uint64_t>((deadline_ns - now + 999999) / 1000000, 10000);
        const int ready = ::poll(&pfd, 1, wait_ms);
        if (ready < 0) { if (errno == EINTR) continue; return fail(error::poll_failed); }
        if (ready == 0) continue;
        // Drain before writing more. HUP can carry final bytes; let recv decide.
        if (can_read && (pfd.revents & (POLLIN | POLLHUP | POLLERR))) {
            frame & f = frames[ri];
            const size_t wanted = reading_length ? sizeof(reply_length) : f.output_size;
            void * destination = reading_length ? (void *)&reply_length : f.output;
            const ssize_t n = ::recv(fd, (char *)destination + read, wanted - read, MSG_DONTWAIT);
            if (n == 0) return fail(error::eof);
            if (n < 0) {
                if (errno != EINTR && errno != EAGAIN && errno != EWOULDBLOCK) return fail(error::read_failed);
            } else {
                if (!f.timing.reply_first_ns) f.timing.reply_first_ns = now_ns();
                f.timing.received_bytes += (uint64_t)n;
                read += (size_t)n;
                if (read == wanted) {
                    if (reading_length) {
                        if (reply_length != f.output_size) return fail(error::malformed);
                        reading_length = false; read = 0;
                    }
                    if (!reading_length && read == f.output_size) {
                        f.timing.reply_end_ns = now_ns();
                        if (f.admission && *(const uint8_t *)f.output != 1) return fail(error::refused);
                        ++ri; read = 0; reading_length = true; reply_length = 0;
                    }
                }
            }
        }
        if (can_write && (pfd.revents & POLLOUT)) {
            frame & f = frames[wi];
            const void * pointers[] = { &f.command, &lengths[wi], f.header, f.payload };
            const size_t sizes[] = { 1, sizeof(uint64_t), f.header_size, f.payload_size };
            while (part < 4 && written == sizes[part]) { ++part; written = 0; }
            if (part == 4) { f.timing.write_end_ns = now_ns(); ++wi; part = written = 0; continue; }
            if (!f.timing.write_begin_ns) f.timing.write_begin_ns = now_ns();
            const ssize_t n = ::send(fd, (const char *)pointers[part] + written, sizes[part] - written,
                                     MSG_DONTWAIT | MSG_NOSIGNAL);
            if (n <= 0) {
                if (n == 0 || (errno != EINTR && errno != EAGAIN && errno != EWOULDBLOCK)) return fail(error::write_failed);
            } else {
                written += (size_t)n; f.timing.sent_bytes += (uint64_t)n;
                while (part < 4 && written == sizes[part]) { ++part; written = 0; }
                if (part == 4) { f.timing.write_end_ns = now_ns(); ++wi; part = written = 0; }
            }
        }
        if (pfd.revents & POLLNVAL) return fail(error::poll_failed);
        if ((pfd.revents & (POLLHUP | POLLERR)) && !can_read) return fail(error::eof);
    }
    return error::none;
}
} // namespace is_factorial_io
