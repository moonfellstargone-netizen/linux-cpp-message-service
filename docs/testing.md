# 测试方法

## 状态与目的

2026-10-25（北京时间），验证提交 `d78f936` 在 GitHub Actions Ubuntu 24.04 的 Debug、ASan/UBSan 和 Release 构建下均通过协议测试、20 项连接测试及 4 项测量工具检查，无失败、无跳过。详见 [CI 运行](https://github.com/moonfellstargone-netizen/linux-cpp-message-service/actions/runs/40110569171) 与 [原始报告](../reports/README.md)。本人 Ubuntu 虚拟机复现和手工演示仍待执行。

CTest 包含三个测试组：纯协议测试验证长度、边界和字节保留；真实 socket 集成测试验证连接收发、断开及错误隔离；测量工具检查验证结果自洽及失败时不会报告成功指标。程序在某次测试中通过，不等于不存在其他缺陷。

## 构建与运行

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Debug
cmake --build build
ctest --test-dir build --output-on-failure
```

备用构建入口：

```bash
bash scripts/build.sh
./build/protocol_tests
```

集成测试使用 Python 3 标准库，自动选择本地端口并启动、停止自己的服务端进程，不需要手工提前运行服务端。单独运行并保存可选 JSON 报告：

```bash
python3 tests/integration_test.py --server ./build/message_server --client ./build/message_client --report build/test-results/integration.json
```

备用构建后也可使用上面的 Python 命令进行真实连接验证；具体参数可查看 `python3 tests/integration_test.py --help`。测量工具的 4 项检查可单独运行：

```bash
python3 tests/load_probe_test.py --server ./build/message_server
```

检查包括短时真实运行的报告一致性、10 组非法参数、服务端文件缺失以及服务端启动失败。没有设置“速度必须达到某值”的通过条件。

GitHub Actions 会在推送和拉取请求时执行 Debug、Release，以及启用 AddressSanitizer / UndefinedBehaviorSanitizer 的 Debug 构建。网络集成用例检查服务端运行时存活、清理时未被强制终止且退出码为 0，保存日志尾部，避免漏掉退出阶段失败。每次运行的结果仅适用于对应提交，在 [验证状态](status.md) 登记。

Release 任务还单独执行四组各 3 秒的回环观察，并保存 JSON；它们与功能测试分开解释，条件、计时口径和复现命令见 [测量说明](measurement.md)。没有据此更换 I/O 模型或添加线程池。

本地启用相同的编译检测：

```bash
cmake -S . -B build-asan -DCMAKE_BUILD_TYPE=Debug -DMSG_ENABLE_SANITIZERS=ON
cmake --build build-asan
ctest --test-dir build-asan --output-on-failure
```

GNU/Clang 配置包含 `-fno-sanitize-recover=undefined`，防止本地 UBSan 仅打印错误后继续成功退出；不只依赖 CI 的环境变量。该参数语义参见 [GCC 文档](https://gcc.gnu.org/onlinedocs/gcc/Instrumentation-Options.html)。本轮没有在正式服务中注入 UB。

## 应覆盖的行为

- 正常小消息、1 字节及 1024 字节边界；二进制 NUL 和 UTF-8 原始字节按字节数处理。
- 头被拆开、正文被拆开、不完整输入暂不产生完整回复；多个请求帧连续发送并依次得到回复。
- 长度为 0、1025 及极大无符号数；仅发送非法长度头就应被拒绝，不等待其声明的巨大正文。
- 请求发到一半就关闭连接；完整请求后半关闭发送方向，仍可接收响应。
- 一个客户端发送非法请求或异常退出，同时正常客户端继续请求回复。
- 重复连接和断开，观察连接能否重新建立及资源是否恢复；连接上限和缓冲保护需有对应检查。
- CLI 的 2 MiB 超长行、1024/1025 字节与 UTF-8 边界、空行恢复、`/quit`、无末尾换行及超长 EOF；精确检查 stdout 响应序列与 stderr 本地诊断。
- Linux 目录描述符作为 stdin 时客户端报告读取错误并非零退出；关闭服务端 stderr 管道读取端后合法请求仍正常，服务端保持存活并正常清理。

本次资源观察：50 次顺序连接前后 FD 均为 4；持有 64 条已完成请求的连接后，第 65 条被拒绝，已有连接仍可请求。慢接收端场景的服务端日志实际记录了 `pending_limit`，另一连接仍得到正确回复。这些是功能及保护策略的验证，不是性能容量结论。完整消息大小、时间、环境和日志见归档 JSON。

不是所有网络路径都能靠一次运行触发。例如短消息测试可能没有真正触发部分发送。必须区分“实现处理了该状态”和“本次用例观测到了该状态”，不把分帧发送测试宣称为所有网络异常的证明。

## 每次真实验证需要记录

- 执行日期、系统及版本、CPU/内存、编译器和构建方式，是否运行在虚拟机中。
- 对应源码版本、运行命令、测试结果与失败原因。
- 客户端或连接数量、消息正文大小、请求次数、持续时间；顺序重复连接和同时在线连接分开记录。
- 自动报告路径，以及手工演示、日志或抓包的必要证据。分享前检查输出中是否混入个人信息。

没有实测时写“未测”或“待执行”，不填写猜测的吞吐或延迟。脚本耗时是该组测试的运行时间，不能直接当作服务端吞吐或单请求延迟。

## Linux 资源观察

Linux 上可在重复连接前后观察服务端 `/proc/<pid>/fd` 数量，并在进程仍运行时比较。应记录观察时机、进程 PID、重复次数及是否等待连接清理完成。

FD 数回到基线，只能说明本次场景未观察到持续增加的描述符；它不能证明没有内存泄漏，也不能覆盖所有 FD 路径。虚拟内存或常驻内存的单次变化同样不能直接判定泄漏。

连接上限是保护性配置。本项目所有自动连接与消息仅为本地模拟，不能表述为企业生产流量、线上压测或已证实的生产并发能力。已有短时观察不构成容量结论；优化前仍需按具体问题定义负载、重复次数、持续时间和指标。
