# RunProgress

评测任务进度：每个任务一行，进度条在运行时有流光，状态切换时徽章弹出。

`jobs=[{name, model, suite, done, total, status}]`，`status` 为 running / queued / done / failed。`simulate` 开启演示模式：进度自动推进、排队任务自动接力、底部滚动样本日志。
