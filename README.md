# 栖序 QIXU 香水顾问助手

Python + Streamlit 本地应用，覆盖生日节庆、产品推荐、购后关怀、沉睡唤醒、活动邀请、价格异议。每次显式提交生成三条独立完整的中文微信候选，顾问选稿、编辑、复制或弃用。品牌与业务资料全部虚构。

**当前正在完成下一版方案，尚未进入 Web／数据库／多语言工程。** 本页只提供阅读入口和现有 v1 的实际命令。

| 要了解什么 | 唯一阅读位置 |
| --- | --- |
| 做什么、界面与写作行为、什么算可用 | [产品设计](docs/product-design.md) |
| 调研选型、架构、目录、接口、开发顺序、验收与 PDF A–E | [技术与工程计划](docs/technical-selection-report.md) |
| Agent 的当前阶段和工作约束 | [AGENTS.md](AGENTS.md) |
| 实际过程、检查及缺件 | [WORK_LOG.md](WORK_LOG.md)；初版材料见[交付清单](artifacts/submissions/initial-local/submission-checklist.md) |
| 已替代的自查、迭代方案与调研原稿 | [集中归档包](artifacts/archives/planning-before-consolidation-20261106.zip)，内含原路径和 SHA 清单 |

后续结论直接归入两份主报告，过程追加同一日志，不再新增平行的设计／自查／迭代报告。归档可供追溯，日常阅读无需展开。

## 在 Windows 启动

在项目目录打开 PowerShell：

```powershell
./scripts/bootstrap.ps1
./.venv/Scripts/python.exe -m streamlit run src/qixu_advisor/app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

打开终端显示的本地地址，通常为 <http://127.0.0.1:8501>。首次安装需联网下载 Python 3.12 和 `uv.lock` 中锁定的依赖，要求已有 `uv`。项目环境用 Python 标准 venv 启动器，兼容本机对 uv 启动器的应用控制限制；不修改系统策略。

首次配置时复制 `.env.example` 为 `.env`，在本地填写 `DEEPSEEK_API_KEY`。默认模型 `deepseek-flash`，接口 `https://api.deepseek.com`，关闭思考，JSON 输出，温度 0.7，最多 1800 输出 token。环境变量优先于 `.env`。密钥不进入 Git、提示、日志、运行清单或提交包。

```powershell
./.venv/Scripts/python.exe -m qixu_advisor.cli check
```

`configured: true` 仅说明本地配置齐全，不代表余额充足或调用成功。HTTP 402 表示余额不足；修复账号后创建新运行，保留原失败记录。程序不自动重试或用示例文案填充失败。

## 使用与检查

顾问写作页选择场景，可选已有客户档案或开发例，也可直接输入新资料。购买者、收礼人、本次需求和长期偏好分开；聊天可以为空。活动必须选择具体活动，生日节庆必须填写缘由。生成后查看使用的事实，选一条编辑，保存处理记录，再用代码框右上角按钮复制。保存与复制不会发送微信。

```powershell
# 仅离线程序检查；使用替身的结果都在临时目录，不证明模型质量。
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m qixu_advisor.cli validate-data

# 真实 API：先运行六个开发诊断例，每例一次调用。
./.venv/Scripts/python.exe -m qixu_advisor.cli batch --split diagnostic --run-id diagnostic-v1

# 在观察诊断和必要修改后，冻结代码、提示、事实、案例、量表与配置。
./.venv/Scripts/python.exe -m qixu_advisor.cli freeze --freeze-id formal-v1
./.venv/Scripts/python.exe -m qixu_advisor.cli batch --split all --run-id formal-v1 --freeze-id formal-v1

# 严格八列、固定五十行；失败保留空输出，另附缺失清单。
./.venv/Scripts/python.exe -m qixu_advisor.cli export --run-id formal-v1 --output artifacts/submissions/formal-v1/outputs.csv
```

不要重复使用运行编号。确需技术重跑时用新的 `--run-id` 并指定 `--parent-run-id`；不能把多轮中最好的候选拼成首轮成绩。看过保留集结果后再调整方案，后续该集合只能称回归验证。冻结后修改代码、资料或参数需要重新冻结。

人工评价页由真实评价者逐条填写，默认全部“未评”。本项目选择主评审阅 150 条、第二位真人复核预抽 12 例；这是项目方法，并非 PDF 指定的人数要求。没有第二位时如实标单人评价，不用 AI 意见替代人工评分。

```powershell
./.venv/Scripts/python.exe -m qixu_advisor.cli summarize --evaluation-id eval-formal-v1 --run-id formal-v1 --rater 你的评价者标识
```

汇总固定区分开发／保留与六场景，未评和缺失保留在分母；没有人评时不判内容通过。评价修订追加保存，汇总读取同一评价者最新修订，原评分保留。CLI `rate` 支持导入真实评价者按 `HumanCaseRating` 格式填写的一例 JSON。

本轮正式首轮为 `formal-v1`（49/50 成功、147 条候选），唯一格式失败例 AFTER-105 的一次技术重试在 `formal-v1-technical-retry`。人评分别选择这两个运行、使用各自评价编号；首轮失败和补充重试成绩分开报告。最终交付表以 `row-provenance.json` 关联每条原稿，不能用重试成绩改写首轮成绩。

`scripts/prepare_submission.py` 和 `scripts/check_submission.py` 是初版历史辅助脚本，均硬编码 `initial-local/`；后者也会重写 verification.json，并非只读。它们只能在恢复副本中复现，不能对当前冻结包重跑。新版工程须先支持新 submission_id，并让只读检查与报告写入分开，再生成新材料；本轮不改脚本。

更改源码后请重启 Streamlit，使已导入模块更新。`scripts/capture_*.py` 和 `review_saved_run.py` 是本轮验证辅助脚本；后者明确加载已有真实结果，只测试编辑保存，不是正式入口或新模型生成。

## 保存与恢复

目录及数据职责统一见[技术报告](docs/technical-selection-report.md#data-paths)。原始运行、人评和 `initial-local` 提交证据不作为缓存清理；本轮文档整理没有改变它们。新版本完成后另建提交目录。

初版恢复标签为 `qixu-v1-review-baseline-20261106`（77b5789），本地完整备份在 `artifacts/backups/20261106-pre-iteration/`，见[恢复说明](artifacts/backups/20261106-pre-iteration/RESTORE.md)。当前文档归档基线为 7523aee。先在新目录检视旧版，避免覆盖后来修改；密钥不在备份中。

规则检查不能证明文案可用。既有 50 例已被审阅，后续只作回归；真人评分和历史 AI 步骤截图仍待补。最新方案与当前材料状态统一见[技术报告 A–E](docs/technical-selection-report.md#submission-package)。
