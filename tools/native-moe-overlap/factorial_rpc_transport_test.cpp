// Standalone runner for the exact production poll engine (no native archive).
#include "factorial-rpc-io.h"
#include <arpa/inet.h>
#include <netinet/tcp.h>
#include <cstdlib>
#include <iostream>
#include <vector>

int main(int argc, char ** argv) {
    if (argc != 8) return 2;
    int fd = ::socket(AF_INET, SOCK_STREAM, 0);
    int tiny = 1024;
    int one = 1;
    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
    setsockopt(fd, SOL_SOCKET, SO_SNDBUF, &tiny, sizeof(tiny));
    setsockopt(fd, SOL_SOCKET, SO_RCVBUF, &tiny, sizeof(tiny));
    sockaddr_in address{};
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    address.sin_port = htons((uint16_t)std::atoi(argv[1]));
    if (connect(fd, (sockaddr *)&address, sizeof(address))) return 3;
    const bool pipeline = std::atoi(argv[2]);
    const uint64_t deadline = is_factorial_io::now_ns() + uint64_t(std::atoi(argv[3])) * 1000000;
    const size_t size = (size_t)std::atoi(argv[4]);
    std::vector<uint8_t> data[3];
    uint8_t headers[3][40] = {}, accepted[3] = {};
    is_factorial_io::frame frames[3] = {};
    for (int i = 0; i < 3; ++i) {
        uint64_t id = (uint64_t)i;
        std::memcpy(headers[i], &id, sizeof(id));
        for (int j = 0; j < 32; ++j) {
            char hex[3] = {argv[5+i][j*2], argv[5+i][j*2+1], 0};
            headers[i][8+j] = (uint8_t)std::strtol(hex, nullptr, 16);
        }
        data[i].resize(size);
        for (size_t j = 0; j < size; ++j) data[i][j] = (uint8_t)(i*29+j);
        frames[i] = {6, headers[i], sizeof(headers[i]), data[i].data(), size,
            true, &accepted[i], 1, true, {}};
    }
    const auto status = is_factorial_io::exchange(fd, frames, 3, pipeline, deadline);
    bool graph_sent = false;
    if (status == is_factorial_io::error::none) {
        is_factorial_io::frame graph{16, nullptr, 0, nullptr, 0, false, nullptr, 0, false, {}};
        graph_sent = is_factorial_io::exchange(fd, &graph, 1, false,
            is_factorial_io::now_ns() + 1000000000) == is_factorial_io::error::none;
    }
    std::cout << "{\"status\":\"" << is_factorial_io::name(status) << "\",\"graph_sent\":" << graph_sent << ",\"frames\":[";
    for (int i = 0; i < 3; ++i) {
        const auto & t = frames[i].timing;
        if (i) std::cout << ',';
        std::cout << "{\"begin\":" << t.write_begin_ns << ",\"end\":" << t.write_end_ns
            << ",\"first\":" << t.reply_first_ns << ",\"ack\":" << t.reply_end_ns
            << ",\"tx\":" << t.sent_bytes << ",\"rx\":" << t.received_bytes << '}';
    }
    std::cout << "]}" << std::endl;
    ::close(fd);
    return 0;
}
