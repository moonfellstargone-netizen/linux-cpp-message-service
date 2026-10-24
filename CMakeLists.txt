cmake_minimum_required(VERSION 3.16)
project(linux_cpp_message_service VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_EXTENSIONS OFF)
option(MSG_ENABLE_SANITIZERS "Enable AddressSanitizer and UndefinedBehaviorSanitizer" OFF)

add_library(message_options INTERFACE)
target_include_directories(message_options INTERFACE "${CMAKE_CURRENT_SOURCE_DIR}/include")
target_compile_features(message_options INTERFACE cxx_std_17)
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(message_options INTERFACE -Wall -Wextra -Wpedantic)
    if(MSG_ENABLE_SANITIZERS)
        target_compile_options(message_options INTERFACE -fsanitize=address,undefined
                               -fno-sanitize-recover=undefined -fno-omit-frame-pointer -g)
        target_link_options(message_options INTERFACE -fsanitize=address,undefined)
    endif()
endif()

include(CTest)
if(BUILD_TESTING)
    add_executable(protocol_tests tests/protocol_test.cpp)
    target_link_libraries(protocol_tests PRIVATE message_options)
    add_test(NAME protocol COMMAND protocol_tests)
endif()

if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    add_executable(message_server src/server.cpp)
    add_executable(message_client src/client.cpp)
    target_link_libraries(message_server PRIVATE message_options)
    target_link_libraries(message_client PRIVATE message_options)
    if(BUILD_TESTING)
        find_package(Python3 3.9 REQUIRED COMPONENTS Interpreter)
        add_test(NAME integration COMMAND "${Python3_EXECUTABLE}"
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/integration_test.py"
            --server $<TARGET_FILE:message_server>
            --client $<TARGET_FILE:message_client>
            --report "${CMAKE_CURRENT_BINARY_DIR}/test-results/integration.json")
        set_tests_properties(integration PROPERTIES TIMEOUT 180)
        add_test(NAME load_probe_checks COMMAND "${Python3_EXECUTABLE}"
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/load_probe_test.py"
            --server $<TARGET_FILE:message_server>)
        set_tests_properties(load_probe_checks PROPERTIES TIMEOUT 60)
    endif()
else()
    message(STATUS "Only the portable protocol tests are built here. Server and client require Linux.")
endif()
