# 交付清单 formal-v2-20261107

更新：2026-11-07。状态只按证据如实标注；「待真人评价」的项目在评价完成前不标完成。

| PDF 要求 | 文件 | 状态 |
|---|---|---|
| A 工作日志（六列表头＋截图） | work-log.csv、work-log-detail.md | 待补：v1 阶段日志在 initial-local；本轮日志在 WORK_LOG.md，合并生成于真人评价后；AI 对话步骤截图待用户提供 |
| B 方法论 | methodology.md | 已写（工具、测试集、评价、好坏定义、版本复现）；真人评阅依据待补充 |
| C 50 例（八列） | outputs.csv + outputs.status.json | 完成：50 行／150 条中文，formal-v2 首轮 50/50；row-provenance.json 逐行溯源 |
| D 评价报告＋截图 | evaluation-report.md、截图 | 待真人评价（当前 0 条） |
| E 缺陷与下一步 | defects-and-next-steps.md | 已写（v1 缺陷清单、S1 修改前后、剩余缺陷与下一步） |
| 加分：架构图 | architecture.svg | 已附（与实现一致） |
| 补充组证据（B/E 佐证） | multiturn-outputs-*.csv、language-outputs-*.csv（含 status） | 完成：6 多轮＋24 语言组，首轮与关联技术重试分列 |
| 版本与来源 | versions.json、row-provenance.json | 已生成 |

提交方式：打包 zip 后由用户发送到 PDF 指定邮箱；链接或附件均不含密钥、不含原始运行目录外资料。

遗留事项（不阻塞交付，但须如实说明）：
1. 真人评价 formal-v2 全部 150 条（第二位复核 12 例，无则单人）→ 完成后生成 D；
2. AI 对话步骤截图（历史缺件，用户提供后并入 A）；
3. approved.jsonl 示例待人工审阅（当前为空，机制已接入）；
4. S2/S3/S5 未实施（见 E）。
