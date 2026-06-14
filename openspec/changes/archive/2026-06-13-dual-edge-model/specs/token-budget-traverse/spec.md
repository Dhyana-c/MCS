## REMOVED Requirements

### Requirement: SeedSelector 和 _traverse 复用同一 LLM purpose

**Reason**：种子定位改为**字面实体链接（jieba foothold）**，不再是 LLM purpose；`_traverse` 改用 `select_facts`。二者不再共享同一 purpose，原"复用"约束作废（`SeedSelectorPluginInterface` 亦已废弃）。种子经字面 foothold + 反查 + 多种子取得，遍历的事实选择由 `select_facts` 承担。
