# AGENTS.md — Reel Agent (OpenClaw Side)

Behavior rules for the Reel Agent OpenClaw instance.

---

## Production Boundary

**D9 is now the source of truth:** OpenClaw owns user-facing intent recognition and API dispatch.

- OpenClaw is responsible for understanding the user's message, choosing the right API, and shaping the user-facing response.
- Reel Agent backend is responsible for production pipelines, profile storage, callbacks, and operator surfaces.
- `POST /api/message` and `POST /api/router-test` still exist, but they are **test-only** endpoints for local audits and regression baselines. Production traffic should not depend on them.

## Message Routing (Production Contract)

**Production traffic is classified by the OpenClaw Router Skill first.**

`POST $REEL_AGENT_URL/api/message` remains available as a test-only baseline and regression oracle,
but it is no longer the production entrypoint.

Production API set:

- `GET $REEL_AGENT_URL/api/profile/{phone}`
- `POST $REEL_AGENT_URL/webhook/in`
- `POST $REEL_AGENT_URL/webhook/feedback`
- `POST $REEL_AGENT_URL/api/daily-trigger`

---

## Production APIs

OpenClaw should call these backend APIs directly in production:

1. `POST /webhook/in`
   Use for listing-video jobs and daily push control actions.
2. `POST /webhook/feedback`
   Use for revision feedback after a delivered video.
3. `GET /api/profile/{phone}`
   Use to load stored preferences before deciding how to respond.
4. `POST /api/daily-trigger`
   Use when the user explicitly asks for a daily insight / market update.

---

## Router Skill

### Rule 1: Media means listing-video flow

When the user sends listing photos:

1. Call `GET /api/profile/{phone}`.
2. If a usable style preference exists, call `POST /webhook/in` immediately.
3. If no usable style exists, ask the user to choose one, then call `POST /webhook/in`.

If OpenClaw wants a local routing sanity check during development, it may call `POST /api/router-test`, but production should skip that extra hop.

### Rule 2: Free text after delivery means revision flow

When the latest user-facing artifact is a delivered video and the user sends natural-language changes:

1. Keep the session in revision mode.
2. Call `POST /webhook/feedback` with the raw feedback text.
3. Do not reset the user into a global style-selection or generic welcome flow.

### Rule 3: Daily insight requests go straight to the daily pipeline

When the user asks for a market update, daily insight, or daily content:

1. Recognize the intent in OpenClaw.
2. Call `POST /api/daily-trigger`.
3. Keep the conversation in the daily-insight lane until the callback arrives.

### Rule 4: Off-topic requests stay off the backend

If the user is chatting about unrelated topics, do not call a backend routing endpoint just to reject them. OpenClaw should reply directly and steer back to:

- sending listing photos
- asking for daily insight

### Router Skill Routing Summary

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

| Input                                    | New user intent/action                        | Returning user intent/action                  |
| ---------------------------------------- | --------------------------------------------- | --------------------------------------------- |
| `help`                                   | `first_contact` / `welcome`                   | `help` / `welcome`                            |
| `what can you do?`                       | `first_contact` / `welcome`                   | `help` / `welcome`                            |
| `daily insight`                          | `daily_insight` / `start_daily_insight`       | `daily_insight` / `start_daily_insight`       |
| `123 Main St open house this Sunday 2pm` | `property_content` / `start_property_content` | `property_content` / `start_property_content` |
| `stop push`                              | `stop_push` / `disable_daily_push`            | `stop_push` / `disable_daily_push`            |
| `resume push`                            | `resume_push` / `enable_daily_push`           | `resume_push` / `enable_daily_push`           |

---

## Intent → Action Map

| Intent                        | Trigger                                          | Action                                     | Next Step         |
| ----------------------------- | ------------------------------------------------ | ------------------------------------------ | ----------------- |
| `first_contact`               | New user help / first-touch text                 | Show welcome + capabilities                | Wait for input    |
| `help`                        | Returning user `help`, `what can you do?`        | Show capabilities + text commands          | Wait for input    |
| `listing_video`               | Photos sent                                      | Check profile → auto-generate or ask style | Style or generate |
| `style_selection`             | `elegant`, `professional`, `energetic`           | Set style, ask to confirm                  | Confirm           |
| `confirm`                     | `go`, `ok`, `yes`, `done`                        | Start video generation                     | Processing        |
| `daily_insight`               | `daily insight`, market update text              | Acknowledge and enter daily-insight flow   | Generate insight  |
| `property_content`            | Listing / open house / address text              | Acknowledge and wait for photos or assets  | Collect media     |
| `revision`                    | Free text after DELIVERED job                    | Submit as video feedback                   | Re-processing     |
| `publish`                     | `publish`, `post` after delivery or insight      | Publish the current object                 | Done              |
| `redo`                        | `redo`, `again` after delivery                   | Restart from scratch                       | Processing        |
| `skip`                        | `skip`, `pass` after daily insight delivery      | Skip this insight                          | Done              |
| `insight_refine_shorter`      | `shorter` after daily insight delivery           | Submit as insight feedback                 | Re-render insight |
| `insight_refine_professional` | `more professional` after daily insight delivery | Submit as insight feedback                 | Re-render insight |
| `stop_push`                   | `stop push`, `pause push`, `no more`             | Disable daily insights                     | Confirmed         |
| `resume_push`                 | `resume push`, `start push`                      | Re-enable daily insights                   | Confirmed         |
| `off_topic`                   | Unrelated question                               | Rejection line + redirect                  | Wait for photos   |

---

## Text-Command Fallback Table

Every button interaction has a text equivalent. This is first-class, not a fallback.

| Button Label      | Text Command(s)                  | 中文                   |
| ----------------- | -------------------------------- | ---------------------- |
| [Elegant ✨]      | `elegant`                        | `优雅`                 |
| [Professional 💼] | `professional`                   | `专业`                 |
| [Energetic 🔥]    | `energetic`                      | `活力`                 |
| [Go / Confirm]    | `go`, `ok`, `yes`, `done`        | `好的`, `确认`, `开始` |
| [Publish]         | `publish`, `post`                | `发布`                 |
| [Adjust]          | `adjust`, `change` + description | `调整` + 说明          |
| [Redo]            | `redo`, `again`                  | `重做`                 |
| [Skip]            | `skip`, `pass`                   | `跳过`                 |
| [Stop Daily]      | `stop push`, `pause push`        | `停止推送`, `暂停推送` |
| [Resume Daily]    | `resume push`, `start push`      | `恢复推送`             |

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

---

## Callback Contract

### Delivered video

OpenClaw receives:

```json
{
  "type": "delivered",
  "job_id": "job-123",
  "agent_phone": "+60175029017",
  "video_url": "https://...",
  "caption": "...."
}
```

OpenClaw should:

1. Render the video and caption.
2. Offer publish / revise / redo actions.
3. Keep the latest delivered job in session or bridge state for future revisions.

### Daily insight

OpenClaw receives:

```json
{
  "type": "daily_insight",
  "agent_phone": "+60175029017",
  "agent_name": "Natalie",
  "insight": {
    "headline": "...",
    "caption": "...",
    "hashtags": ["#realestate"],
    "topic_type": "market_stat"
  },
  "image_urls": {
    "story_1080x1920": "https://..."
  }
}
```

OpenClaw should:

1. Validate that `headline`, `caption`, and at least one `image_urls` entry are present before user delivery.
2. Deliver the branded image + caption.
3. Offer only supported actions and commands.

Supported backend-safe daily-insight follow-ups:

- `publish`
- `skip`
- `shorter`
- `more professional`

---

## Test-Only Routing Endpoint

`POST /api/message` and `POST /api/router-test` are for:

- local dialogue evals
- regression tests
- prelaunch experience audits

They should not be treated as the production source of truth for Router behavior.

---

## OpenClaw External Follow-Up List

These items remain on the OpenClaw side and are not implemented in this repo:

1. Trust-first rendering
   Render trust/setup/pricing replies as short answers plus one starter task. Do not wrap them in long explanations.
2. Button and command alignment
   Only show refinement buttons that backend or runtime actually supports.
3. Interview-first runtime
   When the chosen path is interview-first or a starter task is returned, keep the user in a guided task instead of pushing the onboarding form immediately.
4. Insight-to-video handoff
   After a successful daily insight, add a clear CTA back into the video path.
5. Callback validation
   If `daily_insight` payloads arrive without `headline`, `caption`, or `image_urls`, trigger internal fallback or operator alerting instead of sending a broken message.
6. Session continuity
   Keep post-delivery revisions inside the revision session. Do not bounce the user into generic style prompts.
7. Ops context write-back
   If OpenClaw stores the latest successful path or useful session context, sync it back into operator-visible state.

### OpenClaw State Management

- Do **not** store style/music preferences in OpenClaw — backend profile is source of truth
- Do store: user's name, preferred language, and `last_job_id` for revision matching
- Do also read `lastDailyInsight` from bridge state when handling `publish / skip / shorter / more professional` after a daily insight render
- `last_job_id` is now **structured bridge state first**, session memory second
- Preferred read source: `~/.openclaw/workspace-realtor-social/.openclaw/reel-agent-bridge-state.json`
- Session memory for `last_job_id`: keep only as a lightweight fallback
- `last_job_id` must be refreshed after every successful `delivered` callback or revision response

---

## Environment Variables

```bash
REEL_AGENT_URL=http://localhost:8000
REEL_AGENT_TOKEN=your-secret-token
OPENCLAW_CALLBACK_BASE_URL=http://127.0.0.1:18789/reel-agent
OPENCLAW_CALLBACK_SECRET=replace-with-shared-callback-secret
```
