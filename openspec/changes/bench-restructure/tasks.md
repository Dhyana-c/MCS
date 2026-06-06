## 1. 目录结构创建

- [ ] 1.1 创建顶层 `bench/` 目录
- [ ] 1.2 创建 `bench/multihop-rag/` 子目录及 `scripts/`、`reports/`、`config/` 子目录
- [ ] 1.3 创建 `bench/multihop-rag/outputs/` 目录并添加 `.gitkeep`
- [ ] 1.4 创建 `bench/multihop-rag/data/` 目录及数据下载说明 README
- [ ] 1.5 创建 `bench/hotpotqa/` 占位目录及 README
- [ ] 1.6 创建 `bench/README.md` 总体说明

## 2. 启动脚本迁移与创建

- [ ] 2.1 迁移 `_run_multihop_chat_200_whole.py` 到 `bench/multihop-rag/scripts/run_whole_doc.py`
- [ ] 2.2 创建 `bench/multihop-rag/scripts/run_baseline.py` 基线评测脚本
- [ ] 2.3 创建 `bench/multihop-rag/scripts/run_node_rerank.py` 节点级重排脚本
- [ ] 2.4 创建 `bench/multihop-rag/scripts/run_doc_rerank.py` 文档级重排脚本
- [ ] 2.5 创建 `bench/multihop-rag/scripts/run_dry_run.py` 成本估算脚本
- [ ] 2.6 删除项目根目录 `_run_multihop_chat_200_whole.py`

## 3. 文档迁移与整理

- [ ] 3.1 迁移 `mcs/bench/MULTIHOP_RAG.md` 到 `bench/multihop-rag/README.md`
- [ ] 3.2 迁移 `mcs/bench/MULTIHOP_RERANK_REPORT.md` 到 `bench/multihop-rag/reports/doc_rerank_experiment.md`
- [ ] 3.3 创建 `bench/multihop-rag/reports/index.md` 报告索引
- [ ] 3.4 更新 `mcs/bench/README.md` 说明代码保留在 mcs 包内，启动脚本在 bench/ 顶层

## 4. 输出文件清理

- [ ] 4.1 移动 `multihop_chat_200_v2.db` 到 `bench/multihop-rag/outputs/whole_doc/`
- [ ] 4.2 移动 `multihop_output_chat_200_v2/` 到 `bench/multihop-rag/outputs/whole_doc/`
- [ ] 4.3 移动 `multihop_output_chat_200_v2_noalias/` 到 `bench/multihop-rag/outputs/noalias/`
- [ ] 4.4 移动 `multihop_output_chat_200_v2_rerank/` 到 `bench/multihop-rag/outputs/node_rerank/`
- [ ] 4.5 移动 `multihop_output_100_32k_v2/` 到 `bench/multihop-rag/outputs/32k/`
- [ ] 4.6 移动其他 `multihop_*.db` 到 `bench/multihop-rag/outputs/` 或删除
- [ ] 4.7 移动 `multihop_chat_200_v2.decisions.log` 到 `bench/multihop-rag/outputs/whole_doc/`

## 5. 配置与 .gitignore

- [ ] 5.1 添加 `bench/*/outputs/` 到 `.gitignore`（保留 `.gitkeep`）
- [ ] 5.2 添加 `bench/*/data/*.json` 到 `.gitignore`（数据文件不提交）
- [ ] 5.3 创建 `bench/multihop-rag/config/default.json` 默认配置示例

## 6. 文档更新

- [ ] 6.1 更新 `CLAUDE.md` 中 bench 相关说明
- [ ] 6.2 更新 `mcs/bench/__init__.py` 导出说明（如有变更）
- [ ] 6.3 创建 `bench/multihop-rag/scripts/README.md` 脚本使用说明

## 7. 验证

- [ ] 7.1 运行 `bench/multihop-rag/scripts/run_dry_run.py` 验证路径正确
- [ ] 7.2 确认 `mcs.bench` 包仍可正常导入
- [ ] 7.3 确认所有输出文件已迁移，项目根目录无散落文件