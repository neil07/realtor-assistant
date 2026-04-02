# Reel Agent 2.0 Telegram 体验 Walkthrough

> 用途：在通知人工进 Telegram 体验前，先把放行门槛、演示顺序、预期结果统一成一份可执行 checklist。

## 1. Go / No-Go 预检

全部满足才允许通知人工去 Telegram：

- [ ] G1 OpenClaw Router Skill owns inbound intent recognition and calls production APIs directly
  - **Status:** Router Skill prompt ready (`doc/openclaw/ROUTER_SKILL_PROMPT.md`). Pending: deploy to mini runtime.
- [ ] G2 OpenClaw side can call `/webhook/in` and `/webhook/feedback` with valid Bearer token
  - **Status:** Backend APIs fully implemented and tested (49 tests passing). Pending: mini-side HTTP client setup.
- [ ] G3 OpenClaw side owns a business callback target such as `"$OPENCLAW_CALLBACK_BASE_URL"/events`
  - **Status:** Callback contract documented (`doc/openclaw/CALLBACK_RENDERING.md`). Pending: bridge route implementation on mini.
- [ ] G4 `progress / delivered / failed / daily_insight` can be consumed and rendered in Telegram
  - **Status:** Rendering rules documented (`doc/openclaw/CALLBACK_RENDERING.md`). Pending: mini-side render implementation.
- [ ] G5 OpenClaw side stores and refreshes `last_job_id` for revision matching
  - **Status:** Session state management rules defined in Router Skill prompt. Pending: mini-side implementation.
- [x] G6 Reel Agent backend local or deployed endpoint is reachable and production APIs respond as expected
  - **Status:** All 4 production APIs implemented — `/webhook/in`, `/webhook/feedback`, `/api/profile/{phone}`, `/api/daily-trigger`. 49 tests green.

Current implementation target:

- bridge route: `POST http://127.0.0.1:18789/reel-agent/events`
- bridge auth: `X-Reel-Secret: $OPENCLAW_CALLBACK_SECRET`
- structured state mirror: `~/.openclaw/workspace-realtor-social/.openclaw/reel-agent-bridge-state.json`

No-Go rules:

- Do not notify manual Telegram testing if `callback_url` still points at `/telegram-webhook`
- Do not notify manual Telegram testing if docs still rely on `/api/sessions/main/messages`
- Do not notify manual Telegram testing if delivered events have no user-facing render plan

## 2. 用户侧演示顺序

### T1. Help / 首触达

User sends:

```text
help
```

Expected:

- Bot replies with capability framing
- New user → `first_contact / welcome`
- Returning user → `help / welcome`

### T2. Property content kickoff

User sends:

```text
123 Main St open house this Sunday 2pm
```

Expected:

- Bot acknowledges property-content lane
- Bot explicitly asks user to send photos or richer assets

### T3. Listing photos

User sends:

- 3-8 property photos

Expected:

- If style already exists → OpenClaw calls `/webhook/in` immediately
- If style is missing → bot asks for style, then waits for `go / ok / yes`
- Returned `job_id` is stored as `last_job_id`

### T4. Processing updates

Expected Telegram user-facing progress messages from backend callbacks:

- `Analyzing your photos...`
- `Writing the voiceover script...`
- `Generating AI video clips...`
- `Your listing video is ready!`

### T5. Delivery render

Expected delivered render:

- video or video URL
- caption
- follow-up controls:
  - `publish`
  - `adjust`
  - `redo`

### T6. Revision

User sends:

```text
make the music more upbeat
```

Expected:

- OpenClaw identifies revision against `last_job_id`
- OpenClaw calls `/webhook/feedback`
- Bot acknowledges re-processing

### T7. Daily insight

Two acceptable demo paths:

1. User sends `daily insight`
2. Backend or scheduler pushes a `daily_insight` event

Expected render:

- branded image
- caption
- follow-up controls:
  - `publish`
  - `skip`

### T8. Daily push controls

User sends:

```text
stop push
resume push
```

Expected:

- `stop push` → `disable_daily_push`
- `resume push` → `enable_daily_push`
- Bot confirms the setting change

## 3. Telegram 体验通过标准

这轮 walkthrough 通过，至少满足：

1. `help`
2. `property content`
3. photo-triggered generation
4. delivered render
5. revision
6. daily insight or daily push control

## 4. 当前建议

在 `G1-G6` 全绿之前，保持项目侧继续施工和接线，不通知人工进 Telegram。

**当前进度（2026-04-01）：**

- G6 已绿（后端全部就绪）
- G1-G5 的前置文档已全部产出，待 mini 侧部署：
  - `doc/openclaw/ROUTER_SKILL_PROMPT.md` — 完整 Router Skill system prompt
  - `doc/openclaw/CALLBACK_RENDERING.md` — Callback 渲染规范
  - `doc/openclaw/OPS_CONTEXT_SPEC.md` — Session context 回流规范
- 下一步：在 mini 机上部署 Router Skill prompt，实现 bridge route，跑通 T1-T8
