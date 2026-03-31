# SKILL.md — Reel Agent Backend Integration

---

name: reel-agent-backend
description: |
  Connect to Reel Agent backend for universal message routing,
  property-content kickoff, listing-video generation, revision feedback,
  and daily insight push control.
trigger: user sends any message; always route through /api/message first
requires:
  env:
    - REEL_AGENT_URL
    - REEL_AGENT_TOKEN
    - AGENT_PHONE
  bins:
    - curl
    - jq

---

## Skill 0: Route Message (ALWAYS call first)

Every user message — text, photos, button taps — goes through this endpoint.
It keeps routing thin: `/api/message` only classifies the lane and tells OpenClaw what to do next.

```bash
curl -s -X POST "$REEL_AGENT_URL/api/message" \
  -H "Authorization: Bearer $REEL_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_phone": "'"$AGENT_PHONE"'",
    "text": "'"$USER_TEXT"'",
    "has_media": '$HAS_MEDIA',
    "media_paths": ['$MEDIA_PATHS_JSON'],
    "callback_url": "'"$OPENCLAW_GATEWAY_URL"'/api/sessions/main/messages"
  }'
```

**Graduation routing contract:**

| Input | New user | Returning user |
| --- | --- | --- |
| `help` | `first_contact` / `welcome` | `help` / `welcome` |
| `what can you do?` | `first_contact` / `welcome` | `help` / `welcome` |
| `daily insight` | `daily_insight` / `start_daily_insight` | `daily_insight` / `start_daily_insight` |
| `123 Main St open house this Sunday 2pm` | `property_content` / `start_property_content` | `property_content` / `start_property_content` |
| `stop push` | `stop_push` / `disable_daily_push` | `stop_push` / `disable_daily_push` |
| `resume push` | `resume_push` / `enable_daily_push` | `resume_push` / `enable_daily_push` |

**Decision tree:**

- `action == "welcome"` → send `response` to user, done
- `action == "start_video"` and `auto_generate == true` → call Skill 2 immediately
- `action == "start_video"` and `awaiting == "style_selection"` → send `response`, wait for next message
- `action == "start_daily_insight"` → send `response`, keep the request in the daily-insight lane
- `action == "start_property_content"` → send `response`, keep the user in the unified property-content lane and wait for photos or richer assets before calling Skill 2
- `action == "set_style"` → store style, ask for confirmation (`go` / `ok`)
- `action == "confirm_and_generate"` → call Skill 2
- `action == "submit_feedback"` → call Skill 3
- `action == "publish"` → send caption + hashtags from last delivery
- `action == "redo"` → call Skill 2 again with the same photos
- `action == "disable_daily_push"` / `"enable_daily_push"` → call Skill 4
- `action == "reject"` → send `response`, done

---

## Skill 1: Check Agent Profile

Use only for explicit profile queries. Skill 0 already checks profile internally.

```bash
curl -s -X GET "$REEL_AGENT_URL/api/profile/$AGENT_PHONE" \
  -H "Authorization: Bearer $REEL_AGENT_TOKEN"
```

If `style` exists, OpenClaw may skip style selection on the asset-first video path.

---

## Skill 2: Start Video Generation

Call after parameters are confirmed, or immediately when Skill 0 returns `auto_generate == true`.

```bash
curl -s -X POST "$REEL_AGENT_URL/webhook/in" \
  -H "Authorization: Bearer $REEL_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_phone": "'"$AGENT_PHONE"'",
    "photo_paths": ['$PHOTO_PATHS_JSON'],
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

**Important:**

- Property-content text alone does **not** start generation
- Generation begins only after OpenClaw has photos or richer property assets
- Store returned `job_id` as `last_job_id`

---

## Skill 3: Submit Revision Feedback

Call when Skill 0 returns `action: "submit_feedback"`.

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

Update `last_job_id` if the backend returns a new revision job id.

---

## Skill 4: Daily Push Control

Call when Skill 0 returns `action: "disable_daily_push"` or `"enable_daily_push"`.

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

Swap `disable_daily_push` for `enable_daily_push` when handling `resume push`.

---

## Callback Format (Backend → OpenClaw)

Backend sends progress + delivery updates to `callback_url`.

```json
{
  "type": "progress",
  "job_id": "...",
  "step": "scripting",
  "message": "Writing the voiceover script..."
}
```

```json
{
  "type": "delivered",
  "job_id": "...",
  "video_url": "https://your-domain/output/job_id/video.mp4",
  "caption": "Spring has arrived...",
  "scene_count": 6,
  "aspect_ratio": "9:16"
}
```

```json
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

```json
{
  "type": "failed",
  "job_id": "...",
  "error": "IMA Studio timeout after 3 retries"
}
```

**Post-delivery UX:**

- For `delivered`: `publish / adjust / redo`
- For `daily_insight`: `publish / skip`
- For `failed`: ask user to resend photos or retry later
