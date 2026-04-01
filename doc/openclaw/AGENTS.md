# AGENTS.md — Reel Agent (OpenClaw Side)

Behavior rules for the Reel Agent OpenClaw instance.

---

## Production Boundary

**D9 is now the source of truth:** OpenClaw owns user-facing intent recognition and API dispatch.

- OpenClaw is responsible for understanding the user's message, choosing the right API, and shaping the user-facing response.
- Reel Agent backend is responsible for production pipelines, profile storage, callbacks, and operator surfaces.
- `POST /api/message` and `POST /api/router-test` still exist, but they are **test-only** endpoints for local audits and regression baselines. Production traffic should not depend on them.

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
2. Deliver the image + caption.
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

---

## Environment Variables

```bash
REEL_AGENT_URL=http://localhost:8000
REEL_AGENT_TOKEN=your-secret-token
OPENCLAW_CALLBACK_BASE_URL=http://127.0.0.1:18789/reel-agent
OPENCLAW_CALLBACK_SECRET=replace-with-shared-callback-secret
```
