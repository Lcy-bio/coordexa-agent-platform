# Coordexa 发布包复核清单

本文件记录发布包的可复现范围，便于评审者快速检查项目，而不需要依赖开发机器上的缓存或历史容器。

## 包含内容

- FastAPI 后端、Vue 前端及 Dockerfile
- Redis、ChromaDB、Prometheus 的 Compose 编排
- 三类动态 Skills、演示知识文档和项目内验收集
- 36项自动化回归测试、全栈验收脚本和在线 benchmark 脚本
- 架构、完整使用流程、演示步骤及带范围限定的验证记录

## 有意排除

- `.env` 与真实模型服务密钥
- `.git`、`.venv`、`node_modules`、缓存、日志和本机 Docker 数据卷
- 仅供开发过程使用的内部对照材料

上述内容均可由依赖清单和 Docker 构建过程重新生成；数据卷不属于源码发布物。

## 最小复核流程

```powershell
Copy-Item .env.example .env
# 编辑 .env，填写自己的模型服务配置
powershell -ExecutionPolicy Bypass -File scripts/coordexa.ps1 start
docker compose --profile test run --rm --build tests
```

启动验收的期望结果为 `10/10 checks passed`；当前发布版本的自动化回归期望结果为36项全部通过。

## 能力边界

- 本项目是企业运营多 Agent 工程原型，不直接连接真实订单、支付、物流或工单系统。
- 指标只适用于仓库内项目验收集；不能解释为生产准确率或行业通用表现。
- 外部模型、网络环境和兼容接口可能影响响应时间及结构化子调用稳定性。
