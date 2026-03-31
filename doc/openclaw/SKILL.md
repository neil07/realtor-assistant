# SKILL.md — Reel Agent Backend Integration

---

name: reel-agent-backend
description: |
Connect to Reel Agent backend for listing video generation,
feedback-driven revision, agent profile lookup, daily content push,
and universal text-command message routing.
Trigger when: user sends any message (routed through /api/message first).
requires:
env: - REEL_AGENT_URL - REEL_AGENT_TOKEN - AGENT_PHONE
bins: - curl - jq

---

## Skill 0: Route Message (ALWAYS call first)

Every user message — text, photos, button taps — goes through this endpoint.
It classifies intent and returns the action + response. This is what makes
text-command fallback first-class on channels without buttons.

```bash
curl -s -X POST "$REEL_AGENT_URL/api/message" \
  -H "Authorization: Bearer $REEL_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_phone": "'"$AGENT_PHONE"'",
    "text": "'"$USER_TEXT"'",
    "has_media": '$HAS_MEDIA',
    "media_paths": ['"$MEDIA_PATHS_JSON"'],
    "callback_url": "'"$OPENCLAW_GATEWAY_URL"'/api/sessions/main/messages"
  }'
```

**Response:**

```json
{
  "intent": "listing_video",
  "action": "start_video",
  "response": "Got your photos! Using your elegant style... 🎬",
  "text_commands": {
    "next": "Confirm or change style",
    "examples": ["go", "elegant"]
  },
  "has_profile": true,
  "auto_generate": true
}
```

**Decision tree:**

- `action == "welcome"` → send `response` to user, done
- `action == "start_video"` and `auto_generate == true` → call Skill 2 immediately
- `action == "start_video"` and `awaiting == "style_selection"` → send `response`, wait for next message
- `action == "set_style"` → store style, ask for confirmation ("go" / "ok")
- `action == "confirm_and_generate"` → call Skill 2
- `action == "submit_feedback"` → call Skill 3
- `action == "publish"` → send caption + hashtags from last delivery
- `action == "redo"` → call Skill 2 with same photos
- `action == "disable_daily_push"` / `"enable_daily_push"` → call Skill 4
- `action == "reject"` → send `response`, done

---

## Skill 1: Check Agent Profile

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

→ If `style` is set, **skip style selection** — use stored preference.
→ If 404, show style selection (buttons or text commands).

> Note: Skill 0 already checks the profile internally. You only need this
> for explicit profile queries (e.g., showing user their preferences).

---

## Skill 2: Start Video Generation

Call after confirming parameters with user (or when `auto_generate` is true).

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
→ Tell user the response from Skill 0 (or: "Making your video... ~3 min 🎬")

**Progress callbacks** arrive automatically at `callback_url`. Forward each to user.

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

**Response:**

```json
{
  "job_id": "20260326_143022_a1b2c3-r1",
  "re_run_from": "PRODUCING",
  "classified": { "category": "music", "new_value": "upbeat" }
}
```

→ Update `last_job_id` to new `job_id`.
→ Tell user: "Got it! Only re-doing the music, keeping the script... ⚡"

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

---

## Callback Format (Backend → OpenClaw)

Backend sends progress + delivery updates to `callback_url`. Format:

```json
// Progress update
{
  "type": "progress",
  "job_id": "...",
  "step": "scripting",
  "message": "Writing the voiceover script..."
}

// Delivery — show with action buttons/text-commands
{
  "type": "delivered",
  "job_id": "...",
  "video_url": "https://your-domain/output/job_id/video.mp4",
  "caption": "Spring has arrived...",
  "scene_count": 6,
  "aspect_ratio": "9:16"
}

// Daily insight — show with publish/skip
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

// Failure
{
  "type": "failed",
  "job_id": "...",
  "error": "IMA Studio timeout after 3 retries"
}
```

**Post-delivery UX (buttons OR text commands):**

- For `delivered`: "Happy with it? publish / adjust / redo"
- For `daily_insight`: "Your daily content is ready! publish / skip"
- For `failed`: "Hit an issue 🛠️ — resend photos to try again"
