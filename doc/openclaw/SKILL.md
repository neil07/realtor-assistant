# SKILL.md — Reel Agent Backend Integration

---

name: reel-agent-backend
description: |
Connect to Reel Agent backend for OpenClaw-directed production routing,
property-content kickoff, listing-video generation, revision feedback,
daily insight refinement, and daily insight push control.
trigger: user sends any message; production intent is classified by the OpenClaw Router Skill
requires:
env: - REEL_AGENT_URL - REEL_AGENT_TOKEN - AGENT_PHONE - CALLBACK_URL
bins: - curl - jq

---

## Production Model

OpenClaw owns intent recognition.

Reel Agent backend owns:

- pipeline execution
- profile storage
- callback payloads
- operator console state

Test-only helpers:

- `POST /api/message`
- `POST /api/router-test`

These endpoints are for local audits and regression tests only. Do not put production routing behind them.

---

## Skill 0: Production Routing (Router Skill-owned)

Production routing is now owned by the OpenClaw Router Skill.
Use the backend APIs below directly from OpenClaw after the Router Skill decides the lane.

`/api/message` is still available as a regression oracle during testing, but it is not the production entrypoint.

For every inbound user message:

1. Infer intent in OpenClaw.
2. Pick the correct production API.
3. Shape the user-facing wording in OpenClaw.
4. Keep session continuity for revisions and daily insight follow-ups.

### Production API map

| Situation                                   | API                        |
| ------------------------------------------- | -------------------------- |
| User sends listing photos                   | `POST /webhook/in`         |
| User asks to revise delivered video         | `POST /webhook/feedback`   |
| User asks for daily insight / market update | `POST /api/daily-trigger`  |
| Router needs stored preferences             | `GET /api/profile/{phone}` |

### Test-only router sanity checks

If you need a local routing baseline during development:

```bash
curl -s -X POST "$REEL_AGENT_URL/api/router-test" \
  -H "Authorization: Bearer $REEL_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_phone": "'"$AGENT_PHONE"'",
    "text": "'"$USER_TEXT"'",
    "has_media": '$HAS_MEDIA',
    "media_paths": ['$MEDIA_PATHS_JSON'],
    "callback_url": "'"$CALLBACK_URL"'"
  }'
```

Use that only for:

- local dialogue eval
- regression testing
- prelaunch experience audits

---

## Skill 1: Load Profile

```bash
curl -s -X GET "$REEL_AGENT_URL/api/profile/$AGENT_PHONE" \
  -H "Authorization: Bearer $REEL_AGENT_TOKEN"
```

Use this before deciding whether to:

- reuse an existing style
- ask for a style
- steer toward insight-first
- explain the next best action

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

Notes:

- Property-content text alone does not start generation.
- OpenClaw should collect the minimum missing info first, then call this endpoint.
- Store the returned `job_id` for future revisions.

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

Keep revision text inside the revision session. Do not bounce users into generic style selection after a delivered video.

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

## Skill 4: Trigger Daily Insight

```bash
curl -s -X POST "$REEL_AGENT_URL/api/daily-trigger?secret=" \
  -H "Authorization: Bearer $REEL_AGENT_TOKEN"
```

Use when the user explicitly asks for a daily insight / market update.

---

## Skill 5: Daily Push Control

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

Swap `disable_daily_push` for `enable_daily_push` as needed.

---

## Callback Contract

OpenClaw must expose a business-event bridge that accepts:

- `progress`
- `delivered`
- `failed`
- `daily_insight`
- `onboarding_form`
- `form_completed`

### Daily insight requirements

Before rendering a daily insight to the user, validate:

- `insight.headline`
- `insight.caption`
- `image_urls`

Supported backend-safe follow-ups after daily insight delivery:

- `publish`
- `skip`
- `shorter`
- `more professional`

### Callback rendering follow-ups

- For `delivered`: `publish / adjust / redo`
- For `daily_insight`: `publish / skip / shorter / more professional`
- For `failed`: ask user to resend photos or retry later
- If `openclaw_msg_id` is present, bridge should prefer `openclaw_msg_id -> Telegram target`
- If `openclaw_msg_id` is absent, bridge may fall back to `agent_phone -> Telegram DM target`

---

## Memory Rules

- Backend profile remains the source of truth for style and persistent preferences.
- OpenClaw should keep enough session state to bind:
  - latest delivered `job_id`
  - latest `daily_insight`
  - current revision session
- If OpenClaw tracks the latest successful path or next step, sync it back into operator-visible state when possible.
