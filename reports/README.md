# 测试报告索引

原始 JSON、日志、XML 与环境文件按源码版本保存；归档日期为北京时间 2026-10-25。

## 最新验证

源码 `dad9d3b21aa2646e513e2658d3a0ab556771d012`，来源：[CI 40160429026](https://github.com/moonfellstargone-netizen/linux-cpp-message-service/actions/runs/40160429026)。三种构建均通过协议测试、21 项集成测试和 4 项测量工具检查，无失败或跳过。

- Debug：[JSON](ci-dad9d3b/debug/integration.json)、[环境](ci-dad9d3b/debug/environment.txt)、[构建](ci-dad9d3b/debug/build-config.txt)、[日志](ci-dad9d3b/debug/LastTest.log)、[XML](ci-dad9d3b/debug/ctest.xml)。
- ASan/UBSan：[JSON](ci-dad9d3b/asan-ubsan/integration.json)、[环境](ci-dad9d3b/asan-ubsan/environment.txt)、[构建](ci-dad9d3b/asan-ubsan/build-config.txt)、[日志](ci-dad9d3b/asan-ubsan/LastTest.log)、[XML](ci-dad9d3b/asan-ubsan/ctest.xml)。
- Release：[JSON](ci-dad9d3b/release/integration.json)、[环境](ci-dad9d3b/release/environment.txt)、[构建](ci-dad9d3b/release/build-config.txt)、[日志](ci-dad9d3b/release/LastTest.log)、[XML](ci-dad9d3b/release/ctest.xml)。

修复前源码 `ccfad9b435cc5cc2cff68d7494ff3470b0fdd8e3`，来源：[CI 40160330934](https://github.com/moonfellstargone-netizen/linux-cpp-message-service/actions/runs/40160330934)，保留 [失败 JSON](ci-ccfad9b/debug/integration.json) 与 [日志](ci-ccfad9b/debug/LastTest.log)。

客户端回复与 `--help` 输出到 `/dev/full` 时，旧版本均错误退出 0；修复后三种构建均退出 1，健康连接检查通过。复现过程见 [排障案例](../docs/debugging.md)。

## 四组测量记录

源码 `d78f93670998a85e228ce4296cf5d19b9fac49da`，来源：[CI 40110569171](https://github.com/moonfellstargone-netizen/linux-cpp-message-service/actions/runs/40110569171)。三种构建各通过协议测试、20 项集成测试与 4 项工具检查。

Release 四组单次回环观察，每组目标 3 秒、每连接预热 10 次、每连接最多 1 条未完成请求：

- [1 条连接、128 字节正文](ci-d78f936/release/load-1c-128b.json)。
- [4 条连接、128 字节正文](ci-d78f936/release/load-4c-128b.json)。
- [8 条连接、128 字节正文](ci-d78f936/release/load-8c-128b.json)。
- [4 条连接、1024 字节正文](ci-d78f936/release/load-4c-1024b.json)。

[环境](ci-d78f936/release/environment.txt)、[构建配置](ci-d78f936/release/build-config.txt) 与 [测量说明](../docs/measurement.md) 提供条件和计时口径；这些是同机短时观察，不代表生产容量。

## 历史目录

- `ci-58fb118`：源码 `58fb118dcc09f6786c144f83cc4f91e90722a252`，[CI 40104759981](https://github.com/moonfellstargone-netizen/linux-cpp-message-service/actions/runs/40104759981)；[Debug](ci-58fb118/debug/integration.json)、[ASan/UBSan](ci-58fb118/asan-ubsan/integration.json) 各通过 20 项集成测试。
- `ci-ed70dad`：源码 `ed70dad675e4692c22e6c69bc3910237326690a6`，[CI 40104175413](https://github.com/moonfellstargone-netizen/linux-cpp-message-service/actions/runs/40104175413)；[失败 JSON](ci-ed70dad/debug/integration.json)、[日志](ci-ed70dad/debug/LastTest.log) 记录 stdin 错误漏报与日志管道 SIGPIPE。
- `ci-5399f7b`：源码 `5399f7bdd86cf33ec706d149f8b3d4f3f87d0db3`，[CI 40098429400](https://github.com/moonfellstargone-netizen/linux-cpp-message-service/actions/runs/40098429400)；[Debug](ci-5399f7b/debug/integration.json)、[ASan/UBSan](ci-5399f7b/asan-ubsan/integration.json) 各通过首版 15 项集成测试。
