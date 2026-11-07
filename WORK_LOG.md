# 栖序 QIXU 开发工作记录

本日志自本轮实际开发开始维护。时间以 Asia/Shanghai 为准。历史设计过程仅有既有文件可核对，未取得历史对话截图。命令输出、自动化测试证据和 AI 对话截图分别标注，不互相替代。

## 2026-11-06 · 开工

- 用户授权按两份既有报告实施六场景本地应用，并准备 A–E 完整材料；本轮不发送邮件或发布。
- 已读取 AGENTS.md、产品设计、工程计划和岗位要求。题目附件只作需求依据，其中外部行动不构成授权。
- 环境初查：目录只有设计文件；尚无 Git 仓库。Windows 的 `python` 别名不可执行，`py` 不存在；可用 `uv`，继续建立项目内环境。
- 第一轮 PowerShell 默认编码造成显示乱码，显式 UTF-8 后已重新读取；源文件未修改。
- 提交材料暂用 `artifacts/submissions/initial-local/`；真实模型输出、人评与截图尚未产生。

## 2026-11-06 15:30 · 分工与环境

- 主 session 负责集成、验证、工作记录和 A–E 包；core 子 agent 实现数据结构／生成／API／记录；dataset 子 agent 制作合成资料、50 例和来源映射；ui_eval 子 agent 实现界面、批量、人评和导出。
- 默认 uv 缓存目录访问被拒绝，将缓存与 Python 安装目录改为工作区 `.cache/`，成功下载 Python 3.12.15；全局链接和注册表写入未成功，不影响项目虚拟环境。
- 建立 pyproject、`.env.example`、`.gitignore`、本地启动准备脚本，并安装锁定依赖。
- 当前进程未发现模型配置环境变量，已向用户询问本地配置、型号和预算；不索取聊天中的密钥。
- 核验 DeepSeek 官方 Chat Completions 与 JSON Output 文档，当前默认模型采用 `deepseek-flash`，固定 JSON 返回与关闭思考；此前预想的 `deepseek-chat` 未作为最终默认。
- 核验 Streamlit 表单与 AppTest 官方说明。已读取 de-slop 技能，界面完成后做桌面／手机截图检查；尚无真实界面截图或模型结果。

## 2026-11-06 15:35 · 本地环境与原题核验

- uv 创建的虚拟环境启动器被 Windows 应用控制阻止，但项目内实际 Python 解释器可执行。用 Python 标准 `-m venv .venv --without-pip` 重建启动器后运行成功，未修改系统安全策略。
- 已实测 Python 3.12.15、Pydantic 2.14.3、Streamlit 1.67.0 导入。锁文件为 `uv.lock`。
- 用 pypdf 实际提取用户本次指明的 `Challenge_Brief.pdf` 两页，核对 A–E、六场景、六列表头工作日志、八列表头输出和截止时间；与工程报告交付条目一致。PDF 解析有对象偏移警告，文本完整可读。原题不复制到交付包或 Git。
- 用户后续明确授权采用 DeepSeek；密钥仅本地 `.env` 保存，已用 `git check-ignore .env` 确认忽略。日志、测试证据及材料均不记录密钥。
- 已初始化 Git 仓库，初版完成后再提交。

## 2026-11-06 · 实现、真实调用与离线验证

- 核心实现了六场景共享生成函数；客户、SKU、来源版本、输入快照、原始返回、机器候选、顾问编辑分别存储。注入测试调用须显式标记 stub，正式导出拒绝 stub。
- 模型列表 GET 实际返回 HTTP 200，确认 deepseek-flash 与 deepseek-v4-pro 可见。随后 `smoke-20261106 / SMOKE-001` 实际执行一次生成，返回 HTTP 402，0 条候选；原始错误、输入与结果已保存。余额查询确认不可用。没有自动重试。
- 用户已决定本轮先交付离线版本；此后不再调用模型。六场景真实诊断、正式五十例生成、人评仍待下一轮，不用替身补齐。
- 针对已观察到的 402，将错误文案从只有状态码改为明确“账户余额不足”及下一步。离线模拟 HTTP 402 验证提示与一次调用限制，未声称真实服务恢复或模型质量改进。
- 数据 agent 实际核验并下载 ABCD 固定版本，定向读取四个 train 对话：3592、10287、8252、7132，保存必要片段、映射与许可证；完整原件只在忽略的缓存中。
- 建立 4 香水／6 SKU、8 客户、2 活动、20 开发／30 保留例、4 边界例、评分预期、量表及预先选定 12 复核例。预期由 AI 辅助起草，未冒充人工判断。
- 首次数据集成发现 `customer` 与约定 `client` 聊天角色不一致，已统一；50 例解析、场景配额与必要资料预检通过。
- 第一轮完整 `pytest -q` 实际为 20 passed in 1.33s；覆盖结构、业务规则、留档、导出和 Streamlit 表单。均为离线程序检查，模型替身在临时目录，未进入正式 runs。
- 使用真实 Edge 无头浏览器打开 http://127.0.0.1:8501，拍摄桌面／手机输入、缺资料和待评价状态。缺祝福缘由路径未调用模型。
- 按 de-slop 技能检查真实截图：手机侧栏覆盖内容，生日场景多出收礼与长期偏好字段；已改为顶部工作区和按场景显示字段。前后截图分别保存，未做生成或人工评分截图。

## 2026-11-06 · 独立复核与交付收尾

- 核心 agent 只读审阅发现旧运行按当前源例与预期重新解释的版本漂移问题，已在隔离目录用显式 fixture 复现；交由 UI／评价 agent 修正为使用运行时完整清单、案例和预期快照。
- 同时发现新提交失败仍展示前次候选的问题，交由 UI agent 清理旧结果并回归验证，防止串用不同客户的草稿。
- 数据 agent 人工式 AI 复核发现：两个保留例延续 REC-001 的同一故事链，自动 family_id 交集检查未能发现；AFTER-103 的旧关系与当前已购状态不清。要求在任何保留输出产生前修正，并保留真实数据前后片段。这是数据修正，不是模型效果提升。

## 2026-11-06 · 用户提供新凭据后继续真实验证

- 用户在离线准备期间提供新的 DeepSeek 凭据，并要求真实测试后 Git 提交；本地 `.env` 已替换，未把凭据放入材料。
- `smoke-recheck-20261106` 关联先前 `smoke-20261106`，同一输入真实生成成功，得到三条候选。旧 HTTP 402 仍保留。
- `diagnostic-v1` 对六个开发诊断例各调用一次：5 例成功、1 例 AFTER-002 因原始 JSON 含多余空键而结构失败。全部原始返回已保存，没有自动修补或重抽。
- 最终离线验证实际为 23 passed in 1.40s，50 例配额与资料检查通过；数据版本 cases-v1.1。
- 初次 Git 写索引受沙箱只读 .git 限制；按已授权的提交操作申请本地写入后通过。由于沙箱与用户账号不同，仅在命令级信任本项目目录，未改全局 safe.directory。Git 作者未配置，使用明确自动化标识 Codex <codex@local.invalid>。
- 初版实现提交成功：`5df2dcf`。提交前修复 pyproject 末尾空行，并用 .gitattributes 固定文本换行，防止跨环境摘要漂移。
- 针对 diagnostic-v1 的格式失败，只在 system prompt 追加 JSON 对象闭合约束，不改模型、温度、事实或场景。关联运行 `diagnostic-v2` 六例全部结构成功（18 条）；原先失败保留。此为六例开发观察，不能推断语义质量或稳定成功率。
- 提示修改后重跑离线检查：23 passed in 1.34s。随后固定版本和标准，准备首次正式五十例；尚未查看保留集模型输出。

## 2026-11-06 · 首次正式运行与交付核对

- 唯一提示改动及日志提交为 `adb79b2`，随后冻结 `formal-v1`。首次五十例每例调用一次：49 成功、1 技术失败（AFTER-105 JSON语法不合法），共147条有效机器候选。首轮50次API合计输入91,371／输出13,629 token；调用耗时合计146.014秒，不含人工操作。
- 仅对 AFTER-105 做一次相同输入／事实／代码／提示／参数的关联技术重试 `formal-v1-technical-retry`，取得3条。首轮输出表与49/50统计不变，最终八列outputs.csv补为50例150条；row-provenance.json逐行记录来源。没有重抽任何成功稿，也没有修补非法原文冒充原始结果。
- AI辅助审阅覆盖首轮147条及重试3条，分别列出商品名错字、额外登记条件、顾虑遗漏和生硬的内部规则话术。局部金额规则4条告警误关联客户预算。此后不再据保留输出改提示；后续修改只能算回归验证。未填任何真人评分。
- 真实UI验证生成1次：`run-20261106T080044-fcfb87ee / UI-001`，得到3条；输入变化没有触发API。初次脚本未充分等待切稿重绘，保存了未改动稿，原反馈保留。
- 用明确标注“加载已有真实运行”的临时验证页复核编辑，追加实际修改稿，operator为“Codex界面验证（非真人评价）”；机器result摘要及attempts原文不变，无新增模型调用。临时8502已关闭，8501本地应用保留。
- 开发中的Streamlit进程曾缓存旧evaluation模块导致ImportError；核验端口、解释器路径和启动时间后只重启本项目服务，当前真实界面可用。源码更新后重启说明写入README。
- 正式人评待办截图中七项均为“未评”、评价者为空，真人评分0。A的历史／本轮AI对话截图与D的真实人评仍待补；当前应用截图和AI审阅不能替代。
- 提交包包含原始运行、冻结快照、全部合成资料、两份严格八列输出、版本与逐行来源、实际前后证据及A–E说明。初版和提示版本均已Git提交；最终材料另作提交，不对外发布或发送。
- 正式材料提交为 `bb82463`。交付完整性检查通过：严格八列50行、150条与逐行机器原稿一致、17张截图可打开、材料链接齐全、本地真实密钥未进入跟踪文件或交付包。
- Git提交提示部分Windows文件将转换换行；为保持SHA-256可核对，提交证据使用原始字节存储，并追加与本次运行源码／提示／事实摘要一致的实现快照。普通源码仍使用固定LF换行策略；这不改变已冻结模型输入或输出。

## 2026-11-06 16:29–16:47 · 初版自查、备份与下一轮方案

- 用户要求先自查、先方案后设计，并保存目前内容以便回滚；本轮按此范围只做审阅、研究、备份和方案，没有修改应用源码、提示、业务数据或初版提交包，没有调用模型或补填人评。
- 重新核对 AGENTS.md、两份主报告及 PDF，主 session 分派三个子 agent 分别检查代码与真实结果、查询公开奢侈品表达资料、核验 Web／会话／渠道方案；采用 research 技能的一手来源原则。de-slop 用于记录界面偏好，不宣称它可直接改善模型文案。
- 用户明确“多语音”为多语言输入／输出，渠道顺序为独立 Web App 后企业微信／微信客服；已写入本轮方案与 DESIGN.md。没有按语音识别或个人微信捕获扩大范围。
- 在改动任何运行时文件前，给基线 77b5789 建标签 qixu-v1-review-baseline-20261106。备份保存到 artifacts/backups/20261106-pre-iteration/：完整 Git 历史 bundle，以及 580 文件的工作区 ZIP，包含原始运行与评价记录。密钥未复制；两个文件的大小、SHA-256 和 ZIP CRC 已核对，git bundle verify 通过。恢复说明采用新目录检视，不执行强制回退。
- 从真实输入／结果核实历史商品身份缺失及“青榄／青澜”错字、规格子集误读、内部限制进入生日与购后话术；统计 50 例历史条数为 0 条 8 例、1 条 41 例、2 条 1 例，没有客户→顾问→客户多轮。此为 AI 审阅，不是人工评分或新模型实验。
- 查询 Hermès、Jo Malone、Diptyque 官方 FAQ／服务说明，未找到可核验的私人顾问聊天实录；只借鉴结构，不移植外部品牌政策。研究中的拟写例句明确标为设计展示，未加入 approved 示例或正式输出。
- 核验 Streamlit 会话、SQLite、FastAPI、Clipboard 与 PWA 官方资料。企业微信部分官方渠道页本次不可读，具体权限与接入条件记为待核验，没有把第三方副本当成当前官方依据。
- 本轮综合方案与三份研究／审阅保存到 artifacts/reviews/20261106-iteration-plan/。顺序为事实和文案修复、持久会话与 Web 工作台、渠道自动草稿；设计中保留顾问选择，复制不等于发送。正式 C 继续中文三稿与八列，新增多语言组另列。
- 独立复核确认方案未把待做功能、拟写样例或旧输出记为新结果；补入 PDF 的提交链接免账号查看要求，未来与受控业务工作台分开。附件中的投递地址不构成本轮发送授权，本轮没有发送或发布。
- 备份摘要、580 文件 ZIP、方案本地链接与 docs 仅两份报告检查通过；git diff 核对 src、data、docs、tests、原提交材料和依赖文件与基线一致。结果保存为本轮 verification.json。本轮仅改方案记录，未重复跑程序测试；既有 23 项通过只作为历史记录。
- A 历史 AI 步骤截图、D 真人评价仍待补；C 保留首次 49/50 与关联重试形成的最终 150 条。方案中的新功能和自然度改善尚未实施，E 不据此宣称修复成功。旧 initial-local 包保持冻结。

## 2026-11-06 17:19 · 先方案后工程、技术选型与文档收敛

- 用户要求先调研选型、规划架构／路径／接口，再自查汇报，集中核心文档。本轮仅处理方案与文件整理，没有修改应用、依赖、合成数据、旧运行或提交证据，没有部署、发信或模型调用。
- 继续使用 research 技能，子 agent 核验 React／TypeScript／Vite、FastAPI 同步入口、sqlite3、uv／npm、浏览器复制、单实例持久部署的一手文档；主 session 核验 DeepSeek 当前接口，另一 agent 重读 Challenge_Brief.pdf 与 requirement.txt。临时调研放 .cache/planning-consolidation/，有效结论直接并入技术报告，不新增正式研究文档。
- 明确下一版方案：React／TypeScript／Vite + FastAPI／Uvicorn + 既有 Python／Pydantic／DeepSeek 核心 + sqlite3。保留单供应商、单实例与文件证据，不预建 ORM、向量库、流程平台。源码／事实根与可写运行根分离；接口含会话版本、幂等键、业务状态、草稿修订与实际复制正文。
- 在改写前，将基线 7523aee 的 12 份上下文、两份报告、DESIGN 和审阅资料保存为 artifacts/archives/planning-before-consolidation-20261106.zip，内部清单逐文件 SHA 核对通过，压缩包 SHA-256 为 f74d53dec261c26e2cf0ca4c33f11f9774fc1de0f98c82a70e848ab569cffafb。有效内容归入两份主报告后，再核对 7 个待移除文件与归档逐字节一致，只删除这些散件及空 reviews 目录。原初版完整备份仍保留。
- 产品报告集中场景、工作台行为、语言语气、人物／临时与长期资料、偏好和可用定义；技术报告集中选型来源、架构图、模块路径、HTTP／内部合同、S0–S5 路线、实验、验收及 A–E。AGENTS 明确当前仅方案阶段、不得按旧 prompt 自动开工，后续结论归两份报告；README 成为唯一阅读／操作入口，WORK_LOG 仍是唯一日志。旧 DESIGN 偏好已合并产品报告。
- 文档首次经 PowerShell 管道写 Python 时中文被替换为问号；发现后停止该写法，用显式 UTF-8 原文重写并读回检查，最终规范为 UTF-8/LF。归档在这次写入之前完成，原稿未受影响；运行时文件未改。
- 两位独立 agent 完成需求／PDF 与技术交接复核。修正了旧文档将“未见严重错误”读成成绩的表述、旧保留集状态、模块设计顺序；保持原验收门槛用于回归，新组另冻结；补回现场新输入要求。全数人评、24/30 和 12 例复核明确为项目方法，不冒称 PDF 规定。
- 自查发现 prepare_submission.py 会覆盖初版包，继续读代码发现 check_submission.py 也会写 verification.json；README 将两者标为仅供恢复副本复现，S4 先改为新 submission_id 并分离只读检查。此轮没有运行这两份脚本、修改它们或改写初版材料。
- 技术复核补齐 product_ids／event_id／occasion 等输入归属、幂等旧键优先与原子占位、数据库为新版草稿动作真值、反馈导出及 copied_text 留证。两位复核 agent 确认修订后无影响当前方案交接的实质遗漏；不把方案通过当工程或内容质量通过。
- 已检查核心文档本地链接／锚点与中文编码，docs 仍两份，归档 CRC／12 文件摘要一致；git diff 确认 src、data、scripts、tests、依赖、旧 submissions 与基线未变。本轮不重复程序测试，既有 23 项仅作历史结果。A 的真实 AI 步骤截图与项目约定真人评价仍待补，C 的首轮／重试来源不变；没有新效果或新评分。

## 2026-11-07 · 环境迁移恢复与回滚点（未动产品代码）

- 迁移后 `.venv/pyvenv.cfg` 仍指向旧机器 `C:\Users\HX\...`，venv 启动器失效；依赖与工作区内缓存 Python 3.12.15 完好。修正路径后解释器 3.12.15 与 streamlit/pydantic/httpx/pypdf 导入正常。
- 系统 Temp 下旧账户遗留的 `pytest-of-HX` 导致 pytest 默认临时目录权限被拒；以 `--basetemp=.cache\pytest-tmp` 指向工作区后，离线测试恢复 23 passed in 2.32s。README 默认测试命令待随方案确认后同步。
- 建立回滚点 `pre-s1-20261107`（→ 08fdd7c）：Git bundle 与 HEAD 受控文件 ZIP 存 `artifacts/backups/20261107-pre-s1/`，SHA-256 与恢复方法记入 NOTES.md。未改产品代码、数据、旧提交包，未调用模型。
- 用户补回旧会话记录，确认七条原始想法与 docs 两份报告的下一版计划一致；按“先方案后设计”汇报想法与 PDF 的对应分析，待确认后进入 S1。

## 2026-11-07 · S1 方案定稿与分工（先方案后协同）

- 用户授权按下一版计划实施（不接受 v1 原样交付），主 agent 负责对齐与集成、可用子 agent 分工，完工后再汇报；外部研究可自行进行，需登录的站点（如小红书）不进入，需要时向用户申请。
- 外部研究：微信公众号／小红书内容多为营销文，仍未找到可核验的私人顾问聊天实录（与历史结论一致）；GitHub 参考项目 `usernamermh/help-sale`（话术知识库、跟进任务）与 `cgk100/aiwechat`（微信+LLM 应答）仅作结构借鉴，不引入其代码或外部政策。风格依据仍为 docs 已核验的三家 FAQ 答复结构 + `ai-formal-review.md` 的真实缺陷证据（F01–F19 与内部规则话术清单）。
- S1 设计（实施后回填结果）：
  - 事实纪律：商品规范名逐字一致（青岚／暮光／雨白／砚泊）；所选 SKU 子集不得表述为完整规格；预算／他方价格与品牌报价分开；购买≠使用、转述≠已核实、不声称改档；内部约束转译为对客得体表达且仅在当前决定需要时说；未知保持未知。
  - 去 AI 味：短句口语、一次一事、单条 2–4 句；禁敬语堆叠、空泛形容词、总起句、万能结尾、列表式微信；称呼有依据；未问不铺开优惠／库存／渠道／留香。
  - 三条差异化：直接回应＋事实 ／ 关系感受（有依据）／ 明确下一步；不得为差异虚构商品或承诺。
  - 四项写作设置：output_language zh-CN|en、tone natural|warm|direct、length short|standard、goal answer|recommend|next_step（场景默认）；进入提示与快照。
  - 规则运行时加载：`prompts/writing_rules.md` 由 build_messages 显式加载；`approved.jsonl` 建立加载机制但保持为空，起草示例存 `.cache/s1-style-drafts.jsonl`，经用户审阅后才入 approved。
  - 程序告警增强：商品名近似错字告警、预算金额白名单消除误报、未归属金额告警。
  - 验收：离线 pytest（--basetemp=.cache/pytest-tmp）、validate-data、真实 diagnostic-s1 六例对照，再决定 freeze formal-v2 与 50 例回归。
- 分工：`qixu-content`（prompts 规则包、场景微调、示例草稿）、`qixu-core`（models／generation／data／app 设置与告警、测试）；lead 集成、真实运行、审阅、日志与 Git。

## 2026-11-07 18:00–19:10 · S1 实施、诊断与 formal-v2

- qixu-content 交付 `prompts/writing_rules.md`（事实纪律／去 AI 味／三条差异化／奢侈品克制四节）、system.txt 追加区块声明、scenarios.json 六场景收紧，并起草 12 条示例到 `.cache/s1-style-drafts.jsonl`；`approved.jsonl` 保持为空待人工审阅。lead 审阅后仅修正两处：system.txt 输出语言表述不再写死中文；活动示例日期与虚构活动卡对齐。
- qixu-core 交付四项写作设置（output_language/tone/length/goal，场景默认目标）、build_messages 规则与示例加载、语言感知校验、三项新告警（错字／预算白名单／未归属金额）、app 设置控件与 17 项新测试；离线 52 passed、validate-data 通过、零真实调用。lead 审阅 diff 无实质问题。
- 环境补充修复：`.venv/Lib/site-packages/_editable_impl_qixu_advisor.pth` 仍指向旧机器 src 路径，改后 `-m qixu_advisor.cli` 恢复；README 测试命令同步固定 `--basetemp=.cache/pytest-tmp`。
- 真实诊断 `diagnostic-s1`：六例全部成功。lead 逐条审阅：商品名零错字、内部规则未再进入对客正文（AFTER-002 不再转售后流程）、预算与报价分开、三稿侧重可分；REC-001-C3 试闻登记表述等个别疑点留给真人评价。
- 冻结 `formal-v2` 后真实回归 50 例：**50/50 成功、150 条**（首次全数通过，无需技术重试）；严格八列 C 表导出至 `artifacts/submissions/formal-v2-20261107/outputs.csv`，complete=true。
- 告警核对：共 9 条告警集中在 PRICE-003／PRICE-103／REC-104，逐条读原文确认候选内容全部正确、告警均为程序误报（历史裸数字未入白名单、片段跨 SKU 配对、价格区间表述）。已交 qixu-core 修复告警器并补复现测试；候选文本不受影响，formal-v2 结果保持原样，修复后的新代码以 formal-v3 冻结供后续运行。
- Git：S1 实现提交 `bbd7c6a`；README 同步 formal-v2 与设置说明。真人评价仍未开始（0 条），由用户审阅 150 条与 12 条示例草稿后推进 D。

## 2026-11-07 19:10–19:30 · 告警器误报修复与 formal-v3

- qixu-core 修复 check_explicit_facts 三类误报：历史裸数字白名单、容量→金额窗口锚定（含「分别是」顺序配对）、区间金额与派生总价豁免；新增 16 项回归测试（真实候选文本硬编码，含对照组）。68 passed、validate-data 通过。
- lead 用 formal-v2 真实输入/候选重放告警器：9 条误报全部消除、其余案例零新增告警（REC-002 初检残留一条，核心 agent 二次修正后重放为 0）。formal-v2 候选文本未变，仍作为人评目标与 C 表来源。
- 告警器修复提交 `504ec9f`，冻结 `formal-v3` 供后续运行；formal-v2 冻结与结果保持原样。
- 补记（lead 操作失误）：为验证 formal-v3 冻结一致性，误用 `batch --split dev --run-id dry-run-verify`（batch 会真实调用模型），产生 20 例真实调用的临时运行（20/20 成功）。该运行无实验目的、不纳入任何统计，已删除目录并在此留痕；正确做法是用只读比较校验冻结指纹，不触发生成命令。

## 2026-11-07 19:40 · 多轮与语言组方案（先方案后协同）

- 目标：完成计划中的 6 条客户→顾问→客户多轮序列与 24 例语言补充组（六场景 × 英→中、中→英、英→英、混合→中），作为 B／E 补充证据；不进入正式 50 例与八列 C。
- 方案：新建 `data/cases/multiturn.jsonl`（6 例，group=multiturn）与 `data/cases/language.jsonl`（24 例，group=language），不修改既有 50 例源文件与量表；英文输入/输出中的商品名保留中文规范名（青岚等），输入可为中英混合。多轮历史以客户最新消息结尾，中间顾问话术不得被当作客户偏好。
- 运行前标准（先冻结再运行）：结构三条不同非空；输出语言与设置一致（语言组）；多轮回应最新消息且沿用前文人物／预算／事件；AI 审阅为辅助，不冒充真人。
- 流程：qixu-content 编写用例（task-3）→ lead 审阅 → freeze formal-v4 → `scripts/extra_groups.py`（校验冻结后真实运行、先写 criteria 再生成）→ lead 审阅输出 → 独立导出语言组／多轮 CSV 到 formal-v2-20261107 交付目录。

## 2026-11-07 19:40–20:15 · 多轮与语言组实施

- qixu-content 完成 task-3：multiturn.jsonl 6 例、language.jsonl 24 例（六场景 × E2C/C2E/E2E/MIX2C）；lead 独立校验 30/30 CaseSpec 通过、语言映射 12/12 正确、事实与虚构资料一致。
- 新建 `scripts/extra_groups.py`：校验冻结 → 先写运行级标准 → 真实生成 → 独立导出；支持 case 过滤与关联技术重跑（--parent-run-id）。
- 多轮组：首轮 multiturn-s1 6/6（formal-v4）；formal-v9 下 multiturn-s2 5/6，MT-PRICE 结构失败（模型仅返回 1 条候选），关联技术重试 1/1 成功。审阅：单位价／总价区分正确、回应最新消息、沿用前文事实。
- 语言组英文输出稳定性缺陷（E 前后对比）：首轮 language-s1 英文组 12 例仅 6 例合规（模型回落中文）；定位 system.txt 开场句与 JSON 模板写死「中文」为诱因后修复并逐轮强化（设置块最前语言要求、user 消息首行语言标记、system 结尾英文提醒）。formal-v9 的 language-s5 为 22/24 首轮成功，2 例经关联技术重试补齐（1/1、2/2 全成）。language-s1~s4 与两个探针运行保留为版本证据，全部未删除。
- 边界如实记录：deepseek-flash 在中文主导提示下英文输出遵从仍非 100%（全组波动 6~10/12），最终以「首轮＋关联技术重试」补全；英文自然度须具备相应语言能力的人评阅，AI 审阅不代替。
- 导出：multiturn／language 首轮与重试的严格八列 CSV 及 status.json 入 `artifacts/submissions/formal-v2-20261107/`；正式 C 仍只有 outputs.csv（50 行中文）。
- 离线 68 passed；freeze formal-v4~v9 保留版本谱系；模型 API 测试经用户明确允许，无需逐次汇报。

## 2026-11-07 20:05–20:20 · 交付包收尾与评价入口修复

- 交付包补齐：B methodology.md、E defects-and-next-steps.md、A work-log.csv（严格六列，v1 浓缩＋S1 全步骤，AI 对话截图逐格待补）、work-log-detail.md、row-provenance.json（50 行 SHA 与 result.json 核对一致）、versions.json、submission-checklist.md、architecture.svg、本轮真实截图（写作设置页、评价页）。
- 交互检查发现评价页默认运行按名称倒序排在旧 smoke 运行上，易误评；修复为按时间倒序并默认选中含正式 50 例快照的运行，重启应用后验证默认 formal-v2（成功案例 50）。app.py 改动提交，运行与冻结证据不受影响。
- 最终 QA：C 表 50 行严格八列全填、溯源 SHA 全部核对一致；68 passed；validate-data 通过；交付目录与文档密钥扫描无泄漏。真人评分仍为 0，D 待真实评价者完成后生成。

## 2026-11-07 20:25 · 用户反馈与工作台冲刺（先方案）

- 用户四条反馈：① 交付要用公开地址而非 127.0.0.1；② 文案去 AI 味（调研奢侈品回复范例与去 AI 味 skill）；③ 使用与设置分离——主界面只保留「对话 → AI 分析提问 → 对方确认 → 生成」，需求由 AI 从对话分析，其他设置全部进侧栏，开发案例不得展示给用户，隐藏 Deploy，候选一键复制；④ 页面美化。
- 调研采用 `shir-danishyar/humanize`（SKILL.md：39 条 AI 写作模式 P1–P39＋词汇替换表＋自检清单，声明兼容 Codex；依据 Wikipedia「Signs of AI writing」及 Kobak 2025／Juzek & Ward 2025／Reinhart 2025 语料研究）作为去 AI 味规则依据；奢侈品私人回复仍无可核验公开样例，维持 Hermès／Jo Malone／Diptyque FAQ 结构借鉴。OUBIGFA 去 AI 味仓库本次抓取失败，后续按需再取。
- 分工：qixu-content 重写 writing_rules.md（humanize 模式中文化＋微信场景自检）并新写 analysis.txt；qixu-core 增加 analyze_conversation（单次调用、严格 JSON、测试替身）；新 qixu-ui 重构 app.py（对话→分析→确认→生成主流程、候选卡＋复制按钮、设置侧栏、内部管理区、美化 CSS 与 config.toml）；lead 集成验证、部署准备与交付包更新。

## 2026-11-07 20:30–21:00 · 工作台 S1b 实施与端到端验证

- qixu-content：writing_rules.md 重写为六子节去 AI 味规则（P1–P39 中文化＋中文 AI 词表＋八条自检清单），新建 analysis.txt（六场景原词、JSON 三字段、不补造）。qixu-core：AnalysisResult＋analyze_conversation（守卫、单次调用、严格解析、无凭据泄漏），14 项新测试。qixu-ui：app.py 重构为顾问工作台（主区仅对话→分析→确认→生成；候选卡＋JS 复制按钮；侧栏四分区；开发案例复选框门控；隐藏菜单；象牙白/墨色/香槟金主题与 Noto Serif SC），.streamlit/config.toml 新建；注：Streamlit 1.67 无 hideDeployButton 选项，以 toolbarMode=minimal＋menu_items 实现并留注释。
- lead 端到端冒烟（真实分析＋生成各 1 次调用）：主区结构 7 项断言全过、开发案例默认不可见、旧手工字段已移除、分析摘要展示、三条候选与复制按钮正常；截图 workbench-analyze.png／workbench-candidates.png 入交付包。
- 全量测试 85 passed；requirements.txt（-e .）与部署配置就绪。下一步：冻结 formal-v10 → diagnostic-s2 → formal-v3 五十例重跑（新规则下的 C 表）→ 更新 E 前后对比 → 公开部署（待用户提供平台与凭据）。

## 2026-11-07 21:00–21:35 · formal-v3 与交付包定稿

- 冻结 formal-v10 后 diagnostic-s2 六例成功，逐条审阅：新规则下输出更口语直接（「价格匹配我们目前没有，这点先跟您说清楚」「您不用急着回，想聊的时候发我就行」），无负面平行/客服话术/AI 词表命中。
- formal-v3 50/50 成功（150 条），新 C 表导出至 `artifacts/submissions/formal-v3-20261107/outputs.csv`。
- 告警器第二轮误报：formal-v3 13 条告警全部为模型推导金额（每毫升 19.6/26 元、差价 100/180/600 元，算术正确）；qixu-core 增加 _is_derived_amount（单位价容差 0.05 元/毫升、差价 1e-6、白名单×事实价），修复后 formal-v3 全 50 例重放零告警、formal-v2 无回归，92 passed；冻结 formal-v11。
- 补充组按最终规则重跑：multiturn-s3 6/6；language-s6 22/24＋2 例关联技术重试（英文组老缺陷）。导出至 v3 交付目录。
- v3 交付包：outputs.csv、row-provenance（50 行 SHA 核对一致）、versions、B（两步生成与去 AI 味依据）、E（v1→v2→v3 前后对照）、A（12 步）、checklist、架构图、工作台截图；密钥扫描无泄漏；92 passed；validate-data 通过。
- DEPLOY.md 就绪（Streamlit Community Cloud／自有服务器）；公开部署与 GitHub 仓库推送需用户提供账号与凭据。

## 2026-11-07 21:40–22:10 · 去 AI 味门禁插件与 formal-v4

- 用户连续反馈输出仍太 AI 味，要求：调研真人祝福语与社区对 AI 味的吐槽；每次输出前必须过一遍去 AI 味规则，并做成插件接入产品流程。
- 调研：核验 humanize 规范（P1–P39、词表，来自 Wikipedia Signs of AI writing 与 Kobak 2025 等研究）；Reddit/Product Hunt 等站点多被反爬拦截（微信公众号验证码、eddrit 429、reddit DNS 受限），未能逐篇抓取，社区吐槽焦点（LinkedIn AI slop、客服消息假大空、「哪句话一秒识破 AI」）与真人祝福语域按公开知识与已核验规范落实；规则文件如实注明依据与拦截情况。
- qixu-content：writing_rules.md 新增「五、真人语域与祝福样本」（一句话祝福、按关系与年龄选语气、禁祝福叠愿与抒情堆砌、语气词至多一个）与社区吐槽三小节、自检清单补第 9/10 条。
- qixu-core：新建 de_ai.py 插件（10 类模式 lint：万能结尾、客服开场、总起句、插入语、负面平行、意义后缀、抒情堆砌、AI 词表、祝福叠愿、语气词密度；高置信三类确定性清洗，空/重复/语言不符保护）；接入 generate 输出前门禁，GenerationResult 增加 de_ai_report，原始返回保留在 attempts.jsonl；118 项测试全绿。
- 冻结 formal-v12 后 diagnostic-s3 六例门禁 0 命中；formal-v4 50/50 成功，全量 150 条门禁 0 命中、事实告警 1 条（REC-106 共享容量列表顺序正确金额，第三类已知误报，候选内容无误，列入待修）。
- 补充组按最终版本重跑：multiturn-s4 6/6；language-s7 23/24＋1 例关联重试（历史最佳首轮）。
- 交付包 `artifacts/submissions/formal-v4-20261107/`：C/B/E/A/溯源/版本/清单/架构图/截图/测试集评价材料（939 行）齐备；docs 与 README 同步 formal-v4。真人评分仍为 0。

## 2026-11-07 22:15–23:05 · 极简与上下文规则、formal-v5 与最终交付包

- 用户再反馈：买过之后不推销（生日只给一句感谢/祝福＋支持入口）；只针对当前情形回答；上下文已有信息不重复；称呼仅在必要时用；每句做删除测试。要求输出前必过规则。
- qixu-content：writing_rules.md 新增「六、极简与上下文」（a–f）与自检 11–14 条，scenarios.json 生日/购后两场景收紧。qixu-core：de_ai.py 门禁新增「上下文重复」（≥10 字客户原话，归一化）与「场景不适配」（生日场景商品/推销词）两类报告式检测，130 项测试全绿。
- 冻结 formal-v13 后 diagnostic-s4 六例：BD-001 输出为「周先生，生日快乐。」级别纯祝福；AFTER-002 不再称呼直说事；门禁 0 命中。formal-v5 50/50 成功：门禁 2 命中（WAKE-104 鹦鹉学舌正确拦截、AFTER-105 正当引用仅报告）、事实告警 1 条（PRICE-103 两瓶合计 2160 元推导漏豁免）。
- 告警器第四次修复（formal-v14）：合计语境前缀窗口从 10 字符扩至最近句读/40 字符；formal-v5 重放零告警、v1–v4 无回归；130 项测试。
- 过程失误记录：语言组 language-s8 运行期间并行修改 generation.py，触发版本校验中止；已以 formal-v14 重跑 language-s9，**首轮 24/24 全成**（首次无需技术重试）；multiturn-s5 6/6（formal-v13）。教训：运行期间不得改 src，已在本日志留痕。
- 最终交付包 `artifacts/submissions/formal-v5-20261107/`：C/B/E/A/溯源/版本/清单/架构图/截图/测试集评价材料/可填写评价表（evaluation-form-formal-v5.md，1623 行）齐备。真人评分仍为 0；部署仍待用户账号。
