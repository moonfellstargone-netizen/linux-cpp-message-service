# 已执行测试报告

这里保存实际执行结果，避免仅依赖会过期的 CI 附件。日期为 2026-10-24，验证源码为 `5399f7bdd86cf33ec706d149f8b3d4f3f87d0db3`。

来源：[GitHub Actions 运行 40098429400](https://github.com/moonfellstargone-netizen/linux-cpp-message-service/actions/runs/40098429400)。报告从该运行的 `linux-tests-debug` 和 `linux-tests-asan-ubsan` 附件下载，保留原始内容，没有重新生成或编辑数值。

- [普通构建逐项 JSON](ci-5399f7b/debug/integration.json)、[环境](ci-5399f7b/debug/environment.txt)、[CTest 原始日志](ci-5399f7b/debug/LastTest.log)、[CTest XML](ci-5399f7b/debug/ctest.xml)。
- [ASan/UBSan 构建逐项 JSON](ci-5399f7b/asan-ubsan/integration.json)、[环境](ci-5399f7b/asan-ubsan/environment.txt)、[CTest 原始日志](ci-5399f7b/asan-ubsan/LastTest.log)、[CTest XML](ci-5399f7b/asan-ubsan/ctest.xml)。

两种构建均通过协议测试和 15 项集成测试，失败、错误与跳过数均为 0。普通构建测试机器为 4 逻辑 CPU 的 AMD EPYC 9V45，sanitizer 构建机器为 4 逻辑 CPU 的 AMD EPYC 7763；两者报告内存均为 16766414848 字节。系统为 Ubuntu 24.04，GCC 13.3.0、CMake 3.31.6、Python 3.12.3。完整信息以各环境文件为准。

请求正文包括 1、1024 字节边界及逐用例列出的其他大小；非法声明包含 0、1025 和 4294967295。正常用例同时使用 3 条连接；上限用例保持 64 条已完成请求的连接，并验证下一条被拒绝。重复连接用例执行 50 次顺序连接。各用例耗时、慢接收端的时间/字节预算及实际观察在 JSON 内逐项记录。

这是本机回环地址上的功能、异常与资源观察，不是吞吐、延迟或生产容量测试。CI 使用托管虚拟机，不代表维护者的 Ubuntu 虚拟机已经复现；FD 回到基线和 sanitizer 未报告错误也不能证明所有路径没有缺陷。
