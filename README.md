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

## 版本更新记录

> 版本口径：v1.0 是可运行的多 Agent 原型基线；v1.1 是面向技术面追问的工程加固；v2.0 是在 v1.1 基础上针对真实误判样本的意图规则与评测扩展。本节只记录已经落到代码、测试或基准报告中的内容。

### v1.0.0｜基础架构与核心功能

**实现内容**

- 搭建 FastAPI + Vue 的可运行全栈入口，支持通用、技术、账单、人工升级四类 Agent 协同。
- 引入“意图识别 → RAG 检索 → Agent 路由 → Skill → 白名单 Tool → 结果合并”的基础链路。
- 接入 ChromaDB 知识库，支持向量召回、中文字符 n-gram 词法排序、去重和重排。
- 建立 Redis 工作记忆、ChromaDB 历史摘要和用户画像三层记忆结构。
- 支持 Markdown/JSON/TXT Skill 加载，完成工具参数校验、超时和基础调用轨迹记录。
- 提供基准样本、RAG 门控、实体提取和检索 Hit@3/MRR 评测入口。

**已知限制**

- 早期版本更偏向演示闭环，Token、上下文预算、空响应降级和动态检索的可观测性不足。
- 不连接真实订单、支付、物流或工单系统，不能把演示结果解释为生产 SLA。

### v1.1.0｜工程稳定性与可观测性改进

**修复与强化**

- 新增透明 LLM usage 追踪：记录真实 input/output/total tokens，按请求和组件拆分，拒绝用字符数估算冒充实测。
- 增加动态上下文预算、动态 `top-k`、长上下文截断保护，并保留截断原因和检索元数据。
- 为空响应、工具超时、工具异常增加一次重试、fallback、熔断和 `degraded` 标记，避免单个 Agent 让整条链路失效。
- 补齐 Skill、Tool、Agent 间结构化 JSON 传输约定，工具结果统一携带成功/降级/错误信息。
- 知识来源增加 `source_type`、文件/API provenance，方便回答溯源和面试追问“数据库来源是什么”。
- 扩展自动化测试与在线 v2 扩展集：48 条对话 + 24 条检索请求，覆盖路由、RAG 门控、实体提取、请求成功率、P50/P95 和真实 usage。

**验证结果**

- Docker 测试镜像中的 80 项确定性测试通过。
- v1.1 基线报告保存在 `evaluation/results/coordexa_v2_benchmark_2026-09-20.json`，报告中的指标均带样本量和测试口径。

### v2.0.0｜意图识别规则与评测扩展

**变更内容**

- 针对“我的订单什么时候到？”被判为 `query`：补充“预计到达、预计送达、订单/快递多久到、订单/快递未收到”等具有物流上下文的模板和规则。
- 针对“我的账号疑似被盗，怎么修改密码？”被判为 `refund`：补充“账号/账户安全、疑似被盗、异常登录、密码被改、两步验证”等账户安全模板和规则。
- 对物流和账户安全增加高区分度显式规则优先级：命中强规则时覆盖宽泛的 LLM/Embedding 结果，避免安全类意图误路由。
- 在 LLM 提示模板中明确“订单/账号/密码”等词不能单独触发退款意图，要求优先判断物流或账户安全语义。
- 新增两类误判的回归测试，并用同一份 v2 扩展集重新跑前后对比，最终结果以 `evaluation/results/coordexa_v2_benchmark_2026-09-20-intent-fix-final.json` 为准。

**验证结果**

- 48/48 对话请求、24/24 检索请求成功；意图、主 Agent、Agent 覆盖、RAG 门控、实体用例均为 100%，检索 Hit@3=100%、MRR=1.0000。
- 两条已复现误判在 4 轮重复中全部修正为 `logistics` 与 `account_security`；端到端平均 26.62 秒、P50 26.33 秒、P95 54.39 秒。该结果限定于项目内 v2 验收集，不代表生产准确率。
- 若在线模型仍产生新误判，优先通过新增标注模板和回归样本迭代，不直接修改历史报告数据。

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

### 基础链路

```text
你好
登录一直报 401，应该怎么排查？
```

这两条请求分别用于验证 RAG 门控和技术知识增强：第一条应跳过知识库，第二条应提取错误码 `401` 并路由到 `technical` Agent。

### 多 Agent 协同场景

以下请求用于观察一个用户请求同时命中多个业务域时的主 Agent、辅助 Agent、Skills 和工具调用。主/辅顺序由当前意图识别结果决定，但预期覆盖的业务域应保持一致。

#### 技术故障 + 重复扣款

```text
登录一直报 401，而且刚才还被重复扣款 50 元，请先帮我排查登录问题，再核对这笔扣款。
```

预期覆盖 `technical_login` 与 `payment_issue`，同时触发技术排障和账单核验相关知识/工具。

#### 物流异常 + 退款咨询

```text
订单已经发货七天了，物流一直没有更新，如果确认丢件我想申请退款，应该怎么处理？
```

预期覆盖物流查询和退款处理两个业务域；该场景可用于检查物流检索、退款规则以及结果合并是否都被保留。

#### 账户安全 + 登录故障

```text
我的账号疑似被盗，刚才出现了异常登录，现在又无法登录，请先保护账号并告诉我下一步怎么处理。
```

预期识别账户安全和登录故障相关信号，检查安全类规则是否优先于宽泛的账单/账户分类，并观察是否触发人工升级建议。

#### 订单状态 + 发票问题

```text
订单还没有发货，我还需要把发票抬头改成公司名称，这两个问题可以一起处理吗？
```

预期覆盖订单状态和发票两个业务域，检查不同 Skills 的输入输出能否通过结构化结果交给主 Agent 合并。

#### 需要人工介入的复杂请求

```text
登录问题、重复扣款和退款都没有解决，请保留前面的处理记录并转人工客服继续跟进。
```

预期触发 `human_handoff` 边界，验证工具调用失败或多 Agent 结果无法闭环时的升级路径、会话记忆和降级标记。

详细验收步骤见 `docs/demo-and-test.md`。这些场景用于演示当前原型的路由和协同能力，不代表已经接入真实订单、支付、物流或工单系统。

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

Token 观测也提供一键聚合入口：打开 Swagger 的 `GET /trace/llm/overview`，即可查看最近记录的总调用数、输入/输出/总 Token、usage 可用率、按组件和按请求聚合；前端工作台“对话”侧栏中的“Token 用量”卡片会自动读取同一接口，发送消息后点击“刷新”即可查看。单次请求仍可用 `GET /trace/llm/{request_id}` 深入查看。

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
