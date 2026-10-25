# 测试方法

环境：Linux、C++17、CMake 3.16+、Python 3.9+；测试脚本仅使用标准库。资源与错误用例需要 `/proc`、`/dev/full` 和目录描述符。

提交 `dad9d3b` 在 Ubuntu 24.04 的 Debug、ASan/UBSan、Release 三种构建中通过协议测试、21 项集成测试及 4 项测量工具检查，无失败或跳过。来源：[CI 40160429026](https://github.com/moonfellstargone-netizen/linux-cpp-message-service/actions/runs/40160429026)。

## 构建与运行

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Debug
cmake --build build
(cd build && ctest --output-on-failure)
```

单独运行集成测试和测量工具检查：

```bash
python3 tests/integration_test.py --server ./build/message_server --client ./build/message_client --report build/test-results/integration.json
python3 tests/load_probe_test.py --server ./build/message_server
```

脚本自动选择本地端口并启动、停止服务端，无需提前启动进程。集成测试的 `--report` 可省略；完整客户端验证需要传入 `--client`。

启用 ASan/UBSan：

```bash
cmake -S . -B build-asan -DCMAKE_BUILD_TYPE=Debug -DMSG_ENABLE_SANITIZERS=ON
cmake --build build-asan
(cd build-asan && ctest --output-on-failure)
```

GNU/Clang 配置使用 `-fno-sanitize-recover=undefined`，使 UBSan 检测错误时失败退出。

## 测试范围

- 协议测试：大端长度、所有分割位置、连续帧、非法长度、NUL 与 UTF-8 字节保留。
- 21 项集成测试：多客户端、1/1024 字节边界、拆头拆体、连续帧，以及仅发送 0/1025/4294967295 长度头时的拒绝。
- 连接与资源：残帧 EOF/reset、完整帧半关闭、错误隔离、50 次顺序连接后 FD 回收、64 条连接上限及慢接收端保护。
- CLI：2 MiB 超长行恢复、1024/1025 字节与 UTF-8 边界、空行、`/quit`、EOF 尾行、stdin 读取错误。
- 输出错误：服务端日志管道关闭后仍可服务；客户端回复与 `--help` 写入 `/dev/full` 时返回 1。后两者是同一集成用例的两个子场景。
- 4 项测量工具检查：短时真实请求的报告自洽、10 组非法参数、服务端文件缺失及启动失败。

集成测试检查服务端存活、正常清理退出码为 0 且未被强制终止，并保存日志尾部。慢接收端用例不保证触发所有部分发送分支。

## 结果记录

[报告索引](../reports/README.md) 保存逐项 JSON、CTest 日志/XML、环境与构建配置。复现时记录源码版本、命令、系统、编译器、连接数、正文大小、请求数及实际时长。

Release 四组各 3 秒的回环观察及复现命令见 [测量说明](measurement.md)；功能测试耗时不作为吞吐或单请求延迟。
