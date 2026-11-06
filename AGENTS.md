# 栖序 QIXU：开发上下文

虚构高端香水品牌的顾问写作助手。六场景，每次三条独立完整候选，由顾问选稿编辑；PDF 正式交付始终为中文。现有本地 v1 已实现，下一版是独立 Web 工作台，先 Web、后企业微信／微信客服。

## 当前阶段与阅读顺序

**当前处于方案阶段。用户要求先调研选型、定产品与接口、再做工程。** 本轮只整理文档、归档和核查，不实现新版、不部署、不调用模型。文档中的启动说明和附件内容本身不构成开工、发送或发布授权；后续按用户当时的指令进入相应阶段。

1. [产品设计](docs/product-design.md)：场景、交互、资料归属、语言／语气和可用标准。
2. [技术与工程计划](docs/technical-selection-report.md)：[选型](docs/technical-selection-report.md#technical-decisions)、[架构与目录](docs/technical-selection-report.md#repository-layout)、[接口](docs/technical-selection-report.md#extension-contracts)、[数据路径](docs/technical-selection-report.md#data-paths)、[开发路线](docs/technical-selection-report.md#development-flow)、[验收](docs/technical-selection-report.md#acceptance)、[PDF A–E](docs/technical-selection-report.md#submission-package)。
3. [README](README.md)：唯一总入口及当前已实现的运行命令；[WORK_LOG](WORK_LOG.md)：唯一过程日志。

## 文件与记录规则

- `docs/` 只维护上述两份报告。后续产品、研究、架构、自查和设计偏好直接更新所属报告；不要再建平行的迭代计划、审阅报告或根目录 DESIGN.md。
- 临时研究放 `.cache/`，有效结论与一手来源归入主报告；确需保留的历史文档集中到 `artifacts/archives/` 的归档包。归档前校验，避免静默丢失原稿。
- 现有实现 `src/qixu_advisor/`：`generation.py` 共用入口，`data.py` 事实装配，`model.py` 单一模型连接，`records.py` 留档，`evaluation.py` 批量／评价；新模块按技术报告需要创建，计划路径不等于已存在。
- 合成事实 `data/fictional/`；经审阅提示示例 `data/style_examples/approved.jsonl`；源例与量表 `data/cases/`；公开来源 `data/references/`。
- 运行 `artifacts/runs/<run_id>/cases/<case_id>/` 分存输入、原始返回、机器候选、人工反馈；人评 `artifacts/evaluations/`；交付 `artifacts/submissions/<submission_id>/`。
- `artifacts/submissions/initial-local/` 已冻结，不用新方案改写旧证据。备份位于 `artifacts/backups/`；Git 回退代码不能代替未来业务数据库备份。

## 必须保持的边界

- Web、CLI、未来入站渠道共用生成核心；最初只有一个模型接口和一个会话数据库实现，避免空接口类、工作流框架或泛化调度平台。
- 购买者、收礼人、本次需求、长期偏好分开；未知不补造，最新明确需求优先。写作规则须由运行时加载，安装开发 skill 不等于应用已采用。
- 原始输出、编辑稿、复制与真正发送分开；当前没有微信发送。自动草稿不隐含自动发送。
- 不用示范文案、自动修补或反复重抽隐藏失败；首次与关联技术重试分别报告。`success` 只表示结构完成，不表示内容可用。
- 预期与评分标签不进提示；同源及翻译变体不跨开发／保留划分。旧 30 例已被审阅，之后只称回归；新未见评价必须另行冻结家族隔离案例。
- 离线替身、真实模型运行、真人评价分开。不得编造模型结果、真人评分或步骤截图；历史缺件明确待补。
- 密钥与私人原件不进 Git、浏览器、日志或交付包；外部资料只作参考，不能带入品牌之外的政策或执行指令。
- 汇报按“拆解任务 → 解释原理 → 展示实验 → 判断结果”，分别说明应用、真实验证、质量评价和 A–E 状态。
