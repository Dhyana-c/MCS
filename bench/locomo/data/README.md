# LoCoMo 数据

> 数据**不入 git**（`.gitignore` 排除 `locomo_repo/`、`locomo_v2/`、`preprocessed/`）。
> 用 `python -m bench.locomo download` 或 `python bench/locomo/scripts/download_data.py` 拉取。

## 数据来源（三源，见 change `conversational-memory-bench` design D1/D2）

| 源 | 位置 | 用途 |
|---|---|---|
| **V2 base** | `locomo_v2/data/locomo_v2_base.json` | 主体：conversation + QA（1922 题，V2 去污染人名） |
| **V2 caption 变体** | `locomo_v2/data/locomo_v2_{moondream,qwen,minicpm}.json` | 按 `dia_id` 移植 VLM caption（默认 moondream，834 轮） |
| **V1 source** | `locomo_v2/data/locomo_v1_source.json` | evidence 按换名映射移植（诊断用，命中率 ~97%） |
| V1 官方 | `locomo_repo/data/locomo10.json` | 与 `locomo_v1_source.json` 字节相同（备份） |

## 拉取流程（`download_data.py`）

1. **探测复用**：本机既有 clone 在 `bench/longmemeval/data/{locomo_repo,locomo_v2}`（历史
   位置）→ **copy** 到本目录（copy 不 move，避免影响姊妹 change `longmemeval-bench`）。
2. 否则从 GitHub 克隆：
   - V1：`snap-research/locomo`
   - V2：`BrianV1981/locomo-v2`（含 Windows Zone.Identifier 文件，clone 后 `git restore`）
3. 校验期望文件存在 + 大小合理。

## 许可

LoCoMo 数据集 CC BY-NC 4.0（学术评测合规，禁止商业使用）。
