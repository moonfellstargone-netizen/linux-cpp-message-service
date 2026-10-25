# Linux C++ 小型消息服务

[![Linux build and tests](https://github.com/moonfellstargone-netizen/linux-cpp-message-service/actions/workflows/linux.yml/badge.svg)](https://github.com/moonfellstargone-netizen/linux-cpp-message-service/actions/workflows/linux.yml)

一个基于 C++17 和 POSIX socket 的 TCP 演示项目。客户端发送消息，服务端返回消息的字节数和原文，支持多个客户端分别请求、接收回复。

- 单线程非阻塞 `poll`，每条连接保存自己的收发缓冲和发送进度。
- 4 字节大端长度前缀，处理不完整消息、连续多帧和非法长度。
- RAII 管理描述符，处理断连、半关闭和收发错误，设置连接与缓冲上限。

## 构建与测试

环境：Ubuntu、支持 C++17 的编译器、CMake 3.16+、Python 3.9+。无第三方运行库依赖。

```bash
git clone https://github.com/moonfellstargone-netizen/linux-cpp-message-service.git
cd linux-cpp-message-service
cmake -S . -B build -DCMAKE_BUILD_TYPE=Debug
cmake --build build
(cd build && ctest --output-on-failure)
```

没有 CMake 时可用 `bash scripts/build.sh` 编译，测试方法见 [测试说明](docs/testing.md)。

## 运行

终端一启动服务端：

```bash
./build/message_server 9000
```

在其他终端启动客户端：

```bash
./build/message_client 127.0.0.1 9000
```

输入 `hello`，回复内容为：

```text
bytes=5
hello
```

每行一条消息，`/quit` 退出。完整流程见 [多客户端演示](docs/demo.md)。

## 范围

仅监听 `127.0.0.1`，请求正文 1–1024 字节，最多 64 条连接。当前提供在线请求回复，不含身份认证、客户端间转发和消息持久化。

Ubuntu CI 覆盖 Debug、Release 和 ASan/UBSan 构建，包含协议测试、21 项集成测试及 4 项测量工具检查。[查看报告](reports/README.md)

## 文档

- [协议与连接处理](docs/protocol.md)
- [构建与测试](docs/testing.md)
- [演示步骤](docs/demo.md)
- [排障记录](docs/debugging.md)
- [本机测量](docs/measurement.md)
