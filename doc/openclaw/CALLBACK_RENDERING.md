# Callback Rendering Specification

> How OpenClaw should render each callback type from Reel Agent backend.
> Covers development-checklist Section 5.E (渲染前校验).
> Updated: 2026-04-02

---

## Bridge Contract

- Route: `POST $OPENCLAW_CALLBACK_BASE_URL/events`
- Default local route: `POST http://127.0.0.1:18789/reel-agent/events`
- Auth header: `X-Reel-Secret: $OPENCLAW_CALLBACK_SECRET`
- Repo-owned plugin source: `/Users/lsy/projects/realtor-social/openclaw/extensions/reel-agent-bridge`
- Local runtime mount: `~/.openclaw/extensions/reel-agent-bridge`

---

## Callback Types

Reel Agent backend sends these callback types to `$OPENCLAW_CALLBACK_BASE_URL/events`:

| Type               | Frequency               | User-facing?   | Pre-render validation required? |
| ------------------ | ----------------------- | -------------- | ------------------------------- |
| `progress`         | Multiple per job        | Yes            | No (safe defaults exist)        |
| `delivered`        | Once per job            | Yes            | Yes                             |
| `daily_insight`    | Once per trigger        | Yes            | **Yes (critical)**              |
| `failed`           | Once per job            | Yes (softened) | No                              |
| `quality_blocked`  | Rare                    | Yes            | No                              |
| `stall_warning`    | Rare                    | Yes            | No                              |
| `photo_suggestion` | Once per job (optional) | Yes            | No                              |
| `script_preview`   | Once per job (optional) | Yes            | No                              |
| `onboarding_form`  | Once per new user       | Yes            | No                              |
| `form_completed`   | Once per user           | Internal       | No                              |

---

## Pre-Render Validation Rules

### `delivered` callback

Payload:

```json
{
  "type": "delivered",
  "job_id": "job-xxx",
  "openclaw_msg_id": "msg-xxx",
  "agent_phone": "+1...",
  "video_url": "https://...",
  "video_path": "/output/.../final.mp4",
  "caption": "...",
  "scene_count": 6,
  "word_count": 95,
  "aspect_ratio": "9:16"
}
```

**Validation:**
| Field | Required | Fallback if missing |
|-------|----------|-------------------|
| `video_url` | Yes | Do NOT deliver. Log alert. Notify ops. |
| `caption` | Yes | Deliver video with generic caption: "Your listing video is ready!" |
| `scene_count` | No | Omit from display |
| `word_count` | No | Omit from display |

**Render:**

1. Send the video (video_url or as file).
2. Send the caption text.
3. Show follow-up buttons: **publish** / **adjust** / **redo**
4. Update session: `last_job_id = job_id`, `lane = delivered`

**State updates:**

- refresh `last_job_id`
- write `lastDelivery`
- mark `sessionContext.currentLane = listing_video`
- mark `sessionContext.starterTaskCompleted = true`

---

### `daily_insight` callback (CRITICAL)

Payload:

```json
{
  "type": "daily_insight",
  "agent_phone": "+1...",
  "agent_name": "Natalie",
  "insight": {
    "headline": "Klang Valley median hits RM 520K...",
    "key_numbers": "...",
    "talking_points_buyers": ["..."],
    "talking_points_sellers": ["..."],
    "caption": "Did you know? Klang Valley...",
    "hashtags": ["#realestate", "#klangvalley"],
    "topic_type": "market_stat"
  },
  "forward_buyer": "...",
  "forward_seller": "...",
  "image_urls": {
    "story_1080x1920": "https://..."
  }
}
```

**Validation (ALL must pass before rendering):**

| Field              | Check                               | If fails                                                                                                       |
| ------------------ | ----------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `insight.headline` | Non-empty string                    | **BLOCK delivery.** Log: `[INSIGHT_BLOCKED] Missing headline for {agent_phone}`. Do NOT send anything to user. |
| `insight.caption`  | Non-empty string                    | **BLOCK delivery.** Log: `[INSIGHT_BLOCKED] Missing caption for {agent_phone}`. Do NOT send anything to user.  |
| `image_urls`       | At least one key with non-empty URL | **BLOCK delivery.** Log: `[INSIGHT_BLOCKED] Missing image for {agent_phone}`. Do NOT send anything to user.    |

If any required field is missing:

- **do not render to user**
- return 400 / internal error at bridge
- treat as an ops-visible callback contract failure

**If all validation passes — render:**

1. Send the image (`story_1080x1920` preferred, fallback to any available format).
2. Send the caption with hashtags appended.
3. Show exactly 4 follow-up options:
   - **publish** — post as-is
   - **skip** — discard this one
   - **shorter** — regenerate with shorter text
   - **more professional** — regenerate with professional tone
4. Update session: `last_daily_insight = payload`, `lane = daily_insight`

**Do NOT show:** any other refinement options, buttons, or text commands beyond these 4.

**State updates:**

- write `lastDailyInsight`
- mark `sessionContext.currentLane = daily_insight`
- mark `sessionContext.lastSuccessfulPath = daily_insight.rendered`

---

### `progress` callback

Payload:

```json
{
  "type": "progress",
  "job_id": "job-xxx",
  "openclaw_msg_id": "msg-xxx",
  "agent_phone": "+1...",
  "step": "analyzing",
  "message": "Analyzing your photos..."
}
```

**Validation:** None required (all fields have safe defaults).

**Render:** Send the `message` field as a chat message. These messages are pre-written to sound natural:

| step         | message                                          |
| ------------ | ------------------------------------------------ |
| `analyzing`  | Analyzing your photos...                         |
| `scripting`  | Writing the voiceover script...                  |
| `prompting`  | Planning camera moves...                         |
| `producing`  | Generating AI video clips (this takes ~2 min)... |
| `assembling` | Assembling the final video...                    |
| `done`       | Your listing video is ready!                     |

If `message` is empty, use: "Working on your video..."

**State updates:**

- preserve `job_id` in bridge state as `last_job_id`

---

### `failed` callback

Payload:

```json
{
  "type": "failed",
  "job_id": "job-xxx",
  "openclaw_msg_id": "msg-xxx",
  "agent_phone": "+1...",
  "error": "TTS_ALL_FAILED: all engines returned errors",
  "retry_count": 2,
  "override_url": "http://localhost:8000/webhook/manual-override/job-xxx"
}
```

**Render (user-facing):**
"Sorry, something went wrong with your video. My team is looking into it — I'll update you soon."

**Do NOT:** expose `error` text, `override_url`, or `retry_count` to the user.

**Internal:** Log the full payload for ops. If `retry_count >= 3`, escalate to operator alert.

**State updates:**

- refresh `last_job_id`
- mark `sessionContext.lastPostRenderKind = failed`

---

### `quality_blocked` callback

Payload:

```json
{
  "type": "quality_blocked",
  "job_id": "job-xxx",
  "agent_phone": "+1...",
  "score": 4.2,
  "top_issues": ["low motion", "dark frames", "audio mismatch"],
  "message": "Video scored 4.2/10 — below quality threshold...",
  "actions": {
    "retry_url": "http://.../manual-override/job-xxx?action=retry",
    "accept_url": "http://.../manual-override/job-xxx?action=mark_delivered",
    "cancel_url": "http://.../manual-override/job-xxx?action=cancel"
  }
}
```

**Render:**
"Your video turned out a bit rough this time. Want me to:"

- **Retry** — re-generate from scratch
- **Accept** — deliver as-is
- **Cancel** — drop this one

Map buttons to the action URLs internally.

---

### `stall_warning` callback

Payload:

```json
{
  "type": "stall_warning",
  "job_id": "job-xxx",
  "agent_phone": "+1...",
  "idle_minutes": 8,
  "current_step": "producing",
  "message": "Your video has been processing for 8+ minutes...",
  "actions": {
    "retry_url": "...",
    "cancel_url": "..."
  }
}
```

**Render:**
"Your video is taking longer than expected — I'm still working on it. Want me to retry or cancel?"

- **Retry** / **Cancel** buttons

---

### `photo_suggestion` callback

Payload:

```json
{
  "type": "photo_suggestion",
  "job_id": "job-xxx",
  "agent_phone": "+1...",
  "suggestions": ["Could use: kitchen, bathroom", "Living Room: too dark"],
  "message": "Quick tip: your video is being made, but adding a few more photos could make it even better."
}
```

**Render:** Send the `message` + formatted `suggestions` list. Advisory only — no blocking.

---

### `script_preview` callback

Payload:

```json
{
  "type": "script_preview",
  "job_id": "job-xxx",
  "agent_phone": "+1...",
  "script": {
    "hook": "What if your next listing could sell itself?",
    "walkthrough": "Step inside this stunning...",
    "closer": "Ready to see more? Contact...",
    "word_count": 95,
    "estimated_duration": 30,
    "caption": "..."
  },
  "scenes": {
    "count": 6,
    "structure": [...]
  },
  "message": "Here's your video script preview..."
}
```

**Render:**

1. Format script sections (hook / walkthrough / closer) as a readable preview.
2. Show word count and estimated duration.
3. "Reply with changes, or I'll keep going!"
4. If user replies with feedback → treat as revision.

---

## Target Resolution Order

1. `openclaw_msg_id -> routesByMessageId`
2. `agent_phone -> routesByPhone`
3. `agent_phone -> agents[phone].target`

---

## State File

Bridge state mirror:

- `~/.openclaw/workspace-realtor-social/.openclaw/reel-agent-bridge-state.json`
- repo install guide: `/Users/lsy/projects/realtor-social/openclaw/README.md`

At minimum, per-agent state should retain:

- `lastJobId`
- `lastDelivery`
- `lastDailyInsight`
- `sessionContext`

---

## Tone Guidelines

All user-facing messages should:

- Sound like a professional assistant, not a system log
- Be 1-3 lines max
- Use casual professional tone (matching SOUL.md personality)
- Include emoji sparingly (1-2 per message max)
- Never expose technical terms (job_id, callback, payload, API, override_url)

---

## Go / No-Go Relevance

Telegram walkthrough 不通过的高风险点主要就是这 4 类：

1. callback 根本没进 bridge
2. `last_job_id` 没刷新
3. `daily_insight` 缺字段却还发给了用户
4. 用户态 delivered / daily insight 渲染和 follow-up 不对
