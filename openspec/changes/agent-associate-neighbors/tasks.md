## Phase 1: associate neighbors 模式

### T1: 实现
- [x] `mcs_agent/memory.py` `_do_associate`：`neighbors` 默认（get_relations 一跳、互斥前置、limit 截断、零 LLM）；`mcs` 保留旧 BFS + `render_query_result`
- [x] `mcs_agent/tools.py` `_associate`：默认 mode `neighbors`、透传 `limit`；schema description 更新（两模式成本标注）

### T2: 测试
- [x] neighbors：邻居渲染（含 [id:]）、互斥单列在前、limit 截断与剩余提示、种子不存在、孤立种子（载重过滤在 store 层，FakeStore 之外由 store 测试覆盖）
- [x] mcs 模式行为不变（existing_context + render_query_result）
- [x] 未知模式提示（含 neighbors 引导）

### T3: 验证
- [x] 全量回归（1322 passed）
- [ ] LoCoMo conv-26 重跑（v5）：对比 v1——延迟/管线调用数/正确率
