# AGENTS.md — Reel Agent (OpenClaw Side)

Behavior rules for the Reel Agent OpenClaw instance.

---

## Message Routing (Production Contract)

**Production traffic is classified by the OpenClaw Router Skill first.**

`POST $REEL_AGENT_URL/api/message` remains available as a test-only baseline and regression oracle,
but it is no longer the production entrypoint.

Production API set:

- `GET $REEL_AGENT_URL/api/profile/{phone}`
- `POST $REEL_AGENT_URL/webhook/in`
- `POST $REEL_AGENT_URL/webhook/feedback`
- `POST $REEL_AGENT_URL/api/daily-trigger`

**Response examples:**

```json
{
  "intent": "daily_insight",
  "action": "start_daily_insight",
  "response": "Got it — I can prepare a ready-to-post daily insight for Austin. 📈",
  "text_commands": {
    "next": "Ask for today's market content",
    "examples": ["daily insight", "shorter", "more professional"]
  },
  "has_profile": true
}
```

```json
{
  "intent": "property_content",
  "action": "start_property_content",
  "response": "Got it — this looks like a property content request. Send photos when you're ready and I'll take it from there. 🏡",
  "awaiting": "media_or_missing_property_context",
  "text_commands": {
    "next": "Confirm or change style",
    "examples": ["go", "elegant", "professional"]
  },
  "has_profile": true
}
```

**OpenClaw behavior:**

1. Router Skill decides the lane directly from user input
2. If listing photos arrive and profile already has style → call `/webhook/in` immediately
3. If style is missing → ask for style, then wait for `go / ok / yes`
4. If user asks for `daily insight` → keep the request in the daily-insight lane and trigger the daily content path
5. If user sends free text after `delivered` → call `/webhook/feedback` with `feedback_scope=video`
6. If user sends `shorter` or `more professional` after `daily_insight` → call `/webhook/feedback` with `feedback_scope=insight`
7. If user sends `disable_daily_push` / `enable_daily_push` intent → call `/webhook/in` with `params.action` set to that value
8. On the listing-photo path, OpenClaw only needs the first local image path; backend derives `photo_dir` from `photo_paths[0]` and scans the directory

**Callback contract note:**

- `callback_url` must point to the OpenClaw-side business-event bridge
- For this project the default contract is `POST http://127.0.0.1:18789/reel-agent/events`
- Set `OPENCLAW_CALLBACK_BASE_URL=http://127.0.0.1:18789/reel-agent`, then backend uses `"$OPENCLAW_CALLBACK_BASE_URL"/events`
- Repo-owned bridge source lives in `/Users/lsy/projects/realtor-social/openclaw/extensions/reel-agent-bridge`
- Local runtime mount should be refreshed via `/Users/lsy/projects/realtor-social/scripts/openclaw/install-local-wiring.sh`
- OpenClaw bridge auth uses `X-Reel-Secret: $OPENCLAW_CALLBACK_SECRET`
- Do not point backend callbacks at `/telegram-webhook`; that path is only for Telegram transport ingress
- Do not assume `/api/sessions/main/messages` is a supported backend callback endpoint
- OpenClaw structured callback state lives at:
  - `~/.openclaw/plugins/reel-agent-bridge/state.json`
  - `~/.openclaw/workspace-realtor-social/.openclaw/reel-agent-bridge-state.json`

---

## Graduation Routing Cases

These inputs must stay stable for both new users and returning users.

| Input | New user intent/action | Returning user intent/action |
| --- | --- | --- |
| `help` | `first_contact` / `welcome` | `help` / `welcome` |
| `what can you do?` | `first_contact` / `welcome` | `help` / `welcome` |
| `daily insight` | `daily_insight` / `start_daily_insight` | `daily_insight` / `start_daily_insight` |
| `123 Main St open house this Sunday 2pm` | `property_content` / `start_property_content` | `property_content` / `start_property_content` |
| `stop push` | `stop_push` / `disable_daily_push` | `stop_push` / `disable_daily_push` |
| `resume push` | `resume_push` / `enable_daily_push` | `resume_push` / `enable_daily_push` |

---

## Intent → Action Map

| Intent | Trigger | Action | Next Step |
| --- | --- | --- | --- |
| `first_contact` | New user help / first-touch text | Show welcome + capabilities | Wait for input |
| `help` | Returning user `help`, `what can you do?` | Show capabilities + text commands | Wait for input |
| `listing_video` | Photos sent | Check profile → auto-generate or ask style | Style or generate |
| `style_selection` | `elegant`, `professional`, `energetic` | Set style, ask to confirm | Confirm |
| `confirm` | `go`, `ok`, `yes`, `done` | Start video generation | Processing |
| `daily_insight` | `daily insight`, market update text | Acknowledge and enter daily-insight flow | Generate insight |
| `property_content` | Listing / open house / address text | Acknowledge and wait for photos or assets | Collect media |
| `revision` | Free text after DELIVERED job | Submit as video feedback | Re-processing |
| `publish` | `publish`, `post` after delivery or insight | Publish the current object | Done |
| `redo` | `redo`, `again` after delivery | Restart from scratch | Processing |
| `skip` | `skip`, `pass` after daily insight delivery | Skip this insight | Done |
| `insight_refine_shorter` | `shorter` after daily insight delivery | Submit as insight feedback | Re-render insight |
| `insight_refine_professional` | `more professional` after daily insight delivery | Submit as insight feedback | Re-render insight |
| `stop_push` | `stop push`, `pause push`, `no more` | Disable daily insights | Confirmed |
| `resume_push` | `resume push`, `start push` | Re-enable daily insights | Confirmed |
| `off_topic` | Unrelated question | Rejection line + redirect | Wait for photos |

---

## Text-Command Fallback Table

Every button interaction has a text equivalent. This is first-class, not a fallback.

| Button Label | Text Command(s) | 中文 |
| --- | --- | --- |
| [Elegant ✨] | `elegant` | `优雅` |
| [Professional 💼] | `professional` | `专业` |
| [Energetic 🔥] | `energetic` | `活力` |
| [Go / Confirm] | `go`, `ok`, `yes`, `done` | `好的`, `确认`, `开始` |
| [Publish] | `publish`, `post` | `发布` |
| [Adjust] | `adjust`, `change` + description | `调整` + 说明 |
| [Redo] | `redo`, `again` | `重做` |
| [Skip] | `skip`, `pass` | `跳过` |
| [Stop Daily] | `stop push`, `pause push` | `停止推送`, `暂停推送` |
| [Resume Daily] | `resume push`, `start push` | `恢复推送` |

---

## Flow: Property Content Request

### Text-only kickoff

```text
User: "123 Main St open house this Sunday 2pm"
  → /api/message → intent: property_content, action: start_property_content
Bot: "Got it — this looks like a property content request. Send photos when you're ready and I'll take it from there. 🏡"
```

### Asset-first kickoff

```text
User: (sends 4 photos)
  → /api/message → intent: listing_video, action: start_video

If profile has style:
  → OpenClaw calls /webhook/in immediately
  → Bot: "Got your photos! Using your professional style... 🎬 Video will be ready in ~3 min."

If profile has no style:
  → Bot asks for style selection
  → User: "professional"
  → User: "go"
  → OpenClaw calls /webhook/in
```

---

## Flow: Daily Insight Push

**Initiated by backend** — not user. Backend calls OpenClaw Gateway directly.

```json
{
  "type": "daily_insight",
  "agent_phone": "+60175029017",
  "insight": { "headline": "...", "caption": "...", "hashtags": ["..."] },
  "image_urls": { "story_1080x1920": "https://...", "feed_1080x1080": "https://..." }
}
```

OpenClaw should deliver the branded image + caption and offer `publish / skip / shorter / more professional`.

---

## Flow: Revision Request

```text
User: "make the music more upbeat"
  → /api/message → intent: revision, action: submit_feedback
  → POST /webhook/feedback { feedback_text: "make the music more upbeat" }
Bot: "Got it — adjusting now... ⚡"
```

---

## Memory Rules

- Do **not** store style/music preferences in OpenClaw — backend profile is source of truth
- Do store: user's name, preferred language, and `last_job_id` for revision matching
- Do also read `lastDailyInsight` from bridge state when handling `publish / skip / shorter / more professional` after a daily insight render
- `last_job_id` is now **structured bridge state first**, session memory second
- Preferred read source: `~/.openclaw/workspace-realtor-social/.openclaw/reel-agent-bridge-state.json`
- Session memory for `last_job_id`: keep only as a lightweight fallback
- `last_job_id` must be refreshed after every successful `delivered` callback or revision response

---

## Environment Variables Required

```bash
REEL_AGENT_URL=http://localhost:8000
REEL_AGENT_TOKEN=your-secret-token
AGENT_PHONE=+60175029017
OPENCLAW_CALLBACK_BASE_URL=http://127.0.0.1:18789/reel-agent
OPENCLAW_CALLBACK_SECRET=replace-with-shared-callback-secret
```
