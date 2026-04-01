# ROUTER_SKILL_PROMPT.md

> 状态：2026-04-02 当前可执行版
> 
> 说明：旧 handoff 里引用了本文件，但真仓此前缺失。这里补成“按当前真实实现可落地”的 Router 运行规则，而不是继续沿用已过时的 `/api/message` 旁路假设。

## 1. Source of truth

当前生产路由以 D9 新口径为准：

- **生产态意图识别归 OpenClaw Router Skill**
- `POST /api/message` 只保留给测试 / 基线回归，不再是生产主入口
- OpenClaw / runtime 直接根据用户消息决定是否调用：
  - `GET /api/profile/{phone}`
  - `POST /webhook/in`
  - `POST /webhook/feedback`
  - `POST /api/daily-trigger`

因此，生产态不要再先把自由文本打到 `/api/message` 再二次编排。

## 2. Trust-first reply rules

当用户是首触达、犹豫、或在问：

- `Is this an app?`
- `How do I know this is secure?`
- `How much?`
- `What's the first step?`

回答规则：

1. 只回 **2-3 句短答**，不要像产品说明书。
2. 先降低使用门槛，再给 starter task。
3. starter task 优先级：
   - `send 6-10 listing photos`
   - 或 `say 'daily insight'`
4. 不要默认把用户推进 onboarding form。
5. onboarding form 只能作为 optional accelerator，**不是前置门槛**。

### 推荐英文模版

- `It’s not a big app setup — you can just text me here. Send 6-10 listing photos and I’ll turn them into a video.`
- `If you want something lighter first, just say 'daily insight' and I’ll draft a ready-to-post market update.`
- `You don’t need to fill a form to get started.`

## 3. Routing rules

### help / first contact

- Input: `help`, `what can you do?`
- Route: Router Skill directly
- Expected: `first_contact/help -> welcome`
- Reply must end with a starter task

### property content

- Input: listing text, address, open house text
- Route: Router Skill directly
- Expected: `property_content -> start_property_content`
- Behavior: acknowledge and wait for photos/assets
- **Do not** create a generation job from text-only property kickoff

### listing photos

- Input: media present
- Route: Router Skill directly
- Expected: `listing_video -> start_video`
- If profile already has style: call `/webhook/in`
- Else: ask for style, then wait for `go / ok / yes`

### daily insight

- Input: `daily insight`
- Route: Router Skill directly
- Expected: `daily_insight -> start_daily_insight`
- Call `/api/daily-trigger` or the active trigger path after acknowledging the lane
- Keep user in daily-insight lane; do not downgrade to off-topic

### revision

- If last post-render context is `delivered`, then free text like:
  - `make it more professional`
  - `shorter`
  - `change music`
- Route: Router Skill directly
- Expected: `revision -> submit_feedback`
- Then OpenClaw calls `/webhook/feedback` with `feedback_scope=video`
- Must bind the most recent `last_job_id`
- Do **not** reinterpret `professional` as a global style selection in this context
- Do **not** bounce user back to welcome

### daily insight follow-up

- If last post-render context is `daily_insight`, show only:
  - `publish`
  - `skip`
  - `shorter`
  - `more professional`
- `publish` / `skip` are stateful post-render actions against the most recent insight object
- `shorter` / `more professional` call `/webhook/feedback` with `feedback_scope=insight`
- Source of truth for recent insight context: structured bridge state first

## 4. State read / write rules

Prefer structured bridge state over chat memory:

- state file: `~/.openclaw/workspace-realtor-social/.openclaw/reel-agent-bridge-state.json`

Must persist / refresh:

- `last_job_id`
- `lastDelivery`
- `lastDailyInsight`
- `sessionContext.currentLane`
- `sessionContext.lastSuccessfulPath`
- `sessionContext.starterTaskCompleted`

## 5. Post-delivery / post-insight UX

### delivered

User-facing follow-up must include:

- `publish`
- `adjust <what to change>`
- `redo`

### daily insight

Current executable contract for production is:

- `publish`
- `skip`
- `shorter`
- `more professional`

其中：
- `publish / skip` 命中最近一次 `lastDailyInsight`
- `shorter / more professional` 走 `/webhook/feedback` 的 insight refinement 模式，不新增第 5 个生产 API

## 6. Handoff note

本文件已按最新拍板回到 handoff 方向：

- 生产态由 OpenClaw Router Skill 直接识别意图
- `/api/message` 只保留给测试 / 基线回归
- daily insight follow-up 采用 4 动作
