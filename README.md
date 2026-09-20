# Coordexa 企业运营多 Agent 协同平台

Coordexa 是基于通用客服 Agent 原型进行场景重构和工程化改造的企业运营协同项目。它面向订单履约、技术故障、账务异常和人工升级等请求，串联意图识别、知识检索、分层记忆、多 Agent 路由、动态 Skills、工具治理和质量评测。

本仓库只描述已经落入代码或已经通过测试的能力。任何准确率、F1、检索命中率和质量分数，都必须由本仓库测试脚本在指定数据集上生成，并在引用时同时标注样本量和测试范围。

## 当前实现

- FastAPI 统一入口与 Vue 运营工作台
- 细粒度意图识别、实体提取和可解释路由
- General、Technical、Billing、Escalation 四类运行节点
- `primary_agent + supporting_agents` 主辅 Agent 并行协同
- 意图门控 RAG、ChromaDB 知识库、查询改写与重排
- 中文字符 n-gram + 向量混合排序、知识片段幂等导入
- Redis 工作记忆、ChromaDB 历史摘要与用户画像
- Markdown/JSON/TXT Skills 加载与热更新
- 工具参数校验、缓存、超时、熔断、fallback 和调用轨迹
- Monitor 指标与 LLM-as-Judge 评测入口

这里的 `mcp/tool_manager.py` 是项目内部工具管理层，不宣称已经实现完整的 MCP 协议服务器。

## 快速启动

1. 复制 `.env.example` 为 `.env`，填写可用的模型服务配置。
2. 启动 Docker Desktop。
3. 在项目根目录执行：

```bash
docker compose up -d --build
```

访问地址：

- 工作台：http://localhost:8080
- API 文档：http://localhost:8200/docs
- 健康检查：http://localhost:8200/health
- Prometheus：http://localhost:9190

Windows 下也可以使用统一命令入口：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/coordexa.ps1 start
```

服务启动后执行不调用模型的全栈验收：

```bash
python scripts/verify_stack.py
```

## 推荐演示

```text
你好
登录一直报 401，应该怎么排查？
登录一直报 401，而且刚才还被重复扣款了
```

三条请求分别用于验证 RAG 跳过、技术知识增强和技术/账务主辅协同。详细验收步骤见 `docs/demo-and-test.md`。

## 架构概览

![Coordexa 总体架构](docs/assets/architecture/01-overall-architecture.svg)

完整架构与能力边界见 [`docs/architecture.md`](docs/architecture.md)，当前验证结果见 [`docs/verification-status.md`](docs/verification-status.md)，完整实操流程见 [`docs/Coordexa完整使用与测试流程大纲.md`](docs/Coordexa完整使用与测试流程大纲.md)。
v1.1 面试问题驱动的 Token、上下文、降级与稳定性验证见 [`docs/v1.1-interview-hardening.md`](docs/v1.1-interview-hardening.md)。

## 量化评测

先运行后端单元测试：

```bash
docker compose --profile test run --rm --build tests
```

已安装本地开发依赖时，也可以在项目根目录运行 `python -m pytest`。

启动服务后运行：

```bash
python scripts/run_benchmark.py --base-url http://localhost:8200 --output artifacts/benchmark-report.json
```

脚本会基于 `evaluation/fixtures/benchmark_cases.json` 计算：

- 意图识别准确率
- 主 Agent 路由准确率
- 多 Agent 协同命中率
- RAG 门控准确率
- 实体提取用例准确率
- 检索 Hit@3 与 MRR
- 请求成功率、P50/P95 延迟

LLM-as-Judge 质量评测需要显式增加 `--include-quality-eval`。Judge 失败的样本不会被当作有效的 0.5 分，报告会单独展示 Judge 成功率。

运行 v1.1 稳定性扩展集（48 条对话 + 24 条检索请求）：

```bash
python scripts/run_benchmark.py --base-url http://localhost:8200 --cases evaluation/fixtures/benchmark_cases_v2.json --output artifacts/benchmark-v2-report.json
```

单次 `/chat` 响应包含 `llm_usage`；也可以通过 `/trace/llm/{request_id}` 查看按组件拆分的真实 Token usage。

## 项目结构

```text
backend/                         FastAPI、Agent、RAG、记忆、监控与评测
frontend/                        Vue 运营工作台
evaluation/fixtures/             人工标注的项目验收集
scripts/run_benchmark.py         在线量化测试脚本
scripts/verify_stack.py          Docker 服务、接口和监控一键验收
scripts/coordexa.ps1              Windows 启停、测试与评测入口
docs/                            架构、演示和指标口径
docker-compose.yml               Python + Vue + Redis + ChromaDB + Prometheus
```

项目仅提供演示环境与工程验证能力，不连接真实订单、支付、物流或工单系统。

## 安全说明

- 仓库不包含 `.env` 或任何真实 API Key；首次运行必须从 `.env.example` 创建本地配置。
- 示例 Redis 密码仅用于本地演示，部署到共享环境前必须更换，并限制服务端口和网络访问。
- 不要向演示环境输入密码、验证码、完整密钥或真实支付凭证。
