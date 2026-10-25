# 本机回环测量

以下结果来自源码 `d78f936` 的 [Release CI](https://github.com/moonfellstargone-netizen/linux-cpp-message-service/actions/runs/40110569171)，执行于北京时间 2026-10-25 00:13–00:14，完整快照见 [报告归档](../reports/README.md)。

## 复现

在 Ubuntu 仓库目录构建后运行，脚本自动启动和清理临时服务端：

```bash
cmake -S . -B build-release -DCMAKE_BUILD_TYPE=Release -DMSG_ENABLE_SANITIZERS=OFF
cmake --build build-release
(cd build-release && ctest --output-on-failure)
python3 tests/load_probe.py --server ./build-release/message_server --connections 1 --message-bytes 128 --duration 3 --report build-release/test-results/load-1c-128b.json
python3 tests/load_probe.py --server ./build-release/message_server --connections 4 --message-bytes 128 --duration 3 --report build-release/test-results/load-4c-128b.json
python3 tests/load_probe.py --server ./build-release/message_server --connections 8 --message-bytes 128 --duration 3 --report build-release/test-results/load-8c-128b.json
python3 tests/load_probe.py --server ./build-release/message_server --connections 4 --message-bytes 1024 --duration 3 --report build-release/test-results/load-4c-1024b.json
```

## 环境与口径

GitHub 托管 Ubuntu 24.04；AMD EPYC 9V45 型号标识，4 逻辑 CPU，内存 16766414848 字节；GCC 13.3.0、CMake 3.31.6、Python 3.12.3。Release 使用 `-O3 -DNDEBUG`，sanitizer 关闭，驱动与服务端在同机 `127.0.0.1` 通信。见 [环境](../reports/ci-d78f936/release/environment.txt) 和 [构建配置](../reports/ci-d78f936/release/build-config.txt)。

每组运行一次，目标窗口 3 秒。每连接由一个 Python 线程驱动，预热 10 次后通过屏障共同计时，同一连接仅保留一条未完成请求，逐条核对完整回复。实际窗口从公共开始时刻到最后一次回复核对完成，不含建连、预热和清理；最后一条请求可以跨过截止时刻。完成速率为请求总数除以实际窗口，RTT 从开始发送到完整核对结束；失败报告不产生成功指标。

## 实际结果

- **1 连接、128 字节**：94652 次，3.000023461 秒，31550.42 次/秒；平均 RTT 0.031235 ms，最大 0.805004 ms。[JSON](../reports/ci-d78f936/release/load-1c-128b.json)
- **4 连接、128 字节**：100089 次，3.000276525 秒，33359.93 次/秒；平均 RTT 0.119110 ms，最大 2.619159 ms。[JSON](../reports/ci-d78f936/release/load-4c-128b.json)
- **8 连接、128 字节**：52479 次，3.000663849 秒，17489.13 次/秒；平均 RTT 0.456513 ms，最大 3.652189 ms。[JSON](../reports/ci-d78f936/release/load-8c-128b.json)
- **4 连接、1024 字节**：94607 次，3.000225992 秒，31533.29 次/秒；平均 RTT 0.126041 ms，最大 5.088783 ms。[JSON](../reports/ci-d78f936/release/load-4c-1024b.json)

四组均核对成功，工作线程无错误，服务端正常退出 0、未强制终止。报告另保存源码版本、二进制 SHA256、构建配置和环境。

这些是同机短时观察，包含 Python 驱动和调度开销，不能当作纯服务端或生产容量。每组只测一次，没有 p95/p99、长期稳定性、峰值内存或优化前后对照；8 连接速率下降也不足以确定瓶颈。应用帧字节数含 4 字节头，不含预热与 TCP/IP 开销。归档保留原版本结果，重新运行不保证得到相同数字。
