# DECISIONS — Reel Agent

关键架构和产品决策记录。只收录对后续开发有实际影响的判断。

---

### D1: 单 Agent + 后台 Pipeline，不做多 Agent

- **时间：** 2026-03（产品原则讨论）
- **原因：** 低成本 > 架构先进性。经纪人不需要 5 个 agent 串行，多 agent 串行会增加延迟和 API 成本。按"真人团队分工"映射：1 个客户经理（OpenClaw）+ 后厨团队（Pipeline）
- **影响：** 所有用户对话走 OpenClaw，后台只做生产，不做对话
- **出处：** doc/产品原则概述.md, PRODUCT_ROADMAP.md "分工边界" 章节

---

### D2: KPI 驱动 Skill，不做 SOP 流程

- **时间：** 2026-03
- **原因：** SOP 会随模型换代失效。KPI 定义"做好的标准"，具体怎么做由模型适配层决定。强模型给目标，弱模型给 SOP
- **影响：** 每个 Skill 定义 KPI 而非步骤；换模型只改适配层，不动 Skill 定义
- **出处：** CLAUDE.md "模型适配原则", AGENTS.md "5 Skills"

---

### D3: 消息入口优先，不做 Web App

- **时间：** 2026-03（用户研究结论），2026-03-30（入口边界澄清）
- **原因：** 目标用户（关系驱动型经纪人）不学新工具。优先走已有消息渠道，而不是要求用户进入独立 Web App。当前可接受入口包括 WhatsApp、Telegram、iMessage；具体渠道可按阶段接入
- **影响：** 所有交互设计围绕消息入口组件（按钮 / 列表 / 文本）展开，不做独立前端。OpenClaw 绑定可按渠道逐步增加，但统一回到同一套项目事实层和后台 Pipeline
- **出处：** doc/prita-interview-transcript.md, PRODUCT_ROADMAP.md "需求收集方式"

---

### D4: OpenCV Farneback 替代 VBench pip 包

- **时间：** 2026-03-27
- **原因：** VBench pip 包依赖 PyTorch CUDA（~2GB）+ decord，在 Python 3.13 / macOS ARM 上无法安装。核心算法（top-5% 光流幅度阈值、帧间差异方差）用 OpenCV Farneback 复现，CPU-only，~50MB
- **影响：** motion_metrics.py 是自研实现，不依赖 VBench 包；精度略低于 RAFT 但足够做质量分级
- **出处：** skills/listing-video/scripts/motion_metrics.py, commit 556f49b

---

### D5: Quality Gates — critical 中止，warning 继续

- **时间：** 2026-03-27
- **原因：** 纯中止策略会导致大量 job 失败（TTS 偶发失败很常见）；纯警告策略会放过静默视频（88 Jalan Bukit Kiara 事件：TTS 6/6 失败 + 无 BGM → 交付了无声视频）
- **影响：** dispatcher.py 5 个关卡，每个关卡的 check 分 critical 和 warning 两级。critical 触发 QualityGateError（不重试），warning 只记日志
- **出处：** orchestrator/dispatcher.py `_check_quality_gate()`

---

### D6: Motion Metrics 放 Review 环节，不放 Diagnostics

- **时间：** 2026-03-27
- **原因：** Review = 每条视频自动评分（传感器），Diagnostics = 用户投诉后手动排查。motion 分数应该每条都有，不是出了问题才看
- **影响：** review_video.py 自动运行 compute_motion_metrics()；结果写入 auto_review.json 和交付通知
- **出处：** skills/listing-video/scripts/review_video.py

---

### D7: IMA Studio 主力 + Ken Burns fallback

- **时间：** 2026-03
- **原因：** 不硬依赖单一视频引擎。IMA Studio API 不稳定时，Ken Burns 幻灯片保证有视频交付（质量降级但不中断）
- **影响：** render_ai_video.py 失败自动调用 render_slideshow.py；diagnostics 记录 fallback_scenes
- **出处：** skills/listing-video/scripts/render_ai_video.py, CLAUDE.md "风险与应对"

---

### D8: TTS 三级 fallback — IMA → ElevenLabs → OpenAI

- **时间：** 2026-03
- **原因：** 单一 TTS 引擎的可用性不够。IMA Studio TTS 偶发失败；ElevenLabs 质量好但贵；OpenAI TTS 最便宜做兜底
- **影响：** generate_voice.py 按顺序尝试三个引擎；profile 可锁定特定引擎（voice clone 场景）
- **出处：** skills/listing-video/scripts/generate_voice.py

---

### D9: 生产态意图识别归 OpenClaw Router Skill，`/api/message` 降级为 test-only baseline

- **时间：** 2026-04-02
- **原因：** 思远要求端到端体验完整产品流程，且生产态意图识别本就应该位于 OpenClaw；此前 `/api/message` 主要用于测试与基线验证，不应继续承担生产主入口
- **影响：** 生产态由 OpenClaw Router Skill 直接判定 trust-first / property-content / listing-video / revision / daily-insight / push-control 等路径；后端生产 API 以 `/api/profile/{phone}`、`/webhook/in`、`/webhook/feedback`、`/api/daily-trigger` 为主；`/api/message` 保留给测试 / 回归 / 对照验证
- **补充：** daily insight follow-up 扩展为 `publish / skip / shorter / more professional`；其中 `shorter / more professional` 通过 `/webhook/feedback` 的 insight refinement 模式承接，不新增第 5 个生产 API
- **出处：** 2026-04-02 思远拍板 + `MINI_HANDOFF.md` + 本轮 D9 重构实施
