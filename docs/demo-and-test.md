# Coordexa 演示与测试说明

## 演示链路

### 1. RAG 门控

输入“你好”。预期识别为 `greeting`，由 `general` 处理，`knowledge_used=false`。

### 2. 技术知识增强

输入“登录一直报 401，应该怎么排查？”。预期提取错误码 `401`，路由至 `technical`，并使用“技术故障排查”知识。

### 3. 跨领域协同

输入“登录一直报 401，而且刚才还被重复扣款了”。预期同时出现 `technical` 与 `billing`，一个作为主 Agent，另一个作为辅助 Agent。主次允许受意图识别结果影响，但两个领域都必须被覆盖。

## 测试层次

1. 静态检查：Python 语法、前端构建、Compose 配置。
2. 单元测试：路由、工具白名单、参数校验、RAG 门控。
3. 冒烟测试：健康检查、知识库、Skills、对话、Monitor、评测接口。
4. 标注集评测：意图、路由、协同、实体和 RAG 门控。
5. 检索评测：Hit@3、MRR。
6. 质量评测：LLM-as-Judge 四维评分及 Judge 成功率。

## 一键复核

启动全栈后，先运行不调用外部模型的健康验收：

```powershell
python scripts/verify_stack.py
```

需要同时重跑容器测试时：

```powershell
python scripts/verify_stack.py --run-tests
```

需要生成新的在线指标报告时：

```powershell
python scripts/run_benchmark.py --base-url http://localhost:8200 --output artifacts/benchmark-report.json
```

## 对外引用规则

- 必须写明测试集规模，例如“在18条人工标注的项目验收问题上”。
- 内部验收集结果不能表述为行业通用准确率。
- Judge 成功率低于95%时，不对外引用回答质量均分。
- 检索指标仅针对仓库内置的6篇企业运营知识文档。
- 每次改动后重新生成报告，不手工修改指标。
- 单轮小样本100%只可表述为“本轮项目内验收集结果”，同时保留样本量与运行波动说明。
