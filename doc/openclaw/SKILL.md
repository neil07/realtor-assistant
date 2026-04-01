# SKILL.md — Reel Agent Backend Integration

---

name: reel-agent-backend
description: |
Connect to Reel Agent backend for production pipeline dispatch, revision feedback,
profile lookup, daily insight triggering, and callback consumption.
trigger: user sends any message; OpenClaw Router Skill decides which backend API to call
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

## Skill 0: Router (OpenClaw side)

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

## Skill 3: Submit Revision Feedback

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

Keep revision text inside the revision session. Do not bounce users into generic style selection after a delivered video.

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

---

## Memory Rules

- Backend profile remains the source of truth for style and persistent preferences.
- OpenClaw should keep enough session state to bind:
  - latest delivered `job_id`
  - latest `daily_insight`
  - current revision session
- If OpenClaw tracks the latest successful path or next step, sync it back into operator-visible state when possible.
