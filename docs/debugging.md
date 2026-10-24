# 真实排障记录

## 案例：集成测试漏查服务端退出码

发现日期：2026-10-24。问题位于 [连接测试脚本](../tests/integration_test.py) 的 `RunningServer.close` 与 `IntegrationTests.close_server` 清理流程。

这是实际发现并复现的**测试工具缺陷**。没有观察到真实 C++ 服务端内存泄漏，也没有复现真实 ASan/LSan 报错；下面的退出码 `1` 是为核对测试判定而主动构造的故障。

### 发现与原因

首次 Ubuntu CI 的协议测试和 14 项连接测试通过后，再次审查发现：`tearDown` 只在清理前检查服务端是否仍存活；清理时发送停止请求，等待进程退出，只断言没有超时强制终止。脚本虽然记录了退出码，却未要求退出码为 `0`。

因此，“服务端正常接收请求，但在清理退出阶段返回非零状态”可能被当作测试通过。退出时发生的 sanitizer 错误也有被漏报的可能；这是根据控制流程得到的风险判断，不是本项目已发生泄漏的证据。原流程还会删除临时日志，难以保留失败原因。

### 最小复现与证据

在 Windows 本地，通过 `importlib.util` 导入真实测试脚本，启动一个自行 `SystemExit(1)` 的真实 Python 子进程，等待结束后，将其交给清理检查。包装对象只隔离清理判定，不启动 TCP 服务。

下面的 Python 片段应在仓库根目录执行，仅依赖标准库：

```python
import importlib.util
import subprocess
import sys

spec = importlib.util.spec_from_file_location("integration", "tests/integration_test.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

child = subprocess.Popen([sys.executable, "-c", "raise SystemExit(1)"])
child.wait()
assert child.returncode == 1

class ExitFailure:
    process = child
    last_log = "controlled test process exited with code 1"

    def close(self):
        return False

case = module.IntegrationTests("test_multiple_clients")
case.server = ExitFailure()
case.observations = {}
try:
    case.close_server()
except AssertionError:
    print("VERIFIED: cleanup now rejects a real child exit code of 1")
else:
    print("REPRODUCED: cleanup accepted a real child exit code of 1")
```

修复前实际输出：`REPRODUCED: cleanup accepted a real child exit code of 1`。

修复后实际输出：`VERIFIED: cleanup now rejects a real child exit code of 1`。新断言包含受控退出的日志信息。

另外，独立审查中也用最小替身对象核对了判断逻辑：`forced_kill=False`、`returncode=1` 时，旧 `close_server` 不报错。这个检查只验证断言缺失，不能代替上述真实子进程验证或 Linux 服务端回归。

这个子进程自行返回 `1`，没有对其调用 `terminate`；包装对象的 `close` 返回 `False` 表示本检查没有触发超时强制终止。它验证的是清理退出码判定，不是完整 TCP 用例、Linux `SIGTERM` 处理或真实 LSan 行为。

### 修复

- 清理等待结束后断言服务端 `returncode == 0`，保留原来的超时强制终止检查。
- 删除临时日志目录前读取日志，将最后 4000 个字符写入测试观察记录，并附加到退出失败的断言信息中。
- 保留清理前的存活检查，分别检查运行期间意外退出与退出阶段失败。

修复针对测试判定和证据保留，没有为构造案例而修改 C++ 服务端，也没有宣称修复了服务端泄漏。

### 验证状态与限制

Windows 本地受控真实子进程检查：**已验证**。旧逻辑接受退出码 `1`，新逻辑拒绝退出码 `1`。

包含修复的第二次 Ubuntu 普通构建、ASan/UBSan 构建及连接测试：**已通过**。提交 `5399f7b` 的 [CI 运行](https://github.com/moonfellstargone-netizen/linux-cpp-message-service/actions/runs/40098429400) 中，两种构建均通过协议测试和 15 项连接测试，无跳过项。新增的 64 条连接保持在线、第 65 条被拒绝、原连接仍可工作的用例也通过；原始记录见 [报告归档](../reports/README.md)。

后续实际 CI 结果与提交信息统一记录在 [验证状态](status.md)。即使回归通过，也只能支持本次场景下的结论，不能证明所有内存、资源或网络错误已被覆盖。用户本人对本案例的独立复现与解释验收仍待完成。

## 本轮真实 Ubuntu 故障记录

提交 `ed70dad675e4692c22e6c69bc3910237326690a6` 的 [Ubuntu debug 任务](https://github.com/moonfellstargone-netizen/linux-cpp-message-service/actions/runs/40104175413/job/120902306117) 实际运行了 20 项集成测试，结果为 **2 个 failure、1 个 error**。它们来自下面两个故障用例；日志管道用例既发生连接错误，又在清理时发现异常退出，因此不能将汇总数字解释为三个独立失败用例。

### 案例：stdin 读取错误被当作正常 EOF

相关代码为 [命令行客户端](../src/client.cpp)，回归用例为 `test_client_stdin_read_error`。

此前已将整行读取改为有界读取：正文只保留最多 1024 字节，超长行的剩余输入丢弃到行尾，再处理下一行。在上述故障提交中，2 MiB 超长行、长度边界、UTF-8、末行无换行等用例已能通过，但输入错误检查仍有遗漏。

用例在 Linux 上打开一个目录的只读描述符，将它作为客户端 stdin。底层读取目录返回 `EISDIR`；预期客户端报告 `stdin read failed` 并以非零状态退出。实际客户端返回 `0`，触发“读取错误被报告为成功 EOF”的断言失败。

原因是程序使用默认的 C / C++ 标准输入同步模式，仅凭 `std::istream` 的 `bad()` / `eof()` 判断，没有覆盖底层 stdio 错误被呈现为 EOF 的情况。修复提交 `58fb118` 在读取返回后增加 `std::ferror(stdin)` 检查，将底层输入错误转换成明确错误和非零退出，不把它作为正常输入结束。

这是一项真实输入错误处理修复。2 MiB 用例验证超长行被拒绝后仍能处理合法行，没有测量峰值内存；因此不报告内存占用数字，也不声称测出了内存优化幅度。

### 案例：关闭日志管道使服务端收到 SIGPIPE

相关代码为 [服务端信号设置与连接日志](../src/server.cpp)，回归用例为 `test_closed_stderr_pipe_isolation`。

用例单独启动一个 stderr 指向管道的服务端，关闭父进程持有的管道读取端，然后建立连接并发送合法请求。接受连接会写入 `std::cerr`，此时日志管道已没有读取者。实际连接被 reset，清理记录中服务端退出状态为 `-13`，表示进程因 `SIGPIPE` 终止。

触发点是**日志管道写入**。TCP 回复发送路径原本就使用 `MSG_NOSIGNAL`，但这个标志只保护对应的 socket 发送，不能保护 `std::cerr` 向管道写日志。

修复提交 `bd6834b` 在 `install_signal_handlers` 中通过 `sigaction` 将 `SIGPIPE` 的处理方式设为 `SIG_IGN`，保留原有 socket 的 `MSG_NOSIGNAL`。回归预期为关闭日志读取端后仍能完成合法请求，服务端保持存活，并在正常清理时返回 `0`。

忽略信号不会恢复已经关闭的日志目标，也不保证这段日志能被保存。修复范围是避免该日志输出故障直接终止整个服务端，没有引入日志框架，也没有解决任意日志写入阻塞问题。

### 如何复现与回归

在 Ubuntu 仓库根目录完成对应提交的构建后，可直接运行现有脚本，保存全部 20 项用例的真实结果：

```bash
python3 tests/integration_test.py --server ./build/message_server --client ./build/message_client --report build/test-results/integration.json
```

只检查上述两个场景时，可复用脚本中的原有测试方法，避免另外手写一套网络复现逻辑：

```bash
python3 - <<'PY'
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

spec = importlib.util.spec_from_file_location("integration", "tests/integration_test.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.CONFIG = SimpleNamespace(
    server=Path("build/message_server").resolve(),
    client=Path("build/message_client").resolve(),
)
suite = unittest.TestSuite(module.IntegrationTests(name) for name in (
    "test_client_stdin_read_error",
    "test_closed_stderr_pipe_isolation",
))
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
PY
```

该片段适用于 Linux，读取目录用例在其他系统会跳过。故障提交的输出用于说明问题确实存在；修复后的通过情况应由对应提交的实际结果确认。

本轮还在 `bd6834b` 的 CMake sanitizer 配置中加入 `-fno-sanitize-recover=undefined`，使本地启用 UBSan 时也要求已检出的 undefined behavior 导致非零退出，而不只依赖 CI 的 `UBSAN_OPTIONS=halt_on_error=1`。这是测试判定配置修正，没有向正式服务端注入 UB，也没有观察到本项目的真实 UB 故障。

包含两项修复的提交 `58fb118dcc09f6786c144f83cc4f91e90722a252` 已在 [CI 运行 40104759981](https://github.com/moonfellstargone-netizen/linux-cpp-message-service/actions/runs/40104759981) 完成 Ubuntu 普通与 ASan/UBSan 回归：两种构建均通过协议测试及 20 项集成测试，没有失败、错误或跳过。原始报告的下载、字段复核与来源记录统一放在 [验证状态](status.md) 和 [报告归档](../reports/README.md)，以归档实际内容为准；不使用先前提交的通过结果替代本轮验证。
