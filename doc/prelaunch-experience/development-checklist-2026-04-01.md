# Reel Agent 体验修复开发交接清单

> 用途：把这轮压测后的问题、当前已完成修复、待 Claude 继续处理的 OpenClaw runtime 工作、以及必须回到 mini 机上做的真实联调事项，整理成一份可执行 checklist。
>
> 适用对象：
>
> - Claude Code：继续做 OpenClaw runtime / orchestration / 真实接线
> - 本仓库开发者：继续做 backend / console / 文档 / 验证
> - mini 机执行者：做真实 bridge、Telegram、runtime 环境验证

---

## 1. Claude 先读这些材料

### 体验报告

- [预上线体验正式报告](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/prelaunch-experience/report-2026-04-01.md)
- [产品视角全业务链路走查](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/prelaunch-experience/business-walkthrough-2026-04-01.md)
- [修复指引 / fix playbook](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/prelaunch-experience/fix-playbook-2026-04-01.md)
- [评分结果 CSV](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/prelaunch-experience/scoring-2026-04-01.csv)

### 关键证据

- [HTTP 原始证据 JSONL](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/prelaunch-experience/evidence/2026-04-01/http-evidence.jsonl)
- [HTTP 摘要 CSV](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/prelaunch-experience/evidence/2026-04-01/http-summary.csv)
- [baseline tests 结果](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/prelaunch-experience/evidence/2026-04-01/baseline-tests.json)
- [manual review 记录](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/prelaunch-experience/evidence/2026-04-01/manual-review-notes.md)

### 当前接线与边界文档

- [D9 决策](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/DECISIONS.md)
- [当前 PRD](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/PRD.md)
- [OpenClaw AGENTS 契约](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/openclaw/AGENTS.md)
- [OpenClaw SKILL 契约](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/openclaw/SKILL.md)
- [OpenClaw 真实联调脚本](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/openclaw/REAL_INTEGRATION.md)
- [OpenClaw Telegram walkthrough](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/openclaw/TELEGRAM_WALKTHROUGH.md)

---

## 2. 当前边界结论

- **D9 已成立**：生产态意图识别归 OpenClaw Router Skill。
- 本仓库后端不再作为生产对话路由主入口。
- `POST /api/message` 和 `POST /api/router-test` 现在只作为：
  - prelaunch audit
  - regression baseline
  - no-OpenClaw 本地测试桩
- 生产态 OpenClaw 应直接调用：
  - `GET /api/profile/{phone}`
  - `POST /webhook/in`
  - `POST /webhook/feedback`
  - `POST /api/daily-trigger`

---

## 3. 已完成修复（当前仓库，已落地）

### A. daily insight callback 契约

- [x] `ProgressNotifier.notify_daily_insight()` 已兼容 flat shape
- [x] `ProgressNotifier.notify_daily_insight()` 已兼容 v2 content-pack shape
- [x] 已补测试覆盖 flat + v2 两种 payload

关键文件：

- [orchestrator/progress_notifier.py](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/orchestrator/progress_notifier.py)
- [tests/test_openclaw_mock_integration.py](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/tests/test_openclaw_mock_integration.py)

### B. console 推荐路径与下一步动作

- [x] 增加 `recommended_path`
- [x] 增加 `next_best_action`
- [x] 增加 activation metadata 默认字段
- [x] dashboard 展示推荐路径和建议下一步
- [x] client detail 顶部展示“建议下一步”

关键文件：

- [console/memory_schema.py](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/memory_schema.py)
- [console/router.py](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/router.py)
- [console/templates/dashboard.html](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/templates/dashboard.html)
- [console/templates/client_detail.html](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/templates/client_detail.html)
- [skills/listing-video/scripts/profile_manager.py](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/skills/listing-video/scripts/profile_manager.py)

### C. onboarding 从门槛改成加速器

- [x] onboarding invite 文案已改成 optional accelerator
- [x] onboarding form 标题文案已改
- [x] form done 页面已提供双 CTA：
  - `Send 6-10 listing photos`
  - `Reply "daily insight"`

关键文件：

- [console/templates/onboarding.html](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/templates/onboarding.html)
- [console/templates/onboarding_form.html](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/templates/onboarding_form.html)
- [console/templates/form_done.html](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/templates/form_done.html)

### D. `/api/message` test-only 基线改进

- [x] 新增 `/api/router-test` 作为测试别名
- [x] trust-first / pricing / first-step / insight-first 自然 phrasing 的 test baseline 已补
- [x] delivered / daily insight refinement 的 test baseline 已补
- [x] 文档已经明确 `/api/message` 只用于测试，不是生产主链路

关键文件：

- [server.py](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/server.py)
- [tests/test_message_routing.py](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/tests/test_message_routing.py)
- [tests/test_openclaw_mock_integration.py](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/tests/test_openclaw_mock_integration.py)

### E. 文档已经切到 D9 口径

- [x] PRD 已改成 OpenClaw Router Skill 为生产入口
- [x] OpenClaw AGENTS / SKILL / REAL_INTEGRATION / MOCK_INTEGRATION / TELEGRAM_WALKTHROUGH 已改口径
- [x] docs index 已标明 `run_dialogue_eval.py` 是 test-only `/api/message` 压测脚本

关键文件：

- [doc/PRD.md](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/PRD.md)
- [doc/openclaw/AGENTS.md](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/openclaw/AGENTS.md)
- [doc/openclaw/SKILL.md](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/openclaw/SKILL.md)
- [doc/openclaw/MOCK_INTEGRATION.md](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/openclaw/MOCK_INTEGRATION.md)
- [doc/openclaw/REAL_INTEGRATION.md](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/openclaw/REAL_INTEGRATION.md)
- [doc/openclaw/TELEGRAM_WALKTHROUGH.md](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/openclaw/TELEGRAM_WALKTHROUGH.md)
- [docs/INDEX.md](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/docs/INDEX.md)

---

## 4. 已通过的验证

- [x] `.venv/bin/python -m pytest tests/test_message_routing.py tests/test_openclaw_mock_integration.py tests/test_console_experience.py -q`
- [x] `.venv/bin/python -m pytest tests/test_experience_assets.py -q`
- [x] `.venv/bin/python -m py_compile server.py console/router.py console/memory_schema.py orchestrator/progress_notifier.py skills/listing-video/scripts/profile_manager.py`

---

## 5. 待 Claude 继续处理（OpenClaw runtime / orchestration）

> 这些事项不应在本仓库继续修，而应由 Claude 在 OpenClaw runtime / Telegram / orchestration 那侧完成。

### A. 生产态 Router Skill 落地

- [ ] OpenClaw 不再把生产流量先打 `/api/message`
- [ ] OpenClaw 直接根据真实用户消息决定调用：
  - [ ] `GET /api/profile/{phone}`
  - [ ] `POST /webhook/in`
  - [ ] `POST /webhook/feedback`
  - [ ] `POST /api/daily-trigger`

### B. trust-first 渲染策略

- [ ] `Is this an app?`
- [ ] `How do I know this is secure and not spam?`
- [ ] `How much per month?`
- [ ] `Tell me the first step`

要求：

- [ ] 短答，不要大段说明书
- [ ] 一个 starter task
- [ ] 不要像销售话术

### C. delivered 后 revision session continuity

- [ ] delivered 后自由文本稳定绑定最近 `job_id`
- [ ] 不要把 `make it more professional` 这类话重新当成全局 style selection
- [ ] revision 会话内保持上下文，不跳回 welcome / generic setup

### D. daily insight follow-up affordance 对齐

- [ ] 只展示真正支持的 follow-up
- [ ] 当前允许：
  - [ ] `publish`
  - [ ] `skip`
  - [ ] `shorter`
  - [ ] `more professional`
- [ ] 不再展示 unsupported refinement 按钮或文案

### E. daily insight callback 渲染前校验

- [ ] 校验 `insight.headline`
- [ ] 校验 `insight.caption`
- [ ] 校验 `image_urls`
- [ ] 缺字段时走 fallback / internal alert，不直接发给用户

### F. insight-to-video handoff

- [ ] daily insight 成功后，补一个明确的视频 CTA
- [ ] 不让 insight-first 成为死胡同

### G. starter-task / interview-first runtime

- [ ] skeptical 用户先走 starter task
- [ ] 不要默认把 onboarding form 当前置门槛
- [ ] form 在 runtime 中作为 optional accelerator

### H. ops context 回流

- [ ] 若 OpenClaw 侧掌握最近成功路径或 session lane，回写到 operator 可见状态
- [ ] 至少考虑：
  - [ ] `last_successful_path`
  - [ ] `last_recommended_path`
  - [ ] 当前 session lane
  - [ ] 最近 starter task 是否完成

---

## 6. 需要回到 mini 机上解决 / 验证的事项

> 这些事情即使 Claude 完成代码，也必须在真实环境里跑。

### A. 真实 bridge / runtime / Telegram 联调

- [ ] OpenClaw runtime 真正接到 Telegram / WhatsApp 消息
- [ ] business-event bridge 真正消费：
  - [ ] `progress`
  - [ ] `delivered`
  - [ ] `failed`
  - [ ] `daily_insight`
  - [ ] `onboarding_form`
  - [ ] `form_completed`

### B. 真实 callback 落点验证

- [ ] `callback_url` 的真实落点和本地文档一致
- [ ] 不再错误指向 transport webhook
- [ ] `X-Reel-Secret` 共享密钥校验正常

### C. 真实 session / bridge state 验证

- [ ] `last_job_id` 在真实 runtime 中可持续
- [ ] `lastDailyInsight` 在真实 runtime 中可持续
- [ ] delivered → revision / daily insight → publish|skip 的上下文不中断

### D. 真实 walkthrough

- [ ] help / trust-first
- [ ] property content kickoff
- [ ] 发图生成视频
- [ ] progress 渲染
- [ ] delivered 渲染
- [ ] revision
- [ ] daily insight
- [ ] daily push 开关

参考文档：

- [doc/openclaw/REAL_INTEGRATION.md](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/openclaw/REAL_INTEGRATION.md)
- [doc/openclaw/TELEGRAM_WALKTHROUGH.md](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/openclaw/TELEGRAM_WALKTHROUGH.md)

---

## 7. 当前还留在本仓库的可选后续项

> 这些不是阻断 Claude 的前置条件，但如果继续打磨本仓库，还可以做。

- [ ] 用当前修复后的实现，重刷一版 prelaunch audit 结果
- [ ] 更新：
  - [ ] [report-2026-04-01.md](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/prelaunch-experience/report-2026-04-01.md)
  - [ ] [business-walkthrough-2026-04-01.md](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/prelaunch-experience/business-walkthrough-2026-04-01.md)
  - [ ] [scoring-2026-04-01.csv](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/prelaunch-experience/scoring-2026-04-01.csv)
- [ ] 清掉 Starlette `TemplateResponse` 的 deprecation warning
- [ ] 如果决定彻底收缩 test surface，可在后续把 `/api/message` 标记得更显式，例如在 README / runbook 里再补一句

---

## 8. 给 Claude 的一句话任务说明

可以直接这样交代：

> 先阅读体验报告、业务走查、fix playbook 和 OpenClaw 接线文档。D9 已确定：生产态意图识别归 OpenClaw Router Skill，本仓库的 `/api/message` 只是 test-only baseline。请你专注处理 OpenClaw runtime 侧的剩余问题：生产态 Router Skill 直连生产 API、trust-first 渲染、revision session continuity、daily insight affordance 对齐、callback 渲染前校验、insight-to-video handoff、starter-task/interview-first runtime，以及真实 bridge/Telegram 联调。
