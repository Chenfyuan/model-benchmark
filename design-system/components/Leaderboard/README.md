# Leaderboard

模型排行榜：切换维度时，行按新排名以弹簧动画重新排位，得分条同步伸缩，数字从旧值滚到新值。

`rows=[{model, org, delta, scores:{[metricKey]: number}}]`、`metrics=[{key,label}]`、`max`（默认 100）、`rowHeight`。第一名整行高亮 `signal-soft`，头像填充 `signal`——全表唯一的品牌色位置。
