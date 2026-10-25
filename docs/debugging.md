# 排障记录

## 客户端输出失败却返回成功

- **现象**：将 stdout 指向 `/dev/full`，合法请求回复和 `--help` 两个场景都返回 0，实际输出未写成功。
- **原因**：客户端只校验网络回复，没有检查 `std::cout`；输出还可能停留在缓冲区，直到刷新时才发现 `ENOSPC`。
- **修复**：增加 `flush_stdout`，在帮助、交互提示和回复输出后刷新并检查流状态。失败时报告 `stdout write failed`，返回 1，停止处理后续输入。
- **证据**：[修复前 `ccfad9b`](../reports/ci-ccfad9b/debug/integration.json) 两个子场景均退出 0；[修复后 `dad9d3b`](../reports/ci-dad9d3b/debug/integration.json) 均退出 1，健康连接仍正常。Debug、ASan/UBSan、Release 三种构建均通过回归，见 [报告归档](../reports/README.md)。

不启动服务端也能检查帮助输出：

```bash
./build/message_client --help >/dev/full
echo $?
```

回复路径需先启动服务端：

```bash
printf 'stdout error\n' | ./build/message_client 127.0.0.1 9000 >/dev/full
echo $?
```

两者预期退出码为 1。输出失败不表示请求未被处理；刷新也不提供文件持久化保证。

## 日志管道关闭导致服务端退出

- **现象**：启动 stderr 指向管道的服务端，关闭管道读取端后再建立连接。连接日志触发进程退出，状态为 `-13`（SIGPIPE），客户端连接被重置。
- **原因**：socket 发送已使用 `MSG_NOSIGNAL`，但它不能保护 `std::cerr` 向管道写日志。
- **修复**：启动时通过 `sigaction` 忽略 SIGPIPE，保留 socket 的 `MSG_NOSIGNAL`。日志目标关闭后仍可处理请求；不会自动恢复日志目标，也未解决日志写入阻塞。
- **证据**：[修复前 `ed70dad`](../reports/ci-ed70dad/debug/integration.json) 的 `test_closed_stderr_pipe_isolation` 记录退出 `-13`；[修复后 `58fb118`](../reports/ci-58fb118/debug/integration.json) 该用例通过，正常清理退出 0。

两个场景均包含在集成测试中：

```bash
python3 tests/integration_test.py --server ./build/message_server --client ./build/message_client --report build/test-results/integration.json
```
