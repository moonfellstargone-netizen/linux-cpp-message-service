#include "msg/protocol.hpp"

#include <cstdint>
#include <exception>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>

namespace {

void check(bool condition, std::string_view description) {
    if (!condition) {
        throw std::runtime_error(std::string(description));
    }
}

void test_all_split_positions() {
    const std::string request("A\0B\x80\xff", 5);
    const auto encoded = msg::frame(request);
    for (std::size_t split = 0; split < encoded.size(); ++split) {
        auto pending = encoded.substr(0, split);
        const auto before = pending;
        std::string body = "unchanged";
        check(msg::parse_frame(pending, body) == msg::ParseStatus::NeedMore,
              "incomplete frame must need more bytes");
        check(pending == before, "NeedMore must preserve pending bytes");
        check(body == "unchanged", "NeedMore must preserve output body");
        pending.append(encoded.substr(split));
        check(msg::parse_frame(pending, body) == msg::ParseStatus::Complete,
              "completed split frame must parse");
        check(body == request && pending.empty(), "binary frame must round-trip");
    }
}

void test_multiple_frames_and_trailing_partial() {
    const auto partial = msg::frame("third").substr(0, 6);
    auto pending = msg::frame("first") + msg::frame("second") + partial;
    std::string body;
    check(msg::parse_frame(pending, body) == msg::ParseStatus::Complete && body == "first",
          "first coalesced frame must parse");
    check(msg::parse_frame(pending, body) == msg::ParseStatus::Complete && body == "second",
          "second coalesced frame must parse");
    check(pending == partial, "complete parse must retain subsequent partial frame");
    check(msg::parse_frame(pending, body) == msg::ParseStatus::NeedMore && pending == partial,
          "trailing incomplete frame must remain intact");
}

void test_invalid_lengths() {
    const std::string headers[] = {
        std::string("\0\0\0\0", 4),
        std::string("\0\0\x04\x01", 4),
        std::string("\xff\xff\xff\xff", 4),
    };
    for (const auto& header : headers) {
        auto pending = header;
        std::string body = "unchanged";
        check(msg::parse_frame(pending, body) == msg::ParseStatus::InvalidLength,
              "invalid length must be rejected using header alone");
        check(pending == header && body == "unchanged", "invalid input must not be consumed");
    }
}

void test_boundaries_and_big_endian() {
    const std::string high_bytes("\x80\x01\xfe\xff", 4);
    check(msg::decode_length(high_bytes.data()) == std::uint32_t{0x8001feffU},
          "decode must use unsigned bytes in network order");
    const std::string maximum(msg::kMaxRequestBody, 'm');
    auto pending = msg::frame(maximum);
    check(pending.substr(0, 4) == std::string("\0\0\x04\0", 4),
          "1024 must encode as big-endian 00 00 04 00");
    std::string body;
    check(msg::parse_frame(pending, body) == msg::ParseStatus::Complete && body == maximum,
          "maximum request length must parse");
    pending = msg::frame("x");
    check(msg::parse_frame(pending, body) == msg::ParseStatus::Complete && body == "x",
          "minimum request length must parse");
    bool threw = false;
    try {
        static_cast<void>(msg::frame(""));
    } catch (const std::invalid_argument&) {
        threw = true;
    }
    check(threw, "frame must reject empty bodies");
}

void test_response_bytes_and_limit() {
    const std::string utf8("\xe4\xbd\xa0\xe5\xa5\xbd", 6);
    check(msg::make_response(utf8) == "bytes=6\n" + utf8,
          "UTF-8 response must count bytes");
    const std::string binary("a\0b", 3);
    check(msg::make_response(binary) == std::string("bytes=3\na\0b", 11),
          "response must preserve embedded NUL");
    const auto response = msg::make_response(std::string(msg::kMaxRequestBody, 'x'));
    check(response.size() <= msg::kMaxResponseBody, "maximum response must fit response limit");
    auto pending = msg::frame(response);
    std::string body;
    check(msg::parse_frame(pending, body) == msg::ParseStatus::InvalidLength,
          "request parser must reject an oversized response body");
    check(msg::parse_frame(pending, body, msg::kMaxResponseBody) == msg::ParseStatus::Complete &&
              body == response,
          "response parser must accept its separate maximum");
}

}  // namespace

int main() {
    try {
        test_all_split_positions();
        test_multiple_frames_and_trailing_partial();
        test_invalid_lengths();
        test_boundaries_and_big_endian();
        test_response_bytes_and_limit();
        std::cout << "Protocol checks passed (active in Debug and Release).\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "Protocol check failed: " << error.what() << '\n';
        return 1;
    }
}
