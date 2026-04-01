# CALLBACK_RENDERING.md

> 状态：2026-04-02 当前 bridge 渲染规范

## Bridge contract

- Route: `POST $OPENCLAW_CALLBACK_BASE_URL/events`
- Default local route: `POST http://127.0.0.1:18789/reel-agent/events`
- Auth header: `X-Reel-Secret: $OPENCLAW_CALLBACK_SECRET`

## Supported callback types

- `progress`
- `delivered`
- `failed`
- `daily_insight`
- `onboarding_form`
- `form_completed`

## Rendering rules

### progress

Required:

- `type=progress`
- `job_id`

Optional:

- `step`
- `message`
- `agent_phone`
- `openclaw_msg_id`

User-facing render:

- concise progress text
- preserve `job_id` in bridge state as `last_job_id`

### delivered

Required:

- `type=delivered`
- `job_id`

Optional but recommended:

- `video_url` or `video_path`
- `caption`
- `scene_count`
- `word_count`
- `aspect_ratio`

User-facing render:

- video/video URL
- caption
- follow-up:
  - `publish`
  - `adjust <what to change>`
  - `redo`

State updates:

- refresh `last_job_id`
- write `lastDelivery`
- mark `sessionContext.currentLane = listing_video`
- mark `sessionContext.starterTaskCompleted = true`

### failed

Required:

- `type=failed`
- `job_id`

Optional:

- `error`
- `retry_count`
- `override_url`

User-facing render:

- failure message
- retry guidance

State updates:

- refresh `last_job_id`
- mark `sessionContext.lastPostRenderKind = failed`

### daily_insight

Required before render:

1. `insight.headline` non-empty
2. `insight.caption` non-empty
3. `image_urls` has at least one non-empty entry

If any required field is missing:

- **do not render to user**
- return 400 / internal error at bridge
- treat as an ops-visible callback contract failure

Recommended payload:

- `agent_phone`
- `agent_name`
- `insight.hashtags`
- `insight.cta`

User-facing render:

- image
- headline
- caption
- hashtags if present
- follow-up:
  - `publish`
  - `skip`

State updates:

- write `lastDailyInsight`
- mark `sessionContext.currentLane = daily_insight`
- mark `sessionContext.lastSuccessfulPath = daily_insight.rendered`

## Target resolution order

1. `openclaw_msg_id -> routesByMessageId`
2. `agent_phone -> routesByPhone`
3. `agent_phone -> agents[phone].target`

## State file

Bridge state mirror:

- `~/.openclaw/workspace-realtor-social/.openclaw/reel-agent-bridge-state.json`

At minimum, per-agent state should retain:

- `lastJobId`
- `lastDelivery`
- `lastDailyInsight`
- `sessionContext`

## Go / No-Go relevance

Telegram walkthrough 不通过的高风险点主要就是这 4 类：

1. callback 根本没进 bridge
2. `last_job_id` 没刷新
3. `daily_insight` 缺字段却还发给了用户
4. 用户态 delivered / daily insight 渲染和 follow-up 不对
