#include "msg/protocol.hpp"
#include "msg/unique_fd.hpp"

#include <arpa/inet.h>
#include <sys/socket.h>
#include <unistd.h>

#include <cerrno>
#include <charconv>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>

namespace {

std::runtime_error system_error(const char* operation) {
    return std::runtime_error(std::string(operation) + ": " + std::strerror(errno));
}

void flush_stdout() {
    // A successful socket response does not imply stdout accepted its bytes.
    // Flush first so buffered write errors are observed before reporting success.
    std::cout.flush();
    if (!std::cout) {
        throw std::runtime_error("stdout write failed");
    }
}

unsigned short parse_port(std::string_view text) {
    unsigned int port = 0;
    const auto result = std::from_chars(text.data(), text.data() + text.size(), port);
    if (result.ec != std::errc{} || result.ptr != text.data() + text.size() ||
        port == 0 || port > 65535) {
        throw std::invalid_argument("port must be an integer in 1..65535");
    }
    return static_cast<unsigned short>(port);
}

enum class LineStatus { Complete, EndOfInput, TooLong };

LineStatus read_bounded_line(std::istream& input, std::string& line) {
    line.clear();
    bool too_long = false;
    char character;
    while (input.get(character)) {
        if (character == '\n') {
            return too_long ? LineStatus::TooLong : LineStatus::Complete;
        }
        if (line.size() < msg::kMaxRequestBody) {
            line.push_back(character);
        } else {
            // Discard the rest of this line rather than treating it as another
            // request or retaining an arbitrarily large amount of input.
            too_long = true;
        }
    }
    if (input.bad() || !input.eof()) {
        throw std::runtime_error("stdin read failed");
    }
    if (too_long) {
        return LineStatus::TooLong;
    }
    // EOF can terminate a valid final line without a trailing newline.
    return line.empty() ? LineStatus::EndOfInput : LineStatus::Complete;
}

void send_all(int fd, std::string_view bytes) {
    std::size_t offset = 0;
    while (offset < bytes.size()) {
        const auto sent = ::send(fd, bytes.data() + offset, bytes.size() - offset,
                                 MSG_NOSIGNAL);
        if (sent > 0) {
            offset += static_cast<std::size_t>(sent);
        } else if (sent < 0 && errno == EINTR) {
            continue;
        } else if (sent < 0) {
            throw system_error("send");
        } else {
            throw std::runtime_error("send made no progress");
        }
    }
}

void receive_exactly(int fd, char* output, std::size_t length) {
    std::size_t offset = 0;
    while (offset < length) {
        const auto received = ::recv(fd, output + offset, length - offset, 0);
        if (received > 0) {
            offset += static_cast<std::size_t>(received);
        } else if (received == 0) {
            throw std::runtime_error("server closed before the response was complete");
        } else if (errno == EINTR) {
            continue;
        } else {
            throw system_error("recv");
        }
    }
}

std::string receive_response(int fd) {
    char header[msg::kHeaderSize];
    receive_exactly(fd, header, sizeof(header));
    const auto size = msg::decode_length(header);
    if (size == 0 || size > msg::kMaxResponseBody) {
        throw std::runtime_error("server returned an invalid response length");
    }
    std::string body(size, '\0');
    receive_exactly(fd, body.data(), body.size());
    return body;
}

}  // namespace

int main(int argc, char* argv[]) {
    try {
        if (argc > 3 || (argc == 2 && std::string_view(argv[1]) == "--help")) {
            std::cout << "Usage: message_client [IPv4-address] [port]\n"
                         "Send one nonempty line (1..1024 bytes) per request; /quit exits.\n";
            flush_stdout();
            return argc > 3 ? 1 : 0;
        }
        const std::string host = argc >= 2 ? argv[1] : "127.0.0.1";
        const auto port = argc == 3 ? parse_port(argv[2]) : 9000;
        sockaddr_in address{};
        address.sin_family = AF_INET;
        address.sin_port = htons(static_cast<unsigned short>(port));
        if (::inet_pton(AF_INET, host.c_str(), &address.sin_addr) != 1) {
            throw std::invalid_argument("host must be a numeric IPv4 address");
        }
        msg::UniqueFd socket(::socket(AF_INET, SOCK_STREAM, 0));
        if (!socket) {
            throw system_error("socket");
        }
        if (::connect(socket.get(), reinterpret_cast<sockaddr*>(&address),
                      sizeof(address)) < 0) {
            throw system_error("connect");
        }
        const bool interactive = ::isatty(STDIN_FILENO) != 0;
        if (interactive) {
            std::cout << "Connected to " << host << ':' << port << ". /quit to exit.\n";
            flush_stdout();
        }
        std::string line;
        while (true) {
            if (interactive) {
                std::cout << "> ";
                flush_stdout();
            }
            const auto status = read_bounded_line(std::cin, line);
            // With the default stdio synchronization, a failed fgetc() can
            // look like EOF to iostreams. Preserve the underlying read error.
            if (std::ferror(stdin) != 0) {
                throw std::runtime_error("stdin read failed");
            }
            if (status == LineStatus::EndOfInput ||
                (status == LineStatus::Complete && line == "/quit")) {
                break;
            }
            if (status == LineStatus::TooLong || line.empty()) {
                std::cerr << "Input must contain 1.." << msg::kMaxRequestBody
                          << " bytes; nothing was sent.\n";
                continue;
            }
            send_all(socket.get(), msg::frame(line));
            const auto response = receive_response(socket.get());
            if (response != msg::make_response(line)) {
                throw std::runtime_error("server response does not match this request");
            }
            std::cout.write(response.data(), static_cast<std::streamsize>(response.size()));
            std::cout << '\n';
            flush_stdout();
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "message_client: " << error.what() << '\n';
        return 1;
    }
}
