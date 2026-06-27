# unified-graph-schema Spec Delta — dedup-fact-merge

## MODIFIED: 图质量最终收敛（去重 / 合并）

### Requirement: 图质量最终收敛（去重 / 合并）

重复的同名 / 同义概念 SHALL 由读写共同触发收敛：创建时对齐、之后被写 / 读触及时（read-repair）、聚类时合并。同名 SHALL 可由字面匹配当场识别，但 MUST NOT 仅凭同名盲并（同名未必同义，需消歧）。

事实去重 SHALL 按"同主 · 同宾 · 同说法"对齐；**后台维护扫描（dedup）MAY 合并同名字面事实**（背书 / 互斥边重挂；互为互斥的两事实 MUST NOT 合并以避免自互斥 / 矛盾塌缩）。

**注意**：聚类裂变（见「守门 = 改图即把关」requirement）对事实 MUST 仍只重组不合并——后台去重与聚类是不同操作。

完全未被触及 / 聚类的长尾残留 SHALL 由可选的后台维护扫描兜底。
