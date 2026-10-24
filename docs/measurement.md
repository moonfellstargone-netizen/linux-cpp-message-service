# 本机回环测量与限制

这份记录用于练习“定义条件、执行、保存原始结果、解释限制”。服务端仍使用单线程非阻塞 `poll`，没有据此进行性能优化。四组短时观察不能证明最大连接容量、生产吞吐或可靠投递。

## 复现方法

在 Ubuntu 仓库目录内构建 Release 版本，无需安装额外 Python 库：

```bash
cmake -S . -B build-release -DCMAKE_BUILD_TYPE=Release -DMSG_ENABLE_SANITIZERS=OFF
cmake --build build-release
ctest --test-dir build-release --output-on-failure
python3 tests/load_probe.py --server ./build-release/message_server --connections 1 --message-bytes 128 --duration 3 --report build-release/test-results/load-1c-128b.json
python3 tests/load_probe.py --server ./build-release/message_server --connections 4 --message-bytes 128 --duration 3 --report build-release/test-results/load-4c-128b.json
python3 tests/load_probe.py --server ./build-release/message_server --connections 8 --message-bytes 128 --duration 3 --report build-release/test-results/load-8c-128b.json
python3 tests/load_probe.py --server ./build-release/message_server --connections 4 --message-bytes 1024 --duration 3 --report build-release/test-results/load-4c-1024b.json
```

脚本自动启动临时服务端并选择本机端口，结束后清理；不要提前启动同一个服务端。参数只接受 1–16 条连接、1–1024 字节正文和 0.1–30 秒的有限时长。这是测量工具的范围，不是服务端容量限制。

每条连接由一个 Python 线程驱动，保持一条未完成请求，收到并核对完整回复后才发送下一条。每连接先完成 10 次预热，再通过屏障进入公共计时窗口。每次运行会新建连接，连接建立和预热不计入观察窗口。

计时使用单调时钟：窗口从所有线程预热结束开始，到最后一条已发出请求的完整回复核对结束。到达指定时长后不再发起请求，已经发出的请求仍需完成，所以实际窗口可以略长于指定时长。启动、清理和写报告时间不计入窗口。任意线程、协议核对或服务端清理失败，工具非零退出，报告 `successful=false`、`summary=null`，不把部分数据发布成成功指标。

## 本次真实结果

来源为 [CI 40110569171](https://github.com/moonfellstargone-netizen/linux-cpp-message-service/actions/runs/40110569171) 的 Release 任务；源码 `d78f93670998a85e228ce4296cf5d19b9fac49da`，工作树干净。执行时间为 2026-10-24 16:13–16:14 UTC，即北京时间 2026-10-25 00:13–00:14。

环境为 GitHub 托管 Ubuntu 24.04、4 逻辑 CPU、AMD EPYC 9V45 型号标识，报告内存 16766414848 字节；GCC 13.3.0、CMake 3.31.6、Python 3.12.3。使用 Release 的 `-O3 -DNDEBUG`，未启用 sanitizer。驱动和服务端位于同一台托管机器，使用 `127.0.0.1`；这不是个人 Ubuntu 虚拟机或生产网络。

四组各执行一次，目标窗口均为 3 秒，每连接 10 次预热且只有一条未完成请求。以下数值为原始结果的四舍五入展示，不设置速度通过门槛：

- **1 条连接、128 字节正文**：完成 94652 次请求，实际 3.000023461 秒，31550.42 次/秒；驱动侧平均 RTT 0.031235 ms，最大 0.805004 ms。[原始 JSON](../reports/ci-d78f936/release/load-1c-128b.json)
- **4 条连接、128 字节正文**：完成 100089 次请求，实际 3.000276525 秒，33359.93 次/秒；驱动侧平均 RTT 0.119110 ms，最大 2.619159 ms。[原始 JSON](../reports/ci-d78f936/release/load-4c-128b.json)
- **8 条连接、128 字节正文**：完成 52479 次请求，实际 3.000663849 秒，17489.13 次/秒；驱动侧平均 RTT 0.456513 ms，最大 3.652189 ms。[原始 JSON](../reports/ci-d78f936/release/load-8c-128b.json)
- **4 条连接、1024 字节正文**：完成 94607 次请求，实际 3.000225992 秒，31533.29 次/秒；驱动侧平均 RTT 0.126041 ms，最大 5.088783 ms。[原始 JSON](../reports/ci-d78f936/release/load-4c-1024b.json)

四份报告均为成功：逐条响应核对通过，无工作线程错误，服务端正常退出 0、未强制终止。完整环境及构建条件见 [环境文件](../reports/ci-d78f936/release/environment.txt)、[构建缓存摘录](../reports/ci-d78f936/release/build-config.txt) 和 [报告来源](../reports/README.md)。

## 如何解释数字

- 完成速率是“已核对完整回复的请求数 ÷ 实际窗口秒数”。它包含客户端调度、Python 执行、socket 和服务端共同作用，不能当作纯服务端处理能力。
- RTT 从驱动开始发送请求，到收齐并核对响应结束，包含部分收发循环及调度。平均值按所有已完成请求加权计算；脚本只保存总和、最小和最大值，**没有采集 p95/p99**。
- 应用层字节数只计观察窗口内已完成请求及其回复，包括 4 字节长度头。请求每帧为 `4 + n` 字节；响应为 `4 + len("bytes=<n>\n") + n` 字节。预热、TCP/IP 开销和建连数据均不计入，不能当作网卡吞吐。
- 本次 8 条连接的完成速率低于 4 条连接是一个观察。**推测**：驱动线程调度、Python 执行和托管环境竞争等因素都可能参与；没有驱动／服务端 CPU 分析和重复实验，不能据此确定瓶颈，也不能认定 `poll` 需要替换。
- 每组只有一次短窗口，没有重复测量的离散程度、长时稳定性、独立负载机、CPU/内存峰值或真实网络时延证据。最大 RTT 是本次极值，不代表长期上界；数据也不构成优化前后的对照。

工具同时记录仓库 Git SHA、是否有未提交改动、二进制 SHA256、可读到的邻近 CMake 缓存及机器环境。本次 CI 在同一干净 checkout 构建并运行，四组二进制哈希一致。本地若传入其他来源的可执行文件，仓库 SHA 只说明测量工具所在仓库的版本，不能单靠它证明二进制的源码来源，应自行记录实际构建过程。

简历适合写“建立有条件、可复现的回环测量并归档结果”，不把某组每秒请求数写成生产容量，也不据此声明已经完成性能优化。
