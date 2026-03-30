# SKILL.md — Reel Agent Backend Integration

---

name: reel-agent-backend
description: |
Connect to Reel Agent backend for listing video generation,
feedback-driven revision, agent profile lookup, and daily content push.
Trigger when: user sends listing photos, provides revision feedback,
or daily insight push arrives from backend.
requires:
env: - REEL_AGENT_URL # e.g. http://localhost:8000 - REEL_AGENT_TOKEN # shared secret for auth - AGENT_PHONE # this agent's phone number (+601xxxxxxxx)
bins: - curl - jq

---

## Skill 1: Check Agent Profile

Before asking the user any preference questions, check if we already know their preferences.

```bash
curl -s -X GET "$REEL_AGENT_URL/api/profile/$AGENT_PHONE" \
  -H "Authorization: Bearer $REEL_AGENT_TOKEN"
```

**Response (200):** Agent has a profile.

```json
{
  "style": "elegant",
  "music": "upbeat",
  "language": "en",
  "videos_created": 4
}
```

→ If `style` is set, **skip style selection buttons** — use stored preference.
→ If 404, show style selection buttons to user.

---

## Skill 2: Start Video Generation

Call after confirming parameters with user (or using stored profile).

```bash
curl -s -X POST "$REEL_AGENT_URL/webhook/in" \
  -H "Authorization: Bearer $REEL_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_phone": "'"$AGENT_PHONE"'",
    "photo_paths": ['"$PHOTO_PATHS_JSON"'],
    "callback_url": "'"$OPENCLAW_GATEWAY_URL"'/api/sessions/main/messages",
    "openclaw_msg_id": "'"$MSG_ID"'",
    "params": {
      "style": "'"$STYLE"'",
      "music": "'"$MUSIC"'",
      "address": "'"$ADDRESS"'",
      "price": "'"$PRICE"'",
      "agent_name": "'"$AGENT_NAME"'",
      "language": "'"$LANGUAGE"'",
      "aspect_ratio": "9:16"
    }
  }'
```

**Response:**

```json
{ "job_id": "20260326_143022_a1b2c3", "status": "QUEUED" }
```

→ Store `job_id` in session memory as `last_job_id`.
→ Tell user: "收到 8 张照片，按你的优雅风格生成中... 🎬 约 3-5 分钟"

**Progress callbacks** arrive automatically at `callback_url`.
Forward each one to the user as-is.

---

## Skill 3: Submit Revision Feedback

Call when user sends revision text after receiving a video.

```bash
curl -s -X POST "$REEL_AGENT_URL/webhook/feedback" \
  -H "Authorization: Bearer $REEL_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "job_id": "'"$LAST_JOB_ID"'",
    "agent_phone": "'"$AGENT_PHONE"'",
    "feedback_text": "'"$FEEDBACK_TEXT"'",
    "revision_round": '"$REVISION_ROUND"'
  }'
```

**Response:**

```json
{
  "job_id": "20260326_143022_a1b2c3-r1",
  "re_run_from": "PRODUCING",
  "classified": { "category": "music", "new_value": "upbeat" }
}
```

→ Update `last_job_id` to new `job_id`.
→ Tell user: "收到！只重新配乐，剧本保留，约 2 分钟 🎵"

---

## Skill 4: Disable Daily Push

Call when user opts out of daily market insights.

```bash
curl -s -X POST "$REEL_AGENT_URL/webhook/in" \
  -H "Authorization: Bearer $REEL_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_phone": "'"$AGENT_PHONE"'",
    "photo_paths": [],
    "params": {"action": "disable_daily_push"}
  }'
```

---

## Callback Format (Backend → OpenClaw)

Backend sends progress + delivery updates to `callback_url`. Format:

```json
// Progress update
{
  "type": "progress",
  "job_id": "...",
  "step": "scripting",
  "message": "正在写配音文案..."
}

// Delivery
{
  "type": "delivered",
  "job_id": "...",
  "video_url": "https://your-domain/output/job_id/video.mp4",
  "caption": "Spring has arrived...",
  "scene_count": 6,
  "aspect_ratio": "9:16"
}

// Daily insight push
{
  "type": "daily_insight",
  "agent_phone": "+60175029017",
  "insight": {
    "headline": "Spring Buying Tips for KL",
    "caption": "...",
    "hashtags": ["realestate", "KL"]
  },
  "image_urls": {
    "story_1080x1920": "https://...",
    "feed_1080x1080": "https://..."
  }
}
```

→ For `delivered`: send video file + caption to user, then show [满意发布] [调整] [重做] buttons.
→ For `daily_insight`: send image + caption to user, show [发布] [跳过] buttons.
→ For `failed`: tell user "生成遇到问题 🛠️", offer to retry.
