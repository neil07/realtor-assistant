# PRINCIPLES.md — Reel Agent 产品设计原则

> 全局原则见 `~/.claude/AGENT_PRINCIPLES.md` v1.1（P1-P6 产品价值 + A1-A8 架构实现）。
> 本文档将全局原则映射到 Reel Agent 的具体场景：房产经纪人发 listing 照片 → 自动生成社媒营销短视频。
> 遇到体验问题时，先到这里定位根因和对应原则，再讨论方案。

---

## 产品价值原则（P1-P6）在 Reel Agent 的落地

---

### P1. 可靠 > 炫技

**对本产品意味着什么：**
经纪人发 5 张照片，100% 能拿到一个可用的视频——哪怕部分镜头降级为 Ken Burns 幻灯片。房产经纪人时间极贵、发照片的场景通常是在车里或 open house 之间，一次"视频没出来"可能等于永久流失。

**当前状态：** 8/10

- 有 7 个 Quality Gate 贯穿 pipeline（`dispatcher.py`）
- 有 Auto-Retry：质量评分 < 6.5 自动重试一次（`dispatcher.py`）
- 有 Fallback：IMA 失败 → 单场景自动降级 Ken Burns 幻灯片（`render_ai_video.py` `_generate_one()`），不中止全局
- ThreadPoolExecutor 异常隔离：单场景崩溃不影响其他场景
- Callback 失败 → SQLite 本地队列 + 指数退避重试（`callback_client.py`，30s/60s/120s/240s/480s，最多 5 次）
- Auto-retry 有成本上限：`JOB_COST_LIMIT_CREDIT` 环境变量（默认 200 credit）
- **但**：无 SLA 承诺（目标 99.5% 交付率尚未度量）
- **但**：job 卡住无主动告警（Phase 2 范围）

**演进路径：**

- **Phase 1（MVP）**：单场景失败 → 降级 Ken Burns 而非中止全局；callback 失败 → 本地队列重试
- **Phase 2（PMF）**：SLA 承诺 99.5% 交付率；job 卡住 15 分钟自动告警；自动健康检查
- **Phase 3（规模化）**：多引擎热备（IMA 挂自动切 Runway/本地）；预测性故障规避

**诊断信号：**

- 用户说"我的视频没出来"
- 视频交付率 < 95%
- 同一个 job 重试 > 2 次
- Callback 失败无人知道

---

### P2. 记忆是资产

**对本产品意味着什么：**
用了 20 次的经纪人，系统应该像"老搭档"——知道她的风格偏好、她的市场区域、她讨厌的音乐类型、她每次都要 kitchen 特写。这是竞品抄不走的壁垒。

**当前状态：** 8/10

- Profile 体系完整：23 字段 × 7 维度（`profile_manager.py`）
- `learned_patterns` 4 个列表：`style_confirmed`, `music_rejected`, `always_include`, `frequently_requested`
- `revision_history` 记录最近 20 次修改反馈
- `get_preference_context()` 将偏好转为 prompt 注入（`dispatcher.py:226-229`）
- `preference_context` 注入 `plan_scenes`（via `property_info` + `<agent_preferences>` 标签）和 `generate_script`（独立参数）
- Positive feedback 路径：非重试 job 交付 → `record_positive_signal()` 强化 `style_confirmed`
- **但**：跨 agent 无共享洞察

**演进路径：**

- **Phase 1（MVP）**：~~消费 learned_patterns（注入 plan_scenes + write_prompts）；用户不修改即视为 positive signal，强化当时的 style + music~~ ✅ 已完成
- **Phase 2（PMF）**：跨 agent 聚合（"你市场的经纪人大多选 elegant"）；夜间记忆归纳
- **Phase 3（规模化）**：记忆成为数据飞轮——越多用户用，推荐越准；Profile 可导出（透明化增加信任）

**诊断信号：**

- 老用户仍被问"选什么风格？"
- 用户反复反馈同一个偏好（说明上次没学到）
- 第 10 个视频和第 1 个视频的体验没有明显差异

---

### P3. 主动性是品类

**对本产品意味着什么：**
不是等经纪人发照片才动，而是主动说"你上周的 listing 还没做视频，要不要现在做？"。视频完成后附带发布建议（最佳发布时间 + 平台推荐 + caption）。经纪人愿意为"帮我想着"的服务付更多钱。

**当前状态：** 7/10

- 有 Progress 推送：8 种通知类型（progress/delivered/failed/quality_blocked/stall_warning/photo_suggestion/script_preview/daily_insight）
- 有 Daily Insight：每天推送市场洞察图片（`daily_scheduler.py` + `generate_daily_insight.py`）
- 有失败通知：含 error 和 override_url（`progress_notifier.py:85-107`）
- Watchdog 告警：job 卡住 10 分钟 → `notify_stall_warning()` 推送用户，含 retry/cancel 操作（`server.py:_job_watchdog_loop`）
- 细粒度进度提示：Step 3/4/5 各有独立 `notify_progress` 推送（"Planning camera moves..."/"Generating AI video clips..."/"Assembling..."）
- 交付附带 caption：`script.get("caption")` 流入 `notify_delivered`
- **但**：无 ETA（用户不知道还要等多久）
- **但**：watchdog 只警告一次，无升级机制

**演进路径：**

- **Phase 1（MVP）**：~~job 卡住 15 分钟 → 主动告警；视频完成 → 附带 caption + hashtags + 发布时间建议~~ ✅ 已完成
- **Phase 2（PMF）**：基于经纪人 listing 状态主动建议"该做视频了"；周报：本周内容表现
- **Phase 3（规模化）**：预测性需求（新 listing → 自动准备视频草稿等确认）；智能排期

**诊断信号：**

- 用户必须主动检查 job 状态
- 失败后用户空等无人告知
- 系统只在被问时才回应
- 视频交付后无任何后续建议

---

### P4. 协作者非执行器

**对本产品意味着什么：**
经纪人发了 5 张全是外观的暗光照片，系统应该说"这些照片光线不足，建议补充室内照片或换个角度"，而不是硬做一个质量很差的视频。SOUL.md 定义了"有主见的制片人"——代码要配得上这个人格。

**当前状态：** 7/10

- SOUL.md 定义了"Opinionated producer"人格
- analyze_photos 有质量评分和 `ai_video_worthy` 标记
- Quality Gate 在 critical 时阻止 pipeline
- 低质/缺失照片 → `notify_photo_suggestion()` 主动建议补充（非阻塞，不影响 pipeline）
- Step 2 后推送 `notify_script_preview()`：hook/walkthrough/closer + 场景结构，用户可发 feedback 触发 revision
- 风格自动推荐：基于物业 `estimated_tier`（luxury→elegant, starter→energetic），仅在无 profile 且未主动选择时生效
- **但**：失败后只报错，不提建议（如"用幻灯片模式？"或"换张照片？"）
- **但**：不提供多方案选择

**演进路径：**

- **Phase 1（MVP）**：~~低质照片主动建议补充；风格自动推荐；脚本预览~~ ✅ 已完成
- **Phase 2（PMF）**：多方案建议（"A 风格或 B 风格，我推荐 A 因为..."）；修改时解释 trade-off
- **Phase 3（规模化）**：成为真正的创意伙伴——基于市场趋势建议内容策略

**诊断信号：**

- 低质输入产出低质视频却无人提醒
- 用户从不收到来自 Agent 的建议
- Agent 行为和 SOUL.md 描述不一致
- reviewer 评分低但视频仍被交付

---

### P5. 减负 > 加功能

**对本产品意味着什么：**
经纪人发照片到收到视频，理想状态是 0 个问题。她在车里，手机操作，每一步摩擦都是流失。当前新用户需要 3 次交互才能开始生成，有 Profile 的用户 1 次——目标是所有人都 1 次。

**当前状态：** 8/10

- 有 Profile 的用户：发照片 → 自动识别风格 → 直接开始（1 步）
- 4 个参数有智能默认值（`server.py:540-585`）
- Intent 分类器自动路由，无需手动选菜单（`server.py:843-1006`）
- Console 表单预创建 Profile，减少首次摩擦
- 新用户风格自动推荐：`_recommend_style()` 基于 `estimated_tier` 推荐（无需手动选）
- **但**：不从照片 EXIF 自动提取地址/时间

**演进路径：**

- **Phase 1（MVP）**：~~首次用户也 1 步交互（物业类型自动推荐风格）~~ ✅ 已完成
- **Phase 2（PMF）**：从 EXIF 提取地址/时间；从 MLS 自动拉 listing 信息
- **Phase 3（规模化）**：0 步交互——拍照自动触发、完成后自动发布到预设平台

**诊断信号：**

- 新用户首视频需要 > 2 次交互
- 用户中途放弃（发了照片但没完成流程）
- 每个 job 的参数填写量在增加而非减少

---

### P6. 成长可感知

**对本产品意味着什么：**
P2 让系统记住经纪人的偏好，P6 让经纪人**感受到**系统在变好。第 10 个视频应该比第 1 个明显更快、更准、更少问题。经纪人应该能说出"它越来越懂我了"——这是真正的迁移成本。

**当前状态：** 5/10

- Profile 追踪 + 个性化 Creative Brief（`profile_manager.py`）
- `get_preference_context()` 注入偏好到 prompt
- Daily Insight 个性化（市场区域、语言、品牌色）
- 正向反馈闭环：非重试 job 交付 → `record_positive_signal()` 强化 `style_confirmed`（`dispatcher.py` delivery 路径）
- **但**：无关系里程碑（第 1 个视频 vs 第 50 个视频交互完全一样）
- **但**：系统进步不可见——用户不知道"我学到了什么"
- **但**：无"越用越快"的感知（实际速度可能更快了，但没告诉用户）

**演进路径：**

- **Phase 1（MVP）**：里程碑消息（第 1/5/20 个视频时特殊反馈：如"这是你的第 5 个视频，我已经学会了你偏好 elegant 风格"）；~~正向反馈闭环（用户不改 = 强化信号）~~ ✅ 已完成
- **Phase 2（PMF）**：每次交付附带"本次优化点"（如"这次我没问你风格，因为你上次选了 elegant"）；速度/质量趋势可视化
- **Phase 3（规模化）**：个性化进步报告（月度总结：做了多少视频、风格如何演变、节省了多少时间）

**诊断信号：**

- 老用户和新用户体验一样
- 用户感觉不到系统在进步
- 没有"我学到了什么"的主动反馈

---

## 架构实现原则（A1-A8）在 Reel Agent 的落地

---

### A1. 协议与工具优先

**当前状态：** 7/10

- Pipeline 每步都是独立可调用的 Python 脚本，支持双模（`build_*_request()` + `run()`）
- 每步输出结构化 JSON：`analysis.json`, `scenes.json`, `script.json`, `prompts.json`
- API 端点结构化：`/api/generate`, `/api/status/{job_id}`, `/webhook/in`
- **差距**：错误返回不够结构化（部分是自然语言）；`_classify_intent` 大量硬编码文本匹配

**Phase 1**：统一错误响应格式（error_code + message + retry_suggestion）
**Phase 2**：Intent 分类用 Claude 替代硬编码匹配

---

### A2. 闭环优先

**当前状态：** 8/10

- 状态机完整：QUEUED → ANALYZING → ... → DELIVERED / FAILED / CANCELLED
- 每步 checkpoint 持久化到 SQLite + 文件系统
- 支持从任意步骤恢复（`revision_context.re_run_from`）
- Feedback → Classification → 定向重跑 → 记忆更新
- 8 种通知类型覆盖完整生命周期：progress / delivered / failed / quality_blocked / stall_warning / photo_suggestion / script_preview / daily_insight
- 三类必通知事件已对齐——**完成** ✅ / **卡住** ✅（watchdog 10 分钟告警）/ **建议** ✅（照片建议 + 脚本预览）
- 交付附带 caption（`script.get("caption")` 流入 `notify_delivered`）
- **差距**：无中途暂停（用户不能说"停，我想改脚本"——脚本预览是推送，非门控）
- **差距**：交付时不附带"本次优化点"（P6 成长感知的依赖）

**Phase 1**：~~脚本预览门（Step 2 后可暂停）；卡住 15 分钟 → 主动告警~~ ✅ 已完成
**Phase 2**：每次交付附带质量自评 + 建议 + "本次我学到了什么"；中途暂停能力

---

### A3. 上下文分层

**当前状态：** 7/10

- 永久规则层：CLAUDE.md + SOUL.md + AGENTS.md + SKILL.md
- Skill 层：`refer/` 目录的 prompt 模板 + `templates/` 风格参数
- 任务层：`job_params` + `analysis.json` + `scenes.json`
- 环境层：`.env` 配置的 API 权限 + IMA/TTS 引擎选择
- `preference_context` 多点注入：`plan_scenes`（`<agent_preferences>` XML 标签 via property_info）+ `generate_script`（独立参数）
- **差距**：per-agent Creative Brief 存在但利用不充分
- **差距**：无上下文生命周期管理——Profile 偏好可能过期（用户口味变了但系统还用旧偏好）
- **差距**：bridge state 文件无 staleness 检查（可能读到小时前的数据）
- **差距**：层间冲突无处理——任务层参数和 Profile 偏好矛盾时谁优先？

**Phase 1**：~~preference_context 分发到所有 Claude 调用点~~ ✅ 已完成；bridge state 加 staleness 检查（>10min 视为过期）
**Phase 2**：动态上下文裁剪；层间冲突规则（任务层 > Profile 层，安全规则不可覆盖）

---

### A4. 验证与安全优先

**当前状态：** 8/10

- 有 Quality Gate（7 个检查点）和 Auto-Retry
- 有 video_diagnostics 五层诊断框架
- 有 review_video 自动评分（Claude Vision + OpenCV）
- Bearer Token 认证改为必须：`REEL_AGENT_TOKEN` 未设 → 拒绝所有 auth 请求（`server.py:_require_backend_auth`）
- Token 比较使用 `hmac.compare_digest()` 防时序攻击
- `/api/generate` 和 `/webhook/manual-override` 已加 auth 保护
- 启动时检查 token 配置，未设则 WARNING 日志
- Review 评分 < `DELIVERY_BLOCK_THRESHOLD`（默认 4.0）→ 阻止交付，推送用户三选一（重试/降级交付/取消）
- **差距**：无审计日志；无人工确认门；`/api/profile/{phone}` 和 admin 路由认证仍可选

**Phase 1**：~~认证改为必须；review 评分 < 阈值时阻止交付~~ ✅ 已完成
**Phase 2**：操作审计日志表；人工确认门（高风险操作）；admin 认证硬化

---

### A5. 职责分层

**当前状态：** 8/10

- Pipeline 6 步职责清晰：分析 → 剧本 → 分镜 → 生成 → 组装 → 审片
- 步骤间松耦合，可独立重跑
- Feedback Classifier 独立于 Dispatcher
- Reviewer 从"诊断者"升级为"门卫"：评分 < 阈值 → 阻止交付（`dispatcher.py` delivery gate）
- 两级阈值分离：`AUTO_RETRY_THRESHOLD`（6.5，触发重试）vs `DELIVERY_BLOCK_THRESHOLD`（4.0，阻止交付）
- 质量阻断通知独立方法 `notify_quality_blocked()`，不复用 `notify_failed()`
- **差距**：无"质量仲裁"角色（多个 reviewer 投票）

**Phase 1**：~~Review 评分 < 阈值 → 阻止交付（独立验证变为 gate）~~ ✅ 已完成
**Phase 2**：引入质量仲裁机制

---

### A6. 成本写进架构

**当前状态：** 7/10

- 步骤缓存：revision 重用 parent_job 的 analysis/scenes/script
- 并行执行：Step 2 和 Step 4 用 asyncio.gather
- Prompt Caching：plan_scenes 已用 `cache_control: ephemeral`
- IMA credit 全链路记录：render + TTS → dispatcher 聚合 → `job_manager.add_cost()` 持久化到 `cost_usd` 字段
- IMA 上传缓存：md5→URL 进程级缓存，相同照片不重复上传（`ima_client.py`）
- Auto-retry 成本上限：`JOB_COST_LIMIT_CREDIT` 环境变量（默认 200 credit），超限跳过重试
- Job summary 日志包含 `cost_credit` 字段
- **差距**：Claude API token 计数未追踪（Phase 2，需 SDK 改造）
- **差距**：write_video_prompts 的 batch_async 未启用
- **差距**：无 per-job 成本仪表盘（Console 可视化）

**Phase 1**：~~每次 API 调用记录 token/cost；IMA 上传缓存（md5→URL）；auto-retry 成本上限~~ ✅ 已完成
**Phase 2**：Claude API token 追踪；per-job 成本仪表盘；低价值场景自动用低成本引擎

---

### A7. 先做高频高价值

**当前状态：** 8/10

- 核心链路已打穿：照片 → 视频（最高频最高价值）
- 未在核心链路上堆砌不必要功能
- **差距**：Daily Insight 分散了注意力（是增值还是分心？）

**Phase 1**：确保核心视频链路的可靠性和速度达标后，再扩展 Daily Insight
**Phase 2**：基于用户数据判断哪些增值功能真正被使用

---

### A8. 可观测优先

**当前状态：** 6/10

- 有 `JobLogger` per-job 日志（`job_logger.py`），写 `run.jsonl`
- 有 `video_diagnostics.py` 生成 `diagnostics.json`
- 有五层诊断框架（CLAUDE.md）
- 结构化审计日志（`reel_agent.audit`）：auth 结果、job 创建、intent 分类、bridge state 读取 → JSON 格式写 stderr，生产可接 CloudWatch/Datadog
- `/api/status/{job_id}` 增强：`elapsed_seconds` + `step_elapsed_seconds` + `params_summary` + 终态停表
- **差距**：无异常告警通道——日志写文件等人翻，不主动告警（需接外部告警系统）
- **差距**：无趋势追踪——不知道成功率/速度/成本是在变好还是变差
- **差距**：P6 成长感知的前提（量化进步）部分依赖 A8 的趋势数据

**Phase 1**：~~关键路径加结构化日志；`/api/status/{job_id}` 返回当前步骤 + 耗时~~ ✅ 已完成
**Phase 2**：per-user 趋势仪表盘（速度/质量/成本）；异常告警推送（job 卡住 > 15min → Slack/webhook）

---

## 初创期三问（做任何优化前先问）

1. **会不会让用户拿不到视频？** → P1 可靠性（生存底线）
2. **会不会让用户觉得"它不懂我"？** → P2 记忆 + P4 协作（体验差异）
3. **会不会让我们烧穿？** → A6 成本（活下来）

---

## 总评分与优先级

| 原则        | 当前 | 目标 | 优先级                    | 备注            |
| ----------- | ---- | ---- | ------------------------- | --------------- |
| P1 可靠     | 8    | 9    | **最高** — 信任底线       | Batch 1 完成 ↑2 |
| P2 记忆     | 8    | 9    | 高 — 差异化核心           | Batch 4 完成 ↑1 |
| P3 主动     | 7    | 7    | 中 — 品类升级             | Batch 4 完成 ↑3 |
| P4 协作     | 7    | 7    | **高** — 当前最大体验缺口 | Batch 3 完成 ↑3 |
| P5 减负     | 8    | 9    | 中 — 已经不错             | Batch 3 完成 ↑1 |
| P6 成长感知 | 5    | 8    | 中 — 长期壁垒             | Batch 4 完成 ↑1 |
| A1 协议     | 7    | 8    | 低 — 已经不错             |                 |
| A2 闭环     | 8    | 9    | **高** — 异步通知缺两类   | Batch 4 完成 ↑1 |
| A3 上下文   | 7    | 8    | 中 — 缺生命周期管理       | Batch 4 完成 ↑1 |
| A4 验证     | 8    | 8    | **高** — 安全底线         | Batch 2 完成 ↑3 |
| A5 职责     | 8    | 8    | 中 — reviewer 需升级      | Batch 2 完成 ↑1 |
| A6 成本     | 7    | 8    | **高** — 生存问题         | Batch 1 完成 ↑2 |
| A7 高频     | 8    | 9    | 低 — 已经聚焦             |                 |
| A8 可观测   | 6    | 8    | **高** — P3/P6 的前提     | Batch 5 完成 ↑3 |

---

## 与其他文档的关系

| 文档                            | 职责                    | 与本文档的关系                                 |
| ------------------------------- | ----------------------- | ---------------------------------------------- |
| `~/.claude/AGENT_PRINCIPLES.md` | 全局通用原则 v1.1       | 本文档是它的项目级映射                         |
| `CLAUDE.md`                     | 技术架构约束 + 诊断框架 | 本文档说"为什么"，CLAUDE 说"怎么做"            |
| `SOUL.md`                       | Agent 人格定义          | P4 协作者原则是 SOUL 的验收标准                |
| `AGENTS.md`                     | Agent 行为规则 + 状态机 | P1 可靠 + A2 闭环 + A5 职责约束 AGENTS 的实现  |
| `SKILL.md`                      | Skill KPI 定义          | 本文档为 KPI 提供"这个 KPI 为什么重要"的上下文 |

### P6 成长感知的架构依赖链

P6 没有独立的 A 原则支撑，它的落地依赖三条原则同时到位：

```
A8 可观测（量化进步：速度/质量趋势）
  + A2 闭环（交付时告诉用户"本次优化点"）
  + P2 记忆（记住了什么、学到了什么）
  = P6 成长可感知
```

任何一条缺了，P6 就是空话。当前 A8=6（结构化日志 + 增强状态接口），A2=8（通知链已对齐），P2=8（记忆 + 正向反馈已完成）→ P6 仍缺里程碑消息和趋势可视化。

---

_v1.4 — 2026-04-01 — Phase 2 Batch 5 可观测基座：A8 3→6_
_v1.3 — 2026-04-01 — Phase 1 四批全部完成：P3 4→7、P2 7→8、P6 4→5、A2 7→8、A3 6→7_
_v1.2 — 2026-04-01 — Batch 1 可靠性基座完成：P1 6→8、A6 5→7_
_v1.1 — 2026-04-01 — 对齐全局 AGENT_PRINCIPLES.md v1.1：重构 P6 成长感知、新增 A8 可观测、扩展 A2 异步闭环、补充 A3 生命周期_
_v1.0 — 2026-04-01 — 基于全局 AGENT_PRINCIPLES.md v1.0 映射_
