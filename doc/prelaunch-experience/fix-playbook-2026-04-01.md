# Reel Agent 体验问题修复指引

> 这份文档回答两个问题：
>
> 1. 体验报告怎么指导实际开发
> 2. 如果让 Codex 直接来修，应该怎么拆批次、怎么验收

关联文档：

- `doc/prelaunch-experience/business-walkthrough-2026-04-01.md`
- `doc/prelaunch-experience/report-2026-04-01.md`
- `doc/prelaunch-experience/scoring-2026-04-01.csv`

---

## 1. 怎么用这份报告指导开发

不要把这份报告当“阅读材料”，而要把它当一个修复队列。

### 读法

每个问题都看 5 件事：

1. `环节`

- 用户卡在哪一环
- 是入口、首试、修订、留存，还是后台问题

2. `case`

- 是哪个真实 case 暴露出来的
- 用户原话和系统实际反应是什么

3. `严重级别`

- `P0`：上线前必须修
- `P1`：首批试点前应该修
- `P2`：可以排到下一轮

4. `归属层`

- `backend`
- `console / frontend`
- `OpenClaw orchestration`
- `shared contract`

5. `验收方式`

- 修完以后应该重新跑哪个 case
- 什么结果才算真的修好

### 不要这样用

- 不要只看“感觉有问题”，不看 case
- 不要只改文案，不改路由或契约
- 不要只修 backend，不看 OpenClaw 是否还在展示错误按钮
- 不要只追求测试通过，不回放真实起手 case

---

## 2. 修复优先级

### 第一批：必须先修

这批决定能不能进入真实联调。

1. trust-first 问题

- 包括：
  - `Is this an app?`
  - `How do I know this is secure and not spam?`
  - `How much per month?`
  - `tell me the first step`
- 目标：
  - 不再回通用 welcome
  - 每类问题都给一个短回答 + 一个明确下一步

2. refinement / revision 契约

- 包括：
  - `shorter`
  - `more professional`
  - `make it more professional`
- 目标：
  - 用户看到的命令都能真正执行
  - delivered 后自由文本先走 revision，不被 style selection 劫持

3. insight callback payload

- 包括：
  - `daily_insight` callback schema
  - `headline/caption/hashtags/image_urls` 必填字段
- 目标：
  - pytest 失败项消失
  - OpenClaw 能稳定拿到完整可渲染 payload

### 第二批：试点前应该修

1. onboarding 从门槛改成加速器
2. video-first 首次发图减一步
3. ops dashboard / client detail 补推荐路径和下一步动作
4. interview-first starter task 落地

### 第三批：后续增强

1. landing page 真实现
2. path history / growth 可视化
3. 更轻的 Skill brief 编辑体验

---

## 3. 如果让 Codex 来修，建议怎么分 4 个开发批次

### 批次 A：消息入口与 trust-first

这是最适合先交给 Codex 的一批，因为影响面集中、验证也直接。

#### 要改什么

- `server.py`
  - 增加 trust/setup/pricing/first-step intents
  - 调整 `_classify_intent()` 判断顺序
  - 为这些 intent 生成更短、更像助手的 response
- `tests/test_message_routing.py`
  - 新增对应 case
- `tests/test_openclaw_mock_integration.py`
  - 增加 `/api/message` HTTP 级别断言
- `doc/openclaw/AGENTS.md`
  - 更新 intent/action contract

#### 验收标准

- `Is this an app?` 不再回 welcome
- `How do I know this is secure and not spam?` 不再回 welcome
- `How much per month?` 不再回 welcome
- `I do not know these tools, tell me the first step` 不再回 welcome
- 重跑：
  - `INIT-E1-A2-01`
  - `INIT-E1-A3-01`
  - `INIT-E4-A7-01`
  - `PROBE-FIRSTSTEP-01`

#### 交付给 Codex 的一句话任务

“修 `/api/message` 的 trust-first 路由，把 app/security/pricing/first-step 这 4 类问题从通用 welcome 中拆出来，并补测试与 OpenClaw contract 文档。”

---

### 批次 B：refinement / revision 闭环

这是第二优先级，因为它直接影响“像不像助手”。

#### 要改什么

- `server.py`
  - delivered / daily insight context 下先判断 refinement/revision
  - style keyword 不再抢占 delivered 后自然语言修改
  - 如果暂时不支持某 refinement，就不要再返回对应 hints
- `tests/test_message_routing.py`
  - 补 `shorter`
  - 补 `more professional`
  - 补 `make it more professional`
- `doc/openclaw/AGENTS.md`
  - 删掉或更新 unsupported text commands

#### 验收标准

- `shorter` 在 insight context 下不再 `off_topic / reject`
- `make it more professional` 在 delivered context 下不再 `style_selection / set_style`
- OpenClaw-facing hints 与实际 behavior 一致

#### 交付给 Codex 的一句话任务

“修 delivered/insight context 下的 refinement 与 revision 识别顺序，确保用户可见命令和真实行为一致，并补对应测试。”

---

### 批次 C：onboarding 与首次价值减负

这批既有 console，也有 OpenClaw 联动。

#### 要改什么

- `console/router.py`
  - 重写 onboarding invite message
- `console/templates/onboarding_form.html`
  - 改标题和 framing
- `console/templates/form_done.html`
  - 给出双 CTA，不只推视频
- `doc/openclaw/AGENTS.md` 或 OpenClaw 侧逻辑
  - 对 skeptical 用户优先走 skip-the-form starter task

#### 验收标准

- onboarding 不再被描述成试用前置门槛
- form completion 后有明确下一步
- 可以同时引导视频和 insight

#### 交付给 Codex 的一句话任务

“把 onboarding 从 setup gate 改成 optional accelerator，重写表单前后文案和 completion CTA，并保留 skip-the-form 首试路径。”

---

### 批次 D：operator 推荐路径

这批更偏产品/后台能力，但对试点很关键。

#### 要改什么

- `console/memory_schema.py`
  - 在 readiness 之外补推荐路径逻辑
- `console/router.py`
  - 计算并传入 `recommended_path`、`next_best_action`
- `console/templates/dashboard.html`
  - 展示每个客户的推荐路径
- `console/templates/client_detail.html`
  - 先显示下一步动作，再显示缺失字段

#### 验收标准

- dashboard 能回答“这个用户先推视频、资讯还是访谈”
- client detail 能回答“我现在最该推进什么”

#### 交付给 Codex 的一句话任务

“给 ops console 增加 recommended path 和 next-best-action，让后台从状态台变成动作台。”

---

## 4. 一条问题怎么转成开发任务

用下面这个格式最实用：

### 例子：`INIT-E1-A3-01` 安全问题被回 welcome

#### 产品问题

用户在第一句问“安全吗 / 会不会是 spam”，系统没有直接回答，容易马上流失。

#### 真实 case

- 输入：`How do I know this is secure and not spam?`
- 当前返回：`first_contact / welcome`

#### 修复目标

- 系统必须正面回答这个 trust 问题
- 回答长度要短
- 回答完要给一个单一下一步

#### 改动范围

- `backend`
  - 新增 `trust_question` intent
- `OpenClaw`
  - 调整 trust-first reply 呈现，不要像说明书
- `tests`
  - 补 message routing 和 HTTP 集成断言

#### 验收

- 重跑 case，返回不再是 `welcome`
- response 中必须包含 trust answer
- response 中必须有单一下一步

---

## 5. 如果你要直接让我修，怎么下指令最有效

最好的方式不是说“把报告里的问题都修掉”，而是一次只给一个批次。

### 好的指令方式

- “先修 trust-first 入口：app/security/pricing/first-step 这 4 类问题，改 backend 和测试，OpenClaw 文档同步更新。”
- “修 insight/video refinement 契约，只处理 `/api/message` 和 OpenClaw hints，不动 console。”
- “修 onboarding 的产品 framing，只改 console 模板和 invite message，不碰消息路由。”
- “给 ops console 加 recommended path 和 next-best-action。”

### 为什么这样最好

- 范围清楚
- 回归测试清楚
- 不会把 backend / OpenClaw / console 混成一锅
- 每次修完都能马上回放对应 case

---

## 6. 我建议的实际修复顺序

如果你现在就要我开始修，我建议按这个顺序：

1. `批次 A：trust-first 消息入口`
2. `批次 B：refinement / revision 闭环`
3. `批次 C：onboarding 减负`
4. `批次 D：operator 推荐路径`

原因很简单：

- A/B 先修，才能把真实用户对话入口稳定住
- C 再修，才能把激活率拉起来
- D 最后修，才能让团队运营跟得上

---

## 7. 一句话版本

这份报告最正确的用法，是把每个问题当成一个“有 case、有归属层、有验收标准”的开发任务，而不是一份泛泛的体验总结。

如果让我来修，最适合从 `trust-first` 和 `refinement/revision` 两批开始。
