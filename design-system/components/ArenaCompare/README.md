# ArenaCompare

对战竞技场：两个模型并排流式作答（带闪烁光标与实时 token 计数），全部输出后裁判判定条从 50/50 弹性展开到最终比例，胜方卡片描边亮起。

`prompt`、`a`/`b`=`{model, text, latency}`、`verdict={a, b, reason}`、`judge`。A 方固定 signal，B 方固定 coral。
