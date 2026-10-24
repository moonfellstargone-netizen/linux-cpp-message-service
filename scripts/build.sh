#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
build_dir="${project_dir}/build"
compiler="${CXX:-g++}"
mkdir -p -- "${build_dir}"
flags=(-std=c++17 -Wall -Wextra -Wpedantic -g -I "${project_dir}/include")
"${compiler}" "${flags[@]}" "${project_dir}/src/server.cpp" -o "${build_dir}/message_server"
"${compiler}" "${flags[@]}" "${project_dir}/src/client.cpp" -o "${build_dir}/message_client"
"${compiler}" "${flags[@]}" "${project_dir}/tests/protocol_test.cpp" -o "${build_dir}/protocol_tests"
printf 'Built server, client and protocol_tests in %s\n' "${build_dir}"
