# Ops Context Write-Back Specification

> How OpenClaw writes session context back to operator-visible state.
> Covers development-checklist Section 5.H (ops context 回流).
> Updated: 2026-04-02
>
> 目的：定义 OpenClaw bridge state 中 `sessionContext` 的最小可执行 schema，避免 post-render follow-up 只靠会话记忆。

---

## Purpose

The operator console needs to answer two questions about every client:

1. **What path should this user go next?** (recommended path)
2. **What did the user just do?** (session lane + last action)

Today the backend provides `recommended_path` via the profile API, but the real-time session context lives in OpenClaw. This spec defines how OpenClaw writes that context to the shared bridge state so the console can display it.

---

## Bridge State File

**Primary mirror:** `~/.openclaw/workspace-realtor-social/.openclaw/reel-agent-bridge-state.json`
**Repo-owned bridge source:** `/Users/lsy/projects/realtor-social/openclaw/extensions/reel-agent-bridge`
**Local install helper:** `/Users/lsy/projects/realtor-social/scripts/openclaw/install-local-wiring.sh`

**Top-level shape:**

```json
{
  "updatedAt": "2026-04-02T00:00:00.000Z",
  "agents": {
    "+10000000000": {
      "agentPhone": "+10000000000",
      "target": "123456789",
      "accountId": "realtor-social",
      "lastJobId": "job-123",
      "lastDelivery": {},
      "lastDailyInsight": {},
      "pendingListingVideo": {},
      "sessionContext": {}
    }
  },
  "targets": {}
}
```

**Per-agent legacy structure (also valid):**

```json
{
  "+10000000000": {
    "lastDelivery": {
      "job_id": "job-xxx",
      "timestamp": "2026-04-01T14:30:00Z",
      "video_url": "https://..."
    },
    "lastDailyInsight": {
      "timestamp": "2026-04-01T08:00:00Z",
      "headline": "..."
    },
    "sessionContext": {
      "current_lane": "delivered",
      "last_successful_path": "video",
      "last_recommended_path": "video_first",
      "starter_task_completed": true,
      "last_revision_round": 0,
      "updated_at": "2026-04-01T14:30:00Z"
    }
  }
}
```

---

## Fields

### Existing (already used by backend)

| Field              | Writer                 | Purpose                                        |
| ------------------ | ---------------------- | ---------------------------------------------- |
| `lastDelivery`     | Backend (via callback) | Tells OpenClaw the most recent delivered video |
| `lastDailyInsight` | Backend (via callback) | Tells OpenClaw the most recent daily insight   |

### `sessionContext` fields

```json
{
  "currentLane": "listing_video | daily_insight | onboarding",
  "lastSuccessfulPath": "string",
  "starterTaskCompleted": true,
  "lastPostRenderKind": "delivered | daily_insight | failed",
  "listingVideoDeliveredAt": "2026-04-02T00:00:00.000Z",
  "lastInsightPublishedAt": "2026-04-02T00:00:00.000Z",
  "videoHandoffNudgedAt": "2026-04-02T00:00:00.000Z"
}
```

Also accepted (camelCase ↔ snake_case mapping):

| Field (camelCase)          | Field (snake_case)       | Type     | Write when                                             | Example values                                                                                            |
| -------------------------- | ------------------------ | -------- | ------------------------------------------------------ | --------------------------------------------------------------------------------------------------------- |
| `currentLane`              | `current_lane`           | string   | Every lane change                                      | `idle`, `video_generation`, `delivered`, `revision`, `daily_insight`, `awaiting_style`, `awaiting_photos` |
| `lastSuccessfulPath`       | `last_successful_path`   | string   | User completes video or insight flow                   | `video`, `insight`, `listing_video.delivered`, `daily_insight.rendered`                                   |
| `last_recommended_path`    | —                        | string   | Backend returns `recommended_path` in profile response | `video_first`, `insight_first`                                                                            |
| `starterTaskCompleted`     | `starter_task_completed` | bool     | User successfully completes their first task           | `true`                                                                                                    |
| `lastPostRenderKind`       | —                        | string   | Each callback delivery                                 | `delivered`, `daily_insight`, `failed`                                                                    |
| `last_revision_round`      | —                        | int      | Each revision submitted                                | `0`, `1`, `2`, `3`                                                                                        |
| `listingVideoDeliveredAt`  | —                        | ISO 8601 | Most recent video delivery                             | `2026-04-02T00:00:00.000Z`                                                                                |
| `lastInsightPublishedAt`   | —                        | ISO 8601 | Most recent insight publish                            | `2026-04-02T00:00:00.000Z`                                                                                |
| `videoHandoffNudgedAt`     | —                        | ISO 8601 | Insight-to-video handoff nudge sent                    | `2026-04-02T00:00:00.000Z`                                                                                |
| `updated_at` / `updatedAt` | —                        | ISO 8601 | Every write                                            | `2026-04-01T14:30:00Z`                                                                                    |

### `pendingListingVideo` fields

```json
{
  "firstPhotoPath": "/tmp/job-1/photos/front.jpg",
  "photoDir": "/tmp/job-1/photos",
  "photoCountHint": 6,
  "style": "professional",
  "awaiting": "style_selection | confirmation",
  "updatedAt": "2026-04-02T00:00:00.000Z"
}
```

---

## Semantics

### `currentLane`

当前用户正在走哪条主链路：

- `listing_video`
- `daily_insight`
- `onboarding`

### `lastSuccessfulPath`

最近一次成功完成的用户态路径，例如：

- `listing_video.delivered`
- `daily_insight.rendered`

### `starterTaskCompleted`

是否已经完成过最小 starter task。

当前定义：

- 至少完成一次 listing video delivered，可记为 `true`

### `lastPostRenderKind`

最近一次发给用户的 post-render 类型：

- `delivered`
- `daily_insight`
- `failed`

### `listingVideoDeliveredAt`

最近一次视频交付时间。

### `lastInsightPublishedAt`

最近一次 daily insight 被 publish 的时间。

### `videoHandoffNudgedAt`

是否已经发过那句 insight-to-video handoff：

> Nice! By the way — whenever you have a listing, just send 6-10 photos and I'll make a video too.

### `pendingListingVideo`

当用户已经发来图片，但还没走完 style / confirm 这段最小启动链时，用这个对象承接运行时真相。

它的作用是：

- 让 OpenClaw 在收到 listing photos 后，不必依赖 chat memory 记住"刚才那批图"
- 只用第一张图的本地路径就能在 `/webhook/in` 启动任务，因为后端会从 `photo_paths[0]` 的父目录推导整批素材目录
- 避免用户发完图后，后续 `professional` / `go` 被当成普通闲聊丢掉

---

## Write Rules

### When to write

| Event                                  | Fields to update                                               |
| -------------------------------------- | -------------------------------------------------------------- |
| User sends photos                      | `current_lane = "video_generation"`                            |
| `delivered` callback received          | `current_lane = "delivered"`, `last_successful_path = "video"` |
| User publishes insight                 | `current_lane = "idle"`, `last_successful_path = "insight"`    |
| User skips insight                     | `current_lane = "idle"`                                        |
| User publishes video                   | `current_lane = "idle"`                                        |
| User sends revision                    | `current_lane = "revision"`, `last_revision_round++`           |
| Profile API returns `recommended_path` | `last_recommended_path = value`                                |
| User completes any starter task        | `starter_task_completed = true`                                |

### Callback-specific write rules

#### progress

- refresh `lastJobId`
- set `currentLane = listing_video`

#### delivered

- refresh `lastJobId`
- write `lastDelivery`
- set `currentLane = listing_video`
- set `lastSuccessfulPath = listing_video.delivered`
- set `starterTaskCompleted = true`
- set `lastPostRenderKind = delivered`
- set `listingVideoDeliveredAt = now`

#### daily_insight

- write `lastDailyInsight`
- set `currentLane = daily_insight`
- set `lastSuccessfulPath = daily_insight.rendered`
- set `lastPostRenderKind = daily_insight`

#### listing photos ingress

- 当 Telegram/渠道消息带图片并命中 listing-video path：
  - 写入 `pendingListingVideo.firstPhotoPath`
  - 写入 `pendingListingVideo.photoDir`
  - 如能推断图片数量，写入 `photoCountHint`
  - 若 profile 已有 style，可直接调用 `/webhook/in` 并清空 `pendingListingVideo`
  - 若 style 缺失，则保持 `awaiting = style_selection`
- 当用户回复 `elegant / professional / energetic`：
  - 刷新 `pendingListingVideo.style`
  - 切到 `awaiting = confirmation`
- 当用户回复 `go / ok / yes / confirm`：
  - 用 `pendingListingVideo.firstPhotoPath` 调 `/webhook/in`
  - 成功后清空 `pendingListingVideo`
  - 刷新 `lastJobId`
  - 设置 `currentLane = listing_video`
  - 设置 `lastSuccessfulPath = listing_video.started`

### Write frequency

- Write on lane changes and significant events only.
- Do NOT write on every message (avoid unnecessary I/O).
- Always update `updated_at` on every write.

### Merge strategy

- Read the full file, update only the `sessionContext` block for the current `agent_phone`.
- Do NOT overwrite `lastDelivery` or `lastDailyInsight` (those are backend-managed).
- If the file doesn't exist, create it with the new entry.

---

## Read Rules

When deciding post-render follow-up:

1. Prefer bridge state over chat memory
2. Prefer `lastDailyInsight` / `lastDelivery` timestamps over vague conversational recency
3. Use `sessionContext` to avoid:
   - publish/skip hitting the wrong object
   - revision losing the right `job_id`
   - repeated handoff nudges

---

## Console Consumption

The operator console reads this file to display:

| Console field                          | Source                                                                          |
| -------------------------------------- | ------------------------------------------------------------------------------- |
| "Recommended path" column on dashboard | `sessionContext.last_recommended_path` or backend profile `recommended_path`    |
| "Next best action" on client detail    | Derived from `current_lane` + `last_successful_path` + `starter_task_completed` |
| "Current status" badge                 | `sessionContext.current_lane`                                                   |

### Next best action derivation logic

```
IF starter_task_completed = false:
  → "Recommend starter task: {recommended_path}"

IF current_lane = "delivered":
  → "Waiting for user: publish / revise / redo"

IF current_lane = "revision":
  → "Revision in progress (round {last_revision_round})"

IF current_lane = "daily_insight":
  → "Daily insight delivered, waiting for: publish / skip"

IF last_successful_path = "video" AND no recent insight:
  → "Consider suggesting daily insight"

IF last_successful_path = "insight" AND no recent video:
  → "Consider suggesting listing video"

DEFAULT:
  → "Awaiting user engagement"
```

---

## Expiration

- `sessionContext` entries older than 7 days (by `updated_at`) should be treated as stale.
- Stale entries don't block rendering — just show "Last active: {date}" instead of live status.
- Do NOT auto-delete stale entries. They provide historical context.

---

## Current Limitation

当前真仓尚未把 `publish` 行为本身写回 bridge，因此 `lastInsightPublishedAt` / `videoHandoffNudgedAt` 仍属于 bridge-ready schema，后续需要在真正的 publish action 落地时接上。

---

## Migration

This is a net-new addition. No migration needed for existing bridge state files — the `sessionContext` key simply won't exist for users who haven't had a session yet. Console should handle missing `sessionContext` gracefully (show "No session data" or equivalent).
