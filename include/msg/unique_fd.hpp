#pragma once

#include <unistd.h>
#include <utility>

namespace msg {

class UniqueFd {
public:
    explicit UniqueFd(int fd = -1) noexcept : fd_(fd) {}
    ~UniqueFd() { reset(); }
    UniqueFd(const UniqueFd&) = delete;
    UniqueFd& operator=(const UniqueFd&) = delete;
    UniqueFd(UniqueFd&& other) noexcept : fd_(other.release()) {}
    UniqueFd& operator=(UniqueFd&& other) noexcept {
        if (this != &other) {
            reset(other.release());
        }
        return *this;
    }
    int get() const noexcept { return fd_; }
    explicit operator bool() const noexcept { return fd_ >= 0; }
    int release() noexcept { return std::exchange(fd_, -1); }
    void reset(int next = -1) noexcept {
        if (fd_ >= 0) {
            // Do not retry close() after EINTR: the descriptor may already be closed.
            ::close(fd_);
        }
        fd_ = next;
    }

private:
    int fd_;
};

}  // namespace msg
