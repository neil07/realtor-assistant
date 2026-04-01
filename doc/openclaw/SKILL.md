# SKILL.md — Reel Agent Backend Integration

---

name: reel-agent-backend
description: |
  Connect to Reel Agent backend for OpenClaw-directed production routing,
  property-content kickoff, listing-video generation, revision feedback,
  daily insight refinement, and daily insight push control.
trigger: user sends any message; production intent is classified by the OpenClaw Router Skill
requires:
  env:
    - REEL_AGENT_URL
    - REEL_AGENT_TOKEN
    - AGENT_PHONE
    - CALLBACK_URL
  bins:
    - curl
    - jq

---

## Skill 0: Production Routing (Router Skill-owned)

Production routing is now owned by the OpenClaw Router Skill.
Use the backend APIs below directly from OpenClaw after the Router Skill decides the lane.

`/api/message` is still available as a regression oracle during testing, but it is not the production entrypoint.

`CALLBACK_URL` is the Reel Agent business-event callback target owned by the OpenClaw side.
In this project the default shape is `POST http://127.0.0.1:18789/reel-agent/events`,
with `OPENCLAW_CALLBACK_BASE_URL=http://127.0.0.1:18789/reel-agent`
and backend callbacks authenticated by `X-Reel-Secret: $OPENCLAW_CALLBACK_SECRET`.

Do not use:

- `/telegram-webhook` for `callback_url` — that is Telegram transport ingress into OpenClaw
- `/api/sessions/main/messages` as a backend callback target — it is not the project's business-event contract

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
- `action == "skip"` → mark the current daily insight as skipped and wait for the next one
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

Notes:

- On the Telegram/media ingress path, OpenClaw may send only the first local image path in `photo_paths`.
- Backend derives the actual `photo_dir` from `photo_paths[0]`, so a single local path is enough to start generation.

```bash
curl -s -X POST "$REEL_AGENT_URL/webhook/in" \
  -H "Authorization: Bearer $REEL_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_phone": "'"$AGENT_PHONE"'",
    "photo_paths": ['$PHOTO_PATHS_JSON'],
    "callback_url": "'"$CALLBACK_URL"'",
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
- Preferred state sink for `last_job_id`: `~/.openclaw/workspace-realtor-social/.openclaw/reel-agent-bridge-state.json`
- For daily insight publish/skip controls, also read `lastDailyInsight` from the same bridge state file

---

## Skill 3: Submit Feedback

Video revision after `delivered`:

```bash
curl -s -X POST "$REEL_AGENT_URL/webhook/feedback" \
  -H "Authorization: Bearer $REEL_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "job_id": "'"$LAST_JOB_ID"'",
    "agent_phone": "'"$AGENT_PHONE"'",
    "feedback_text": "'"$FEEDBACK_TEXT"'",
    "revision_round": '"$REVISION_ROUND"',
    "feedback_scope": "video"
  }'
```

Daily insight refinement after `daily_insight` render:

```bash
curl -s -X POST "$REEL_AGENT_URL/webhook/feedback" \
  -H "Authorization: Bearer $REEL_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_phone": "'"$AGENT_PHONE"'",
    "feedback_text": "shorter",
    "feedback_scope": "insight",
    "callback_url": "'"$CALLBACK_URL"'"
  }'
```

For `feedback_scope=insight`, backend will refine the latest insight object and can re-push a fresh `daily_insight` callback.
Update `last_job_id` if the backend returns a new video revision job id.

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

The OpenClaw side must expose a business-event bridge that can consume:

- `progress`
- `delivered`
- `failed`
- `daily_insight`

and then fan those events into Telegram user-visible messages.
Current concrete implementation: local plugin route `POST /reel-agent/events`.

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
- For `daily_insight`: `publish / skip / shorter / more professional`
- For `failed`: ask user to resend photos or retry later
- If `openclaw_msg_id` is present, bridge should prefer `openclaw_msg_id -> Telegram target`
- If `openclaw_msg_id` is absent, bridge may fall back to `agent_phone -> Telegram DM target`
