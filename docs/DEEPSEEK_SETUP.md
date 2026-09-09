# DeepSeek 对话 + 百炼 Embedding + 本地数据库

已有 DeepSeek 开放平台 API 余额时，可以直接用于本项目的对话请求。
DeepSeek 对话与 Embedding 分别配置，不需要为对话再购买百炼服务。
当前 Embedding 继续选择百炼 `text-embedding-v4`；其用量由百炼单独计费。

## 本机配置

在项目根目录 `.env` 中填写密钥，其他项已配置好：

```dotenv
# DeepSeek 官方 API，仅用于对话
MODEL_PROVIDER=openai
OPENAI_API_KEY=你的DeepSeek密钥
OPENAI_BASE_URL=https://api.deepseek.com
CHAT_MODEL=deepseek-v4-flash

# 百炼 API，仅用于向量化；密钥需与接口地域一致
EMBEDDING_PROVIDER=openai
EMBEDDING_API_KEY=你的百炼密钥
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_BATCH_SIZE=10
```

`OPENAI_API_KEY` 是项目沿用的兼容协议配置名，这里填 DeepSeek 的密钥，
不需要 OpenAI 账号。`.env` 已被 Git 忽略，密钥不要发到聊天或提交仓库。
可分享的无密钥模板为 `.env.deepseek.example`。

官方说明：[DeepSeek API](https://api-docs.deepseek.com/zh-cn/)、
[百炼 Embedding](https://help.aliyun.com/zh/model-studio/text-embedding-synchronous-api)。
对话模型名以账号当前可用列表为准；百炼北京地域仅是当前 Embedding 接口的选择，
不限制你所在的城市，也不影响 DeepSeek 的配置。

## 分步验证

只有 DeepSeek 密钥时，可以先测试对话，不要求填写百炼密钥：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m support_pilot.check_cloud --only chat
```

百炼密钥填好后，单独测试 Embedding 或测试两者：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m support_pilot.check_cloud --only embedding
.\.venv\Scripts\python.exe -X utf8 -m support_pilot.check_cloud
```

加 `--config-only` 仅检查配置，不发送网络请求。真实测试仅发送固定测试句子，
不读取知识库、不修改数据库，但会产生少量 API 用量。
对话测试成功不代表 Embedding 成功；两者分别出现 PASS 后再启动完整云端 RAG。

## 启动与数据流

停止本项目的旧 API 后，在项目目录执行 `.\scripts\start_all.ps1`，
打开 `http://127.0.0.1:8501`。修改 `.env` 不会更新已经运行的进程。
新索引为空时首次启动会自动切分 `data/knowledge` 中的文档并发送给百炼向量化。

- 原文件仍在本机 `data/knowledge`。
- 向量及片段在本机 `.data/qdrant-bailian-v4`，原 Hash 索引保持在 `.data/qdrant`。
- 业务数据在本机 `.data/support.db`。
- 入库片段和检索问题发送给百炼 Embedding。
- 问题、选中片段、业务查询结果、部分历史用户消息发送给 DeepSeek 对话接口。
- 重排沿用本地规则，没有外部重排调用。

## 配置兼容

`EMBEDDING_API_KEY` 和 `EMBEDDING_BASE_URL` 均留空时，保持旧行为：
Embedding 与对话共用 `OPENAI_API_KEY` / `OPENAI_BASE_URL`。
只要设置了任意一个独立 Embedding 字段，就必须成对填写，
避免把 DeepSeek 密钥发送给另一家服务商。

如果暂时只做演示，可将 `EMBEDDING_PROVIDER=hash`、`QDRANT_PATH=.data/qdrant`、
`QDRANT_COLLECTION=support_knowledge` 后重启，使用本地 Hash 向量；
此时无需百炼密钥，但不具有正式语义向量模型的检索能力。
