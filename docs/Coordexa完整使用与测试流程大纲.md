# Coordexa 完整使用与测试流程大纲

本大纲按 1～16 节组织 Coordexa 的安装、使用、测试和验收流程。所有命令均在项目根目录执行，端口、服务名和验收口径以当前仓库实现为准。

## 1. 项目结构

目标：先建立前端、后端、数据组件、评测和交付脚本的整体认识。

- `backend/`：FastAPI、Agent 编排、RAG、记忆、Skills、监控与评测。
- `frontend/`：Vue 工作台与 Nginx 反向代理。
- `evaluation/`：人工标注验收集和历史报告。
- `scripts/`：Windows 启停、全栈验收和在线 benchmark。
- `docker-compose.yml`：Backend、Frontend、Redis、ChromaDB、Prometheus 五服务编排。

验收证据：能够说明一次 `/chat` 请求如何经过记忆、意图识别、RAG 门控、主辅 Agent、Skills、工具和监控。

## 2. 环境准备

目标：准备 Docker Desktop、Python 命令和模型服务配置。

1. 确认 Docker Desktop 已启动。
2. 在项目根目录复制 `.env.example` 为 `.env`。
3. 填写 `ANTHROPIC_API_KEY`，使用兼容服务时同时填写 `ANTHROPIC_BASE_URL` 和 `ANTHROPIC_MODEL`。
4. 不把 `.env`、密钥或真实业务数据提交到版本库或发布包。

当前默认端口：Frontend `8080`、Backend `8200`、Prometheus `9190`。Redis 和 ChromaDB 默认只在 Compose 内部网络访问。

验收证据：`docker version`、`docker compose version` 正常，`.env` 不再包含示例密钥。

## 3. Docker Compose 全栈部署

目标：用推荐方式启动完整演示环境。

```powershell
powershell -ExecutionPolicy Bypass -File scripts/coordexa.ps1 start
```

脚本会构建服务、等待健康检查并执行 10 项无模型调用的全栈验收。常用地址：

- 工作台：`http://localhost:8080`
- Swagger：`http://localhost:8200/docs`
- Backend 健康检查：`http://localhost:8200/health`
- 前端代理健康检查：`http://localhost:8080/api/health`
- Prometheus：`http://localhost:9190`

验收证据：五个服务运行，`scripts/verify_stack.py` 显示 `10/10 checks passed`。

## 4. Docker Run 开发模式

目标：理解开发模式与全栈模式的区别，不作为首轮验收主路径。

当前项目优先使用 Compose。后续如需代码热更新，可单独启用 Dockerfile 的 `development` target，并按运行平台配置卷挂载路径。

验收证据：首轮跳过本节的运行操作，并记录“Compose 是当前唯一正式演示入口”。

## 5. Swagger 和接口总览

目标：按固定顺序认识 API，不立即进行高成本评测。

推荐顺序：

1. `GET /health`
2. `POST /chat`
3. `GET /knowledge/stats`
4. `POST /knowledge/upload`
5. `POST /search`
6. `GET /monitor`
7. `GET /skills`
8. `POST /skills/reload`
9. `GET /metrics`
10. `POST /eval/run`

Coordexa 还增加了 `GET /trace/tools` 和 `GET /trace/tool/{request_id}`，用于核验实际工具调用轨迹。

验收证据：Swagger 中接口与当前代码一致，错误参数能返回 4xx，而不是进入模型调用。

## 6. 使用项目

目标：验证主链路和四种代表性场景。

1. 寒暄：“你好”——应跳过 RAG。
2. 技术：“登录一直报 401”——应路由 Technical 并提取错误码。
3. 账务：“这个月重复扣款了，我要退款”——应路由 Billing。
4. 复合：“登录报 401，而且还重复扣款”——应出现主 Agent 与辅助 Agent。
5. 多轮：固定 `user_id + conv_id`，验证订单号或偏好能被后续轮次使用。

优先在 `http://localhost:8080` 工作台演示，再用 Swagger 复核结构化返回字段。

验收证据：保存每类用例的意图、主辅 Agent、实体、`knowledge_used`、`request_id` 和延迟。

## 7. 知识库使用

目标：验证默认文档、幂等导入、中文混合检索和文件校验。

1. 查看 `/knowledge/stats`，首次启动的默认业务知识库应有 6 个片段。
2. 首次上传 `backend/data/demo_docs/sample_knowledge.json`，新增 6 个不同的 Coordexa 项目说明片段，总数应变为 12。
3. 再次上传同一个 `sample_knowledge.json`，确认固定 ID upsert 生效，总数仍保持 12。
4. 分别检索退款、积分、账户安全问题，记录标题排序、词法分数、向量分数和混合分数。
5. 验证 `.txt/.md/.json` 可上传，其他扩展名、空文档、错误 JSON 和超大文件被拒绝。

验收证据：6 条检索验收集的 Hit@3、MRR 和逐条排名报告。

## 8. ChromaDB 在项目中的用途

目标：理解三个 collection 的职责边界。

- `knowledge_base`：业务知识片段。
- `episodic`：压缩后的历史会话摘要。
- `user_profile`：用户偏好和关键实体，固定 ID 幂等更新。

验收证据：能解释知识事实、跨会话记忆和用户画像为什么不能放在同一个 collection 中。

## 9. 在 Docker 中查看 ChromaDB 内容

目标：通过 Compose 服务名检查数据，不直接修改底层持久化文件。

当前 ChromaDB 没有暴露宿主机端口，因此原指南的 `localhost:8001` 不适用。统一使用：

```powershell
docker compose exec chromadb curl -s http://localhost:8000/api/v1/heartbeat
docker compose exec backend python <检查脚本>
```

依次查看 collection 列表、`knowledge_base`、`user_profile`、`episodic` 和 Docker volume。清空 collection 或 volume 属于破坏性操作，不纳入常规验收。

验收证据：记录三个 collection 的条数和一条脱敏样例。

## 10. Redis 工作记忆查看

目标：验证 Redis 工作记忆 key、顺序和 TTL。

```powershell
docker compose exec redis redis-cli -a coordexa_dev_password KEYS "wm:*"
docker compose exec redis redis-cli -a coordexa_dev_password TTL "wm:<user_id>:<conv_id>"
docker compose exec redis redis-cli -a coordexa_dev_password LRANGE "wm:<user_id>:<conv_id>" 0 -1
```

如果 `.env` 修改了 `REDIS_PASSWORD`，命令必须使用相同密码。生产环境不应使用 `KEYS *` 扫描大库。

验收证据：同一会话存在消息列表，TTL 约为 24 小时。

## 11. 查看工作记忆压缩内容

目标：验证 `COMPRESS_AT = 15` 后的三级记忆迁移。

1. 使用专用测试用户与固定会话发送足量消息。
2. 检查 Redis `summary:{user_id}:{conv_id}`。
3. 检查工作记忆只保留最近消息。
4. 检查 ChromaDB `episodic` 出现对应摘要。
5. 再开启一个新会话，验证跨会话相关历史检索。

该步骤会产生多次真实模型调用，应单独执行并记录费用、耗时和失败回退。

验收证据：Redis summary、剩余消息数、episodic 文档和跨会话回复四项一致。

## 12. Monitor 在线监控

目标：核验 Agent、工具、告警和 Prometheus 抓取状态。

1. 调用 `GET /monitor`。
2. 查看 Agent 成功率、平均延迟、路由分数和降权。
3. 查看工具成功率、熔断状态和完成请求统计。
4. 访问 `http://localhost:9190/targets`，确认 Backend 与 Prometheus 均为 `UP`。
5. 对照前端告警文本和 API 的 `message` 字段。

验收证据：保存调用前后监控快照；延迟告警作为真实边界保留，不人为删除。

## 13. 运行端到端评测

目标：把确定性验收、在线 benchmark 和 LLM-as-Judge 分开。

顺序：

1. 容器单元测试：`scripts/coordexa.ps1 test`。
2. 无模型全栈验收：`scripts/coordexa.ps1 verify`。
3. 12 条对话 + 6 条检索：`scripts/coordexa.ps1 benchmark`。
4. 最后单独调用 `/eval/run`，观察 Judge 成功率。

只有成功解析的 Judge 样本才计算回答质量。Judge 成功率不足 95% 时，不在对外材料中引用质量均分。单轮 100% 必须标注“项目内验收集、样本量和测试时间”，并同时说明多轮运行波动。

验收证据：测试通过数、benchmark JSON、Judge 成功/失败数、日志中的 fallback 次数。

## 14. 停止、重启和清理

目标：掌握可恢复操作和破坏性操作的边界。

```powershell
powershell -ExecutionPolicy Bypass -File scripts/coordexa.ps1 stop
powershell -ExecutionPolicy Bypass -File scripts/coordexa.ps1 restart
powershell -ExecutionPolicy Bypass -File scripts/coordexa.ps1 status
```

`docker compose down` 会删除容器但保留数据卷；`docker compose down -v` 会删除 Redis、ChromaDB、Backend 和 Prometheus 数据卷，不纳入普通测试流程，执行前必须再次确认。

验收证据：restart 后仍能通过 10 项检查，知识库数据仍存在。

## 15. 常见问题

目标：按现象形成固定排查顺序。

1. 启动失败：检查 `.env`、Docker Desktop、Backend 日志。
2. 临时 502：等待 Backend 健康，不立即判为代码失败。
3. ChromaDB 失败：检查 `chromadb` 健康和 Backend 内部连接。
4. Redis 认证失败：核对 `.env` 与 Compose 密码。
5. 检索为空：检查知识库片段数和上传格式。
6. 画像/摘要缺失：检查异步更新、消息阈值和模型空响应日志。
7. Judge 无分数：记录 `judge_failed`，不填充或伪造分数。

验收证据：每类故障保留“现象—定位命令—原因—恢复动作”四列记录。

## 16. 推荐验证流程

最终执行顺序：

1. 配置 `.env`。
2. 启动五服务并完成 10 项健康验收。
3. 查看 Swagger 与前端工作台。
4. 跑寒暄、技术、账务、复合和多轮对话。
5. 查看知识库统计并验证幂等导入。
6. 执行 6 条检索验收。
7. 检查 ChromaDB 三个 collection。
8. 检查 Redis 工作记忆。
9. 触发并检查工作记忆压缩。
10. 检查 Monitor、工具轨迹和 Prometheus。
11. 运行 32 项容器测试。
12. 运行 12 条对话 + 6 条检索 benchmark。
13. 单独运行 LLM-as-Judge 并记录成功率。
14. 执行 restart 持久化复核。
15. 汇总截图、JSON、日志与可对外引用的项目指标。

完成标准：所有对外陈述均能追溯到代码、接口返回、测试报告或日志；未接入的真实订单、支付、物流、CRM、工单、鉴权和 RBAC 继续明确标记为未实现。
