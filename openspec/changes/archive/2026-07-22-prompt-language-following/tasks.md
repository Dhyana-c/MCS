## 1. 写入侧 prompt 语言跟随指令

- [x] 1.1 `extract_concepts`：`SYSTEM_PROMPT` / `USER_TEMPLATE` 加语言跟随指令——`content` MUST 用输入文本原文语言、**知名实体（如 Apple/Tesla/Google 等有其他语言译名者）MUST NOT 翻译**、保留原文表述
- [x] 1.2 `extract_work_events`：同上——事件 `content` 与参与者名跟随作品文本原文语言
- [x] 1.3 `judge_relations`：命题节点 `content` / `Decision.reason` 跟随被判定概念的原文语言
- [x] 1.4 `decide_hub`：社区 `theme` / `summary` MUST 跟随被处理节点群的原文语言（实测漂移点）
- [x] 1.5 `generalize`：概括结论 MUST 跟随被概括节点的原文语言
- [x] 1.6 `gen_summary` / `gen_graph_summary`：摘要 MUST 跟随被摘要节点的原文语言
- [x] 1.7 `synthesize`：合成答案 MUST 跟随查询/节点原文语言
- [x] 1.8 `merge_content`：合并后 `content` MUST 跟随原节点原文语言

## 2. node_class 枚举英文化 + parse 映射

- [x] 2.1 `extract_concepts`：prompt 中 `node_class="概念"|"事实"` 字面值改为 `"concept"|"fact"`
- [x] 2.2 `extract_concepts.parse`：加英文→中文常量映射（`concept→CLASS_CONCEPT`、`fact→CLASS_FACT`），**保留中文值向后兼容**
- [x] 2.3 `judge_relations`：prompt 中 `node_class="概念"|"事实"` 字面值改为 `"concept"|"fact"`
- [x] 2.4 `judge_relations.parse`：加同样的英文→中文映射 + 中文值向后兼容
- [x] 2.5 确认**存储层 `node.node_class` 取值不变**（仍为中文常量），既有 `node_class` 读路径（载重过滤、事件边过滤、universe 判定）零改动

## 3. gen_aliases 去中文化

- [x] 3.1 `gen_aliases` 的 `USER_TEMPLATE` 示例 `["AAPL", "苹果公司", "苹果"]` 改为语言中立形态（不预设中文译名作示范）

## 4. 回答侧语言跟随增强

- [x] 4.1 `mcs_agent/loop.py`：`LANGUAGE_FOLLOW_PROMPT` 增加主动对齐——不确定用户语言时先据用户消息判断再作答（在原被动转述基础上）

## 5. 测试

- [x] 5.1 **integration**（真实 LLM，无 key 时 skip）：英文 ingest 含 `Apple`/`Tesla`/`Google` 等知名实体的文本，断言落图对应节点 `name`/`content` 为英文、无 `苹果公司`/`特斯拉`/`谷歌` 中文译名节点
- [x] 5.2 **integration**：`decide_hub` 对纯英文节点群产出英文 `theme`（CJK 字符计数断言）
- [x] 5.3 单测：`extract_concepts.parse` / `judge_relations.parse` 英文枚举映射——`concept→CLASS_CONCEPT`、`fact→CLASS_FACT`
- [x] 5.4 单测：parse 向后兼容中文值——`概念`/`事实` 仍被接受并正确映射
- [x] 5.5 回归：中文语料 ingest 仍产中文节点、`golden_cage` 风格行为不变
- [x] 5.6 单测：`LANGUAGE_FOLLOW_PROMPT` 主动对齐措辞 + 仍追加在自定义 `system_prompt` 之后（扩展现有 `test_language_follow_appended_to_any_system_prompt`）

## 6. 文档同步

- [x] 6.1 `CLAUDE.md`：补 prompt 协议层 `node_class` 枚举为 `concept`/`fact`、parse 映射中文常量、**存储取值不变**的表述
- [x] 6.2 `README` / `docs/graph-model-design.md`：涉及 `node_class` 字面值 / prompt 语言的段落同步

## 7. 验证

- [x] 7.1 `openspec validate prompt-language-following --strict` 通过
- [x] 7.2 全量测试绿：`.venv\Scripts\python.exe -m pytest -q`
