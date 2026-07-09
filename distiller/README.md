# 语义蒸馏器

语义蒸馏刻意放在 hook 和 raw collection 同步路径之外。

使用 `semantic-distillation` skill 读取一条已经采集完成的 trajectory bundle，
先准备确定性的证据索引，再把蒸馏产物写入
`trajectories/distilled/<trajectory_id>/<distillation_run_id>/`。
