# Linux C++ 小型消息处理服务

`linux-cpp-message-service` 是面向学习和工程验证的 Linux C++ TCP 项目：客户端发送一条请求，服务端返回请求的字节数及原始内容。多个客户端可以分别与服务端通信，**不提供客户端之间的消息转发**。

目标环境为 Ubuntu，使用 C++17、POSIX socket 和单线程非阻塞 `poll` 服务端；命令行客户端按请求、回复顺序同步交互。项目由 AI 辅助实现，用户独立阅读、修改和排障的理解验收尚待完成。它是按通用需求新建的个人项目，不是原单位项目或其成果。

## 当前状态

Linux 编译、自动测试、三终端演示及资源观察：**待执行**。这里的设计与测试步骤不是已通过的测试结果；实际记录见 [验证状态](docs/status.md) 和 [测试方法](docs/testing.md)。

本项目用于练习消息边界、部分收发、连接清理及可重复验证。它不提供安全身份认证、持久化、离线消息或可靠投递保证，也没有生产流量或高并发能力的性能结论。

## 快速开始

在现有 Ubuntu 环境中确认已有 C++17 编译器、CMake；自动集成测试另需 Python 3 标准库。暂不要求安装额外框架或测试库。

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Debug
cmake --build build
ctest --test-dir build --output-on-failure
```

单独运行真实连接测试并保存本地 JSON 报告：

```bash
python3 tests/integration_test.py --server ./build/message_server --client ./build/message_client --report build/test-results/integration.json
```

没有 CMake 时，可使用直接调用 `g++` 的备用构建入口：

```bash
bash scripts/build.sh
```

在一个终端启动服务端：

```bash
./build/message_server
```

在另一个终端启动客户端：

```bash
./build/message_client 127.0.0.1 9000
```

每行输入对应一条请求，空行或超过 1024 字节的行会在客户端本地被拒绝，`/quit` 退出客户端。服务端默认端口为 `9000`，也可执行 `./build/message_server 9001` 指定端口；始终只监听 `127.0.0.1`。客户端参数依次为 IPv4 地址和端口，默认连接 `127.0.0.1:9000`。

## 范围与限制

- 请求正文为 1–1024 字节，响应包含 `bytes=<字节数>`、一个换行和原始请求。正文可以是任意字节；命令行入口按行输入，不校验 UTF-8。
- 每连接独立保存接收和发送状态，解析不完整消息及连续多帧，非法长度导致该连接关闭。
- 最多 64 个连接，每连接接收缓冲上限 8192 字节、待发送缓冲上限 65536 字节。这些是保护性限制，不是测出的性能指标。
- 不提供账号、消息路由、超时、自动重连、应用层确认、数据库、音视频或多节点能力。仅监听本机，不用于公网部署。

## 阅读导航

- [协议与错误处理](docs/protocol.md)
- [测试方法与记录要求](docs/testing.md)
- [三终端演示及故障复现](docs/demo.md)
- [源码阅读与独立练习](docs/learning.md)
- [真实排障记录入口](docs/debugging.md)
- [已确认、待验证、暂不做与接续](docs/status.md)

源码入口为 [服务端](src/server.cpp)、[客户端](src/client.cpp)、[协议与限制](include/msg/protocol.hpp) 和 [描述符所有权](include/msg/unique_fd.hpp)；测试入口为 [协议测试](tests/protocol_test.cpp) 和 [连接测试](tests/integration_test.py)。

在本人完成独立修改、运行和解释之前，不将本项目表述为“已独立掌握 Linux 服务端开发”。是否用于简历及具体措辞，应依据后续可复现结果确定。
