# 交付清单 formal-v6-20261107

更新：2026-11-07。状态只按证据如实标注；「待真人评价」的项目在评价完成前不标完成。

| PDF 要求 | 文件 | 状态 |
|---|---|---|
| A 工作日志（六列表头＋截图） | work-log.csv、work-log-detail.md | 已写；AI 对话步骤截图待用户提供（逐格标注） |
| B 方法论 | methodology.md | 已写（两步生成、品牌语感与极简规则、12 类门禁、测试集、评价、好坏定义、版本复现） |
| C 50 例（八列） | outputs.csv + outputs.status.json | 完成：formal-v6 首轮 48/50＋2 例关联技术重试，150 条中文；row-provenance.json 逐行溯源 |
| D 评价报告＋截图 | evaluation-report.md、截图 | 待真人评价（当前 0 条）；评价表见 evaluation-form-formal-v6.md |
| E 缺陷与下一步 | defects-and-next-steps.md | 已写（v1 缺陷、v2→v6 前后对照、告警器与门禁演进、剩余缺陷与下一步） |
| 加分：架构图 | architecture.svg | 已附（与实现一致） |
| 补充组证据 | multiturn-outputs-*.csv、language-outputs-*.csv（含 status） | 完成：6 多轮（multiturn-s6）；24 语言组（language-s10 首轮 23/24，LG-EVENT-C2E 重试仍失败，如实保留） |
| 版本与来源 | versions.json、row-provenance.json | 已生成 |
| 测试集评价材料 | test-cases-review.md、evaluation-form-formal-v6.md | 已生成（供真人审阅与填写） |
| 部署 | 仓库 DEPLOY.md | 待用户选择平台并提供凭据后发布公开链接 |

提交方式：打包 zip 或公开链接由用户发送到 PDF 指定邮箱；链接或附件不含密钥。

遗留事项（如实说明）：
1. 真人评价 formal-v6 全部 150 条（第二位复核 12 例，无则单人）→ 完成后生成 D；
2. AI 对话步骤截图（历史缺件，用户提供后并入 A）；
3. approved.jsonl 示例待人工审阅（当前为空，机制已接入）；
4. 公开部署待用户提供 GitHub 账号（Streamlit Community Cloud）或自有服务器；
5. 语言组 1 例英文输出两轮失败（见 E）；告警器共享容量列表误报待修；
6. S2/S3/S5 未实施（见 E）。
