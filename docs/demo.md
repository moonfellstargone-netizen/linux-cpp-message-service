# 多客户端演示

按 [README](../README.md) 构建后，打开三个 Ubuntu 终端。

终端 A 启动服务端：

```bash
./build/message_server 9000
```

终端 B、C 各启动一个客户端：

```bash
./build/message_client 127.0.0.1 9000
```

1. B 输入 `hello`，应收到 `bytes=5` 和原文。
2. C 输入 `world`，应收到自己的回复；B、C 的消息不互相转发。
3. 在 C 按 `Ctrl+C`，观察 A 的连接清理日志，再从 B 发送消息。
4. 重新启动 C，确认可再次请求；使用 `/quit` 正常退出客户端。

服务端停止后再次运行客户端，应看到连接错误。同一端口重复启动服务端，应看到 `bind_failed`。

非法长度、残帧和半关闭由 [自动测试](testing.md) 验证；输出失败的复现方法见 [排障记录](debugging.md)。
