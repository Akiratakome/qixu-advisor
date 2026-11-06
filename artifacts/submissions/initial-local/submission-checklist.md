# 栖序 QIXU · 本地初版交付索引

**本地应用和五十例真实输出已完成；完整 assignment 仍缺真人评价及 AI 对话截图。** 更换本地凭据后完成真实验证：首轮 49/50 成功、147 条候选；唯一格式失败例做一次关联技术重试后，最终八列表格包含 50 例、150 条真实候选。首轮表格和统计独立保留；真人评分仍为 0。

| 项目 | 本轮材料 | 状态与待补 |
|---|---|---|
| 本地应用 | 根目录 README、源码、锁定依赖；真实浏览器截图 | 六场景输入、生成核心、选稿编辑、批量、记录和评价入口已实现；离线检查及真实生成已验证 |
| A. 过程 | [工作日志表](work-log.csv)，根目录 WORK_LOG.md | 开发过程已记录；历史及本轮 AI 对话截图待补，应用截图不替代聊天截图 |
| B. 方法 | [methodology.md](methodology.md)，[随包测试资料](evidence/dataset/cases/manifest.json) | 工具、测试集、预期、量表和限制已说明；预期仍待真人审阅 |
| C. 五十例输出 | [outputs.csv](outputs.csv)，[状态](outputs.status.json)，[逐行来源](row-provenance.json) | 完整 50 例／150 条真实候选；AFTER-105 来自唯一技术重试，另外49例来自首轮；[首轮原表](outputs-first-attempt.csv)另存 |
| D. 评价 | [evaluation-report.md](evaluation-report.md)，[AI辅助审阅](evidence/ai-formal-review.md)，待评界面截图 | 实际模型运行、工程验证和 AI 辅助问题清单已报告；逐条真人评分及完成评价的截图待补 |
| E. 缺陷与下一步 | [defects-and-next-steps.md](defects-and-next-steps.md)，真实数据／界面／诊断前后对照 | 已记录工程修正与单项 JSON 格式实验；没有真人评分支持的内容质量提升结论 |
| 架构加分项 | [architecture.svg](architecture.svg) | 与当前本地实现对应 |
| 版本与完整性 | [versions.json](versions.json)，[verification.json](verification.json) | 代码、数据、提示、依赖、运行与证据可核对 |

应用截图在 `screenshots/application/`；`screenshots/evaluation/formal-awaiting-human.png` 是已有真实输出但全部待评价的状态，不能认作已经评分。`awaiting-evaluation.png` 是更早的失败阶段截图。AI 对话截图在 `screenshots/process/` 待补。

本包包含所引用的合成资料、原始失败记录和工程验证证据，支持独立阅读。源码与启动命令在本地 Git 仓库；未创建公共仓库或对外链接。题目原文、密钥、私人邮件不在本包中。

提交截止为 2026 年 11 月 9 日结束前，题目未注明时区；本轮只准备材料，未对外发送。
