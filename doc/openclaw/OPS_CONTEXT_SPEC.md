# OPS_CONTEXT_SPEC.md

> 状态：2026-04-02
> 
> 目的：定义 OpenClaw bridge state 中 `sessionContext` 的最小可执行 schema，避免 post-render follow-up 只靠会话记忆。

## State file

- Primary mirror: `~/.openclaw/workspace-realtor-social/.openclaw/reel-agent-bridge-state.json`
- Repo-owned bridge source: `/Users/lsy/projects/realtor-social/openclaw/extensions/reel-agent-bridge`
- Local install helper: `/Users/lsy/projects/realtor-social/scripts/openclaw/install-local-wiring.sh`

Top-level shape:

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

## sessionContext fields

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

## pendingListingVideo fields

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

- 让 OpenClaw 在收到 listing photos 后，不必依赖 chat memory 记住“刚才那批图”
- 只用第一张图的本地路径就能在 `/webhook/in` 启动任务，因为后端会从 `photo_paths[0]` 的父目录推导整批素材目录
- 避免用户发完图后，后续 `professional` / `go` 被当成普通闲聊丢掉

## Write rules

### progress

- refresh `lastJobId`
- set `currentLane = listing_video`

### delivered

- refresh `lastJobId`
- write `lastDelivery`
- set `currentLane = listing_video`
- set `lastSuccessfulPath = listing_video.delivered`
- set `starterTaskCompleted = true`
- set `lastPostRenderKind = delivered`
- set `listingVideoDeliveredAt = now`

### daily_insight

- write `lastDailyInsight`
- set `currentLane = daily_insight`
- set `lastSuccessfulPath = daily_insight.rendered`
- set `lastPostRenderKind = daily_insight`

### listing photos ingress

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

## Read rules

When deciding post-render follow-up:

1. Prefer bridge state over chat memory
2. Prefer `lastDailyInsight` / `lastDelivery` timestamps over vague conversational recency
3. Use `sessionContext` to avoid:
   - publish/skip hitting the wrong object
   - revision losing the right `job_id`
   - repeated handoff nudges

## Current limitation

当前真仓尚未把 `publish` 行为本身写回 bridge，因此 `lastInsightPublishedAt` / `videoHandoffNudgedAt` 仍属于 bridge-ready schema，后续需要在真正的 publish action 落地时接上。
