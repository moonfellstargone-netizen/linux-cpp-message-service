# 已执行测试报告

这里保存实际执行结果，避免仅依赖会过期的 CI 附件。最新归档日期为北京时间 2026-10-25，各快照对应下面明确列出的源码版本；原始报告没有重新生成或修改数值。

## 最新 stdout 修复与 21 项回归

验证源码为 `dad9d3b21aa2646e513e2658d3a0ab556771d012`，来源为 [CI 40160429026](https://github.com/moonfellstargone-netizen/linux-cpp-message-service/actions/runs/40160429026)。Debug、ASan/UBSan 和 Release 三种构建各通过协议测试、21 项集成测试及 4 项测量工具检查，无失败或跳过。

- Debug：[网络 JSON](ci-dad9d3b/debug/integration.json)、[环境](ci-dad9d3b/debug/environment.txt)、[构建配置](ci-dad9d3b/debug/build-config.txt)、[CTest 日志](ci-dad9d3b/debug/LastTest.log)、[CTest XML](ci-dad9d3b/debug/ctest.xml)。来源附件 `linux-tests-debug`，ID `12585892201`。
- ASan/UBSan：[网络 JSON](ci-dad9d3b/asan-ubsan/integration.json)、[环境](ci-dad9d3b/asan-ubsan/environment.txt)、[构建配置](ci-dad9d3b/asan-ubsan/build-config.txt)、[CTest 日志](ci-dad9d3b/asan-ubsan/LastTest.log)、[CTest XML](ci-dad9d3b/asan-ubsan/ctest.xml)。来源附件 `linux-tests-asan-ubsan`，ID `12586246886`。
- Release：[网络 JSON](ci-dad9d3b/release/integration.json)、[环境](ci-dad9d3b/release/environment.txt)、[构建配置](ci-dad9d3b/release/build-config.txt)、[CTest 日志](ci-dad9d3b/release/LastTest.log)、[CTest XML](ci-dad9d3b/release/ctest.xml)。来源附件 `linux-tests-release`，ID `12586256809`。

修复前 `ccfad9b435cc5cc2cff68d7494ff3470b0fdd8e3` 的 [CI 40160330934](https://github.com/moonfellstargone-netizen/linux-cpp-message-service/actions/runs/40160330934) 真实失败。归档其 Debug 附件 `linux-tests-debug`（ID `12585817243`）的 [JSON](ci-ccfad9b/debug/integration.json)、[环境](ci-ccfad9b/debug/environment.txt)、[构建配置](ci-ccfad9b/debug/build-config.txt)、[日志](ci-ccfad9b/debug/LastTest.log) 与 [CTest XML](ci-ccfad9b/debug/ctest.xml)。

新增用例将客户端 stdout 指向 `/dev/full`：合法请求正文 12 字节，随后健康连接请求正文 13 字节；另检查不连接服务端的 `--help`。两个子场景均有 5 秒进程超时，旧版本都退出 0，导致同一用例记 2 failures；修复后三种构建均退出 1，精确诊断检查及健康连接检查通过。所有文件均直接摘自对应附件，保留原始数值；解释与复现见 [排障案例](../docs/debugging.md)。

本轮归档用于功能回归，没有将运行耗时作为性能指标。下方四组测量仍属于原 `d78f936` 快照，未随本轮客户端修复改写。

## 前次三种构建与有界观察

源码为 `d78f93670998a85e228ce4296cf5d19b9fac49da`，来源为 [CI 运行 40110569171](https://github.com/moonfellstargone-netizen/linux-cpp-message-service/actions/runs/40110569171)，执行于 2026-10-24 16:13–16:14 UTC（北京时间 2026-10-25）。三种构建各有 3 个 CTest 测试组：协议测试、20 项网络集成测试、4 项测量工具检查；均通过，无失败或跳过。

- Debug：[网络 JSON](ci-d78f936/debug/integration.json)、[环境](ci-d78f936/debug/environment.txt)、[构建配置](ci-d78f936/debug/build-config.txt)、[CTest 日志](ci-d78f936/debug/LastTest.log)、[CTest XML](ci-d78f936/debug/ctest.xml)。附件 `linux-tests-debug`，ID `12566596830`。
- ASan/UBSan：[网络 JSON](ci-d78f936/asan-ubsan/integration.json)、[环境](ci-d78f936/asan-ubsan/environment.txt)、[构建配置](ci-d78f936/asan-ubsan/build-config.txt)、[CTest 日志](ci-d78f936/asan-ubsan/LastTest.log)、[CTest XML](ci-d78f936/asan-ubsan/ctest.xml)。附件 `linux-tests-asan-ubsan`，ID `12566048693`。
- Release：[网络 JSON](ci-d78f936/release/integration.json)、[环境](ci-d78f936/release/environment.txt)、[构建配置](ci-d78f936/release/build-config.txt)、[CTest 日志](ci-d78f936/release/LastTest.log)、[CTest XML](ci-d78f936/release/ctest.xml)。附件 `linux-tests-release`，ID `12566221962`。

Release 另执行四组单次回环观察，每组目标 3 秒、每连接预热 10 次、一条未完成请求；全部逐条核对回复并正常退出：

- [1 条连接、128 字节正文](ci-d78f936/release/load-1c-128b.json)。
- [4 条连接、128 字节正文](ci-d78f936/release/load-4c-128b.json)。
- [8 条连接、128 字节正文](ci-d78f936/release/load-8c-128b.json)。
- [4 条连接、1024 字节正文](ci-d78f936/release/load-4c-1024b.json)。

以上文件从对应附件解压，保留原始内容。数字解释、环境、计时方式和复现命令见 [测量说明](../docs/measurement.md)。它们是驱动与服务端同机的短时观察，没有重复实验的稳定性结论，不能与下面功能测试耗时混用，也不是生产容量数据。

## 前次 20 项修复回归

最终修复源码为 `58fb118dcc09f6786c144f83cc4f91e90722a252`，来源为 [CI 运行 40104759981](https://github.com/moonfellstargone-netizen/linux-cpp-message-service/actions/runs/40104759981)。普通构建与 ASan/UBSan 构建均通过协议测试和 20 项集成测试，失败、错误、跳过数均为 0。

- [普通构建 JSON](ci-58fb118/debug/integration.json)、[环境](ci-58fb118/debug/environment.txt)、[CTest 日志](ci-58fb118/debug/LastTest.log)、[CTest XML](ci-58fb118/debug/ctest.xml)。
- [ASan/UBSan 构建 JSON](ci-58fb118/asan-ubsan/integration.json)、[环境](ci-58fb118/asan-ubsan/environment.txt)、[CTest 日志](ci-58fb118/asan-ubsan/LastTest.log)、[CTest XML](ci-58fb118/asan-ubsan/ctest.xml)。

修复前复现版本为 `ed70dad675e4692c22e6c69bc3910237326690a6`，来源为 [CI 运行 40104175413](https://github.com/moonfellstargone-netizen/linux-cpp-message-service/actions/runs/40104175413)。保留 [失败 JSON](ci-ed70dad/debug/integration.json)、[原始日志](ci-ed70dad/debug/LastTest.log)、[环境](ci-ed70dad/debug/environment.txt) 与 [CTest XML](ci-ed70dad/debug/ctest.xml)。该运行确实失败，不能当作通过记录：stdin 错误用例返回 0，日志关闭用例的专属服务端退出 -13。同一用例可能在执行和清理时各记一次错误，所以汇总 2 failures、1 error 来自两个故障用例。

本轮新增用例包括 2097152 字节超长输入及恢复、UTF-8 边界、EOF 尾行、目录 stdin 和关闭日志管道。超长输入是客户端本地拒绝检查，不是发送了 2 MiB 请求，也没有测量客户端峰值内存。实际连接数、请求大小、每项耗时及环境逐项保存在 JSON 中。

## 首版 15 项记录

验证源码为 `5399f7bdd86cf33ec706d149f8b3d4f3f87d0db3`，保留用于追溯初版结果，不代替本轮 20 项回归。

来源：[GitHub Actions 运行 40098429400](https://github.com/moonfellstargone-netizen/linux-cpp-message-service/actions/runs/40098429400)。报告从该运行的 `linux-tests-debug` 和 `linux-tests-asan-ubsan` 附件下载，保留原始内容，没有重新生成或编辑数值。

- [普通构建逐项 JSON](ci-5399f7b/debug/integration.json)、[环境](ci-5399f7b/debug/environment.txt)、[CTest 原始日志](ci-5399f7b/debug/LastTest.log)、[CTest XML](ci-5399f7b/debug/ctest.xml)。
- [ASan/UBSan 构建逐项 JSON](ci-5399f7b/asan-ubsan/integration.json)、[环境](ci-5399f7b/asan-ubsan/environment.txt)、[CTest 原始日志](ci-5399f7b/asan-ubsan/LastTest.log)、[CTest XML](ci-5399f7b/asan-ubsan/ctest.xml)。

两种构建均通过协议测试和 15 项集成测试，失败、错误与跳过数均为 0。普通构建测试机器为 4 逻辑 CPU 的 AMD EPYC 9V45，sanitizer 构建机器为 4 逻辑 CPU 的 AMD EPYC 7763；两者报告内存均为 16766414848 字节。系统为 Ubuntu 24.04，GCC 13.3.0、CMake 3.31.6、Python 3.12.3。完整信息以各环境文件为准。

请求正文包括 1、1024 字节边界及逐用例列出的其他大小；非法声明包含 0、1025 和 4294967295。正常用例同时使用 3 条连接；上限用例保持 64 条已完成请求的连接，并验证下一条被拒绝。重复连接用例执行 50 次顺序连接。各用例耗时、慢接收端的时间/字节预算及实际观察在 JSON 内逐项记录。

这是本机回环地址上的功能、异常与资源观察，不是吞吐、延迟或生产容量测试。CI 使用托管虚拟机，不代表维护者的 Ubuntu 虚拟机已经复现；FD 回到基线和 sanitizer 未报告错误也不能证明所有路径没有缺陷。
