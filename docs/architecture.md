# Coordexa 架构与能力边界

## 主链路

```text
Vue 工作台
  -> POST /chat
  -> Redis / ChromaDB 读取对话上下文
  -> LLM + 本地 n-gram + 规则融合意图识别
  -> 根据意图决定是否执行知识检索
  -> ChromaDB 多查询召回、中文词面/向量混合排序与可选 LLM 重排
  -> 主 Agent + 辅助 Agent 结构化路由
  -> Skills 与工具白名单注入
  -> Agent 执行与结果合并
  -> 写回工作记忆并异步更新用户画像
  -> Monitor、工具轨迹与评测
```

## 角色映射

| 代码节点 | 产品角色 | 当前职责 |
|---|---|---|
| `GeneralAgent` | 运营协调 Agent | 通用咨询、订单物流、信息澄清和跨域协调 |
| `TechnicalAgent` | 技术可靠性 Agent | 登录、错误码、崩溃和配置排查 |
| `BillingAgent` | 收入与合规 Agent | 退款、发票、支付异常和账务核验 |
| `EscalationAgent` | 运营升级通道 | 人工交接摘要和高风险请求升级 |

## 能力边界

- 当前是可运行的工程原型，不直接连接真实订单、支付、物流或工单系统。
- Escalation 节点生成交接信息，不代表已经创建真实工单。
- 知识库检索结果只来自导入的演示文档。
- Monitor 统计进程内运行数据，不等同于完整生产可观测平台。
- LLM-as-Judge 是辅助评测方法，结果受 Judge 模型和解析成功率影响。
- `mcp/tool_manager.py` 是内部工具管理抽象，不等同于完整 MCP 协议实现。
