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
