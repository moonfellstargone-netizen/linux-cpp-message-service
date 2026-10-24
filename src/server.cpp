#include "msg/protocol.hpp"
#include "msg/unique_fd.hpp"

#include <arpa/inet.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <poll.h>
#include <signal.h>
#include <sys/socket.h>

#include <algorithm>
#include <cerrno>
#include <charconv>
#include <cstdint>
#include <cstring>
#include <deque>
#include <iostream>
#include <stdexcept>
#include <string>
#include <system_error>
#include <utility>
#include <vector>

namespace {

volatile sig_atomic_t stop_requested = 0;
constexpr std::size_t kReadBudget = 16 * 1024;
constexpr std::size_t kWriteBudget = 64 * 1024;
constexpr std::size_t kAcceptBudget = 16;
constexpr int kPollWaitMilliseconds = 250;

void request_stop(int) { stop_requested = 1; }

std::string system_error(const char* operation) {
    const int saved_errno = errno;
    return std::string(operation) + " errno=" + std::to_string(saved_errno) +
           " detail=" + std::strerror(saved_errno);
}

void log_connection(const char* event, std::uint64_t id,
                    const std::string& reason) {
    std::cerr << "event=" << event << " connection=" << id
              << " reason=" << reason << '\n';
}

// Both listening and accepted sockets must be nonblocking. CLOEXEC also keeps
// descriptors private if a future diagnostic command launches another process.
bool configure_socket(int fd) {
    for (const auto& commands : {std::pair{F_GETFL, F_SETFL},
                                 std::pair{F_GETFD, F_SETFD}}) {
        int flags;
        do {
            flags = ::fcntl(fd, commands.first);
        } while (flags < 0 && errno == EINTR);
        if (flags < 0) {
            return false;
        }
        const int addition = commands.first == F_GETFL ? O_NONBLOCK : FD_CLOEXEC;
        int result;
        do {
            result = ::fcntl(fd, commands.second, flags | addition);
        } while (result < 0 && errno == EINTR);
        if (result < 0) {
            return false;
        }
    }
    return true;
}

struct Connection {
    msg::UniqueFd fd;
    std::uint64_t id;
    std::string input;
    std::deque<std::string> output;
    std::size_t output_offset = 0;
    std::size_t pending_bytes = 0;
    bool read_eof = false;

    Connection(msg::UniqueFd socket, std::uint64_t number)
        : fd(std::move(socket)), id(number) {}
};

void close_connection(Connection& connection, const std::string& reason) {
    log_connection("closed", connection.id, reason);
    connection.fd.reset();
}

bool prepare_replies(Connection& connection, std::string& reason) {
    std::string body;
    while (true) {
        const auto status = msg::parse_frame(connection.input, body);
        if (status == msg::ParseStatus::NeedMore) {
            return true;
        }
        if (status == msg::ParseStatus::InvalidLength) {
            reason = "invalid_length";
            return false;
        }
        auto reply = msg::frame(msg::make_response(body));
        if (reply.size() > msg::kMaxPendingBytes - connection.pending_bytes) {
            reason = "pending_limit";
            return false;
        }
        connection.pending_bytes += reply.size();
        connection.output.push_back(std::move(reply));
    }
}

bool receive_messages(Connection& connection, std::string& reason) {
    std::size_t budget = kReadBudget;
    char buffer[4096];
    while (budget > 0 && !stop_requested) {
        const auto room = msg::kMaxReceiveBytes - connection.input.size();
        if (room == 0) {
            reason = "receive_limit";
            return false;
        }
        const auto capacity = std::min({sizeof(buffer), budget, room});
        const auto received = ::recv(connection.fd.get(), buffer, capacity, 0);
        if (received > 0) {
            const auto count = static_cast<std::size_t>(received);
            budget -= count;
            connection.input.append(buffer, count);
            if (!prepare_replies(connection, reason)) {
                return false;
            }
        } else if (received == 0) {
            connection.read_eof = true;
            if (!connection.input.empty()) {
                reason = "truncated_frame";
                return false;
            }
            return true;
        } else if (errno == EINTR) {
            continue;
        } else if (errno == EAGAIN || errno == EWOULDBLOCK) {
            return true;
        } else {
            reason = system_error("recv_failed");
            return false;
        }
    }
    return true;
}

bool send_replies(Connection& connection, std::string& reason) {
    std::size_t budget = kWriteBudget;
    while (!connection.output.empty() && budget > 0 && !stop_requested) {
        const auto& reply = connection.output.front();
        const auto remaining = reply.size() - connection.output_offset;
        const auto sent = ::send(connection.fd.get(),
                                 reply.data() + connection.output_offset,
                                 std::min(remaining, budget), MSG_NOSIGNAL);
        if (sent > 0) {
            const auto count = static_cast<std::size_t>(sent);
            budget -= count;
            connection.pending_bytes -= count;
            connection.output_offset += count;
            if (connection.output_offset == reply.size()) {
                connection.output.pop_front();
                connection.output_offset = 0;
            }
        } else if (sent < 0 && errno == EINTR) {
            continue;
        } else if (sent < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
            return true;
        } else {
            reason = sent == 0 ? "send_returned_zero" : system_error("send_failed");
            return false;
        }
    }
    return true;
}

unsigned short parse_port(int argc, char** argv) {
    if (argc == 1) {
        return 9000;
    }
    if (argc != 2) {
        throw std::runtime_error("usage: server [port: 0..65535]");
    }
    const std::string text = argv[1];
    unsigned int port = 0;
    const auto result = std::from_chars(text.data(), text.data() + text.size(), port);
    if (result.ec != std::errc{} || result.ptr != text.data() + text.size() ||
        text.empty() || port > 65535) {
        throw std::runtime_error("invalid_port expected=0..65535");
    }
    return static_cast<unsigned short>(port);
}

void install_signal_handlers() {
    struct sigaction action {};
    action.sa_handler = request_stop;
    ::sigemptyset(&action.sa_mask);
    if (::sigaction(SIGINT, &action, nullptr) < 0 ||
        ::sigaction(SIGTERM, &action, nullptr) < 0) {
        throw std::runtime_error(system_error("sigaction_failed"));
    }
}

int run(unsigned short port) {
    msg::UniqueFd listener(::socket(AF_INET, SOCK_STREAM, 0));
    if (!listener) {
        throw std::runtime_error(system_error("socket_failed"));
    }
    if (!configure_socket(listener.get())) {
        throw std::runtime_error(system_error("configure_listener_failed"));
    }
    const int reuse = 1;
    if (::setsockopt(listener.get(), SOL_SOCKET, SO_REUSEADDR, &reuse,
                     sizeof(reuse)) < 0) {
        throw std::runtime_error(system_error("setsockopt_failed"));
    }
    sockaddr_in address {};
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    address.sin_port = htons(port);
    if (::bind(listener.get(), reinterpret_cast<sockaddr*>(&address),
               sizeof(address)) < 0) {
        throw std::runtime_error(system_error("bind_failed"));
    }
    if (::listen(listener.get(), static_cast<int>(msg::kMaxConnections)) < 0) {
        throw std::runtime_error(system_error("listen_failed"));
    }
    socklen_t address_size = sizeof(address);
    if (::getsockname(listener.get(), reinterpret_cast<sockaddr*>(&address),
                      &address_size) < 0) {
        throw std::runtime_error(system_error("getsockname_failed"));
    }
    std::cout << "event=listening port=" << ntohs(address.sin_port)
              << " address=127.0.0.1" << std::endl;

    std::vector<Connection> connections;
    connections.reserve(msg::kMaxConnections);
    std::uint64_t next_id = 1;
    while (!stop_requested) {
        std::vector<pollfd> watched {{listener.get(), POLLIN, 0}};
        for (const auto& connection : connections) {
            short events = connection.read_eof ? 0 : POLLIN;
            if (!connection.output.empty()) {
                events |= POLLOUT;
            }
            watched.push_back({connection.fd.get(), events, 0});
        }
        const auto existing_count = connections.size();
        // A short wait also covers a termination signal arriving between the
        // loop condition and poll(). This is not a per-connection timeout.
        const int ready = ::poll(watched.data(), watched.size(), kPollWaitMilliseconds);
        if (ready < 0) {
            if (errno == EINTR) {
                continue;
            }
            throw std::runtime_error(system_error("poll_failed"));
        }
        if (stop_requested) {
            break;
        }
        if (watched.front().revents & (POLLERR | POLLHUP | POLLNVAL)) {
            throw std::runtime_error("listener_poll_error");
        }
        if (watched.front().revents & POLLIN) {
            for (std::size_t attempt = 0; attempt < kAcceptBudget && !stop_requested;
                 ++attempt) {
                msg::UniqueFd accepted(::accept(listener.get(), nullptr, nullptr));
                if (!accepted) {
                    if (errno == EINTR) {
                        continue;
                    }
                    if (errno == EAGAIN || errno == EWOULDBLOCK) {
                        break;
                    }
                    // A persistent descriptor/resource failure must not spin on
                    // a readable listening socket. Exit with a clear error.
                    if (errno == EMFILE || errno == ENFILE || errno == ENOMEM ||
                        errno == ENOBUFS) {
                        throw std::runtime_error(system_error("accept_failed"));
                    }
                    log_connection("accept_error", 0, system_error("accept_failed"));
                    break;
                }
                const auto id = next_id++;
                if (connections.size() >= msg::kMaxConnections) {
                    log_connection("rejected", id, "connection_limit");
                } else if (!configure_socket(accepted.get())) {
                    log_connection("rejected", id, system_error("configure_failed"));
                } else {
                    connections.emplace_back(std::move(accepted), id);
                    log_connection("accepted", id, "connected");
                }
            }
        }
        // New clients are included in the next poll snapshot. Closing an old
        // client does not invalidate the remaining snapshot indices.
        for (std::size_t i = 0; i < existing_count && !stop_requested; ++i) {
            auto& connection = connections[i];
            const short events = watched[i + 1].revents;
            if (events == 0) {
                continue;
            }
            if (events & POLLNVAL) {
                close_connection(connection, "invalid_descriptor");
                continue;
            }
            if (events & POLLERR) {
                int socket_error = 0;
                socklen_t size = sizeof(socket_error);
                std::string reason = "socket_error";
                if (::getsockopt(connection.fd.get(), SOL_SOCKET, SO_ERROR,
                                 &socket_error, &size) == 0) {
                    reason += " errno=" + std::to_string(socket_error) +
                              " detail=" + std::strerror(socket_error);
                }
                close_connection(connection, reason);
                continue;
            }
            std::string reason;
            // HUP may arrive alongside readable bytes: receive those bytes and
            // observe EOF instead of dropping them before parsing.
            if (!connection.read_eof && (events & (POLLIN | POLLHUP)) &&
                !receive_messages(connection, reason)) {
                close_connection(connection, reason);
                continue;
            }
            // Replies created during this read can be sent immediately; send()
            // remains nonblocking even without an earlier POLLOUT event.
            if (!connection.output.empty() && !send_replies(connection, reason)) {
                close_connection(connection, reason);
                continue;
            }
            if (connection.read_eof && connection.output.empty()) {
                close_connection(connection, "peer_eof");
            } else if (connection.read_eof && (events & POLLHUP)) {
                // A fully closed peer cannot consume queued replies. Avoid
                // repeatedly polling HUP if its socket also refuses writes.
                close_connection(connection, "hangup_with_pending_output");
            }
        }
        connections.erase(
            std::remove_if(connections.begin(), connections.end(),
                           [](const Connection& connection) { return !connection.fd; }),
            connections.end());
    }
    for (auto& connection : connections) {
        close_connection(connection, "server_shutdown");
    }
    std::cerr << "event=stopped reason=signal\n";
    return 0;
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const auto port = parse_port(argc, argv);
        install_signal_handlers();
        return run(port);
    } catch (const std::exception& error) {
        std::cerr << "event=fatal reason=" << error.what() << '\n';
        return 1;
    }
}
