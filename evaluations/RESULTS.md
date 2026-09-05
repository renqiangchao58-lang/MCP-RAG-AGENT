# SupportPilot 离线评估结果

> 使用内置 Hash Embeddings 与确定性路由，可离线复现，不消耗模型 API。

| 指标 | 结果 |
|---|---:|
| Retrieval Hit@K | 100.0% |
| Retrieval Top-1 Accuracy | 100.0% |
| Mean Reciprocal Rank | 1.000 |
| Average Citations | 1.25 |
| Route Accuracy | 100.0% |
| Total Cases | 20 |

## 失败案例

无。

## 复现命令

```powershell
.\.venv\Scripts\python.exe -m support_pilot.evaluation
```
