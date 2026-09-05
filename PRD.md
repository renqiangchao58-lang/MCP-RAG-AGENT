# SupportPilot v0.1 产品需求

## 目标

面向客服和售后工程师，跑通“查政策 → 查订单 → 判断资格 → 用户确认 → 创建工单”的完整闭环。项目用于展示 LangChain RAG、LangGraph 工作流、MCP 工具调用和人工审批。

## P0 功能

- 导入 PDF、Markdown、TXT 并重建 Qdrant 索引。
- 知识问答返回文件名、页码、片段和相关性分数。
- Agent 自动路由至知识库、业务系统或组合路径。
- MCP Server 提供 `get_order`、`get_customer`、`list_tickets`、`create_ticket`。
- 写操作必须先生成待确认动作；确认接口是唯一执行入口。
- 支持会话内订单号指代和自然语言确认/取消。
- Web UI 展示流式回答、引用、工具参数、结果与确认按钮。
- 提供 20 条检索/路由评测案例、自动化测试和 Docker Compose。

## 不在 v0.1 范围

多 Agent、用户权限、多租户、真实 CRM/Jira、OCR、混合检索、Reranker、长期记忆和 Kubernetes。

## 完成定义

订单 A1024 的端到端演示可稳定完成；确认前工单数不变，确认后写入一条工单；Top-5 检索命中率不低于 85%；无依据时不编造政策。

