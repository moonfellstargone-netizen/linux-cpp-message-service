#pragma once

#include <cstddef>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>

namespace msg {

inline constexpr std::size_t kHeaderSize = 4;
inline constexpr std::uint32_t kMaxRequestBody = 1024;
inline constexpr std::uint32_t kMaxResponseBody = kMaxRequestBody + 32;
inline constexpr std::size_t kMaxConnections = 64;
inline constexpr std::size_t kMaxReceiveBytes = 8 * 1024;
inline constexpr std::size_t kMaxPendingBytes = 64 * 1024;

// The wire header contains the body length in network byte order, not a C++ struct.
inline std::uint32_t decode_length(const char* header) {
    const auto* p = reinterpret_cast<const unsigned char*>(header);
    return (std::uint32_t{p[0]} << 24) | (std::uint32_t{p[1]} << 16) |
           (std::uint32_t{p[2]} << 8) | std::uint32_t{p[3]};
}

inline std::string frame(std::string_view body) {
    if (body.empty() || body.size() > std::numeric_limits<std::uint32_t>::max()) {
        throw std::invalid_argument("frame body length is out of range");
    }
    const auto size = static_cast<std::uint32_t>(body.size());
    std::string output(kHeaderSize, '\0');
    for (std::size_t i = 0; i < kHeaderSize; ++i) {
        output[i] = static_cast<char>((size >> (24 - 8 * i)) & 0xffU);
    }
    output.append(body.data(), body.size());
    return output;
}

enum class ParseStatus { Complete, NeedMore, InvalidLength };

// NeedMore preserves the input; Complete consumes exactly one frame.
inline ParseStatus parse_frame(std::string& input, std::string& body,
                               std::uint32_t maximum = kMaxRequestBody) {
    if (input.size() < kHeaderSize) {
        return ParseStatus::NeedMore;
    }
    const auto length = decode_length(input.data());
    if (length == 0 || length > maximum) {
        return ParseStatus::InvalidLength;
    }
    const auto frame_size = kHeaderSize + static_cast<std::size_t>(length);
    if (input.size() < frame_size) {
        return ParseStatus::NeedMore;
    }
    body.assign(input.data() + kHeaderSize, length);
    input.erase(0, frame_size);
    return ParseStatus::Complete;
}

// Count bytes rather than characters. Embedded NUL and UTF-8 bytes are preserved.
inline std::string make_response(std::string_view request) {
    std::string response = "bytes=" + std::to_string(request.size()) + "\n";
    response.append(request.data(), request.size());
    return response;
}

}  // namespace msg
