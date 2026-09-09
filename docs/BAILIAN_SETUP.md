# 百炼 API + 本地知识库

使用本机 Python 运行应用，不需要 Docker、云服务器或本地大模型。
对话使用百炼 `qwen-plus`，Embedding 使用 `text-embedding-v4`。
重排沿用本地规则；原文档及数据库继续保存在本机。

## 1. 填写密钥

在阿里云百炼控制台开通模型服务，创建华北 2（北京）地域的 API Key。
将密钥仅填写到项目根目录 `.env` 的 `OPENAI_API_KEY=` 后，不要发到聊天或提交 Git。
`.env` 已被 Git 忽略；可分享的无密钥配置模板是 `.env.bailian.example`。

```dotenv
MODEL_PROVIDER=openai
OPENAI_API_KEY=填写你自己的百炼密钥
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
CHAT_MODEL=qwen-plus
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_BATCH_SIZE=10
QDRANT_PATH=.data/qdrant-bailian-v4
QDRANT_COLLECTION=support_knowledge_bailian_v4
```

本配置采用官方仍支持的北京公共域名。如控制台提供业务空间专属地址，
可将 BASE_URL 换成控制台显示的 OpenAI 兼容地址（以 `/compatible-mode/v1` 结尾）。
密钥和地址必须属于同一地域。两个模型需在该账号和地域可用。

官方参考：[创建密钥](https://help.aliyun.com/zh/model-studio/get-api-key)、
[对话接口](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)、
[向量接口](https://help.aliyun.com/zh/model-studio/text-embedding-synchronous-api)。

## 2. 测试接口

在项目目录执行：

```powershell
.\.venv\Scripts\python.exe -m support_pilot.check_cloud --config-only
.\.venv\Scripts\python.exe -m support_pilot.check_cloud
```

第一条仅检查配置，不联网。第二条会发送两条测试文本做向量化，再发送一条对话测试，
会产生少量 API 用量；它不读取原文档、不打开或修改数据库。
必须同时出现 `PASS Embedding` 和 `PASS 对话`，才说明两个真实接口均已连通。
缺密钥返回退出码 2；接口失败返回 1；成功返回 0。

## 3. 启动应用

若之前已运行旧版 API，先停止该项目的旧 API 进程，再执行：

```powershell
.\scripts\start_all.ps1
```

启动器会拒绝复用模型配置不同的旧 API。仅编辑 `.env` 不会改变已经运行的进程。
打开 `http://127.0.0.1:8501`。`http://127.0.0.1:8000/health` 应显示：

- `model_mode`: `llm`
- `embedding_provider`: `openai`
- `embedding_model`: `text-embedding-v4`
- `qdrant_collection`: `support_knowledge_bailian_v4`

健康接口仅说明配置和服务状态，不替代第 2 步的双接口实测。
新索引不存在时，API 首次启动会自动读取 `data/knowledge` 中支持的文档，
切分并发送文本到百炼 Embedding。大批量入库可能超过启动器等待时限，
此时应缩小初始文档集或单独启动 API 并观察日志。

## 数据位置与外发范围

| 内容 | 位置 / 接收方 |
|---|---|
| PDF / Markdown / TXT 原文件 | 本机 `data/knowledge` |
| 新向量、文本片段与来源信息 | 本机 `.data/qdrant-bailian-v4` |
| 原 Hash 演示索引 | 原样保留在本机 `.data/qdrant` |
| 订单、客户、工单 | 本机 `.data/support.db` |
| 入库片段、检索问题 | 百炼 Embedding API |
| 问题、选中片段、业务查询结果、部分历史用户消息 | 百炼对话 API |

数据库留本地并不意味着文本不外发。此配置不会调用外部重排 API。
API 处理与日志保留规则以服务商条款、所选地域及账号配置为准。

## 接入细节

`text-embedding-v4` 每批最多 10 条文本；客户端发送原始字符串和 `float` 向量格式，
避免发送 OpenAI token ID。文档继续按现有规则切分为约 700 字符的片段。
更换 Embedding 模型时应使用新的索引路径及集合，并重新向量化，不能混用旧向量。
本页的同平台配置共用地址和密钥。跨平台时可通过 `EMBEDDING_API_KEY` 与
`EMBEDDING_BASE_URL` 指定独立接口，详见 [DeepSeek 组合方案](DEEPSEEK_SETUP.md)。

需要回到离线演示时，在 `.env` 中把 `MODEL_PROVIDER=offline`、
`EMBEDDING_PROVIDER=hash`、`QDRANT_PATH=.data/qdrant`、
`QDRANT_COLLECTION=support_knowledge`，并重启 API。
