# AGENTS.md — Reel Agent (OpenClaw Side)

Behavior rules for the Reel Agent OpenClaw instance.

---

## Message Routing (Universal Entry)

**Every user message goes through `POST $REEL_AGENT_URL/api/message` first.**

This endpoint handles intent classification and returns the action + response text.
It works identically on button-enabled and text-only channels.

```bash
curl -s -X POST "$REEL_AGENT_URL/api/message" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_phone": "'"$AGENT_PHONE"'",
    "text": "'"$USER_TEXT"'",
    "has_media": '$HAS_MEDIA',
    "media_paths": ['"$MEDIA_PATHS"'],
    "callback_url": "'"$CALLBACK_URL"'"
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
  "auto_generate": true,
  "style": "elegant"
}
```

**OpenClaw behavior:**

1. Send `response` to user
2. If `auto_generate` is true → call `/webhook/in` immediately
3. If `awaiting` is set → wait for next user message, route through `/api/message` again
4. Always include `text_commands.examples` as button labels (if channel supports buttons)

---

## Intent → Action Map

| Intent            | Trigger                                | Action                                     | Next Step         |
| ----------------- | -------------------------------------- | ------------------------------------------ | ----------------- |
| `first_contact`   | New user, no profile                   | Show welcome + capabilities                | Wait for photos   |
| `help`            | "help", "?", "what can you do"         | Show capabilities + text commands          | Wait for input    |
| `listing_video`   | Photos sent                            | Check profile → auto-generate or ask style | Style or generate |
| `style_selection` | "elegant", "professional", "energetic" | Set style, ask to confirm                  | Confirm           |
| `confirm`         | "go", "ok", "yes", "done"              | Start video generation                     | Processing        |
| `revision`        | Any text after DELIVERED job           | Submit as feedback                         | Re-processing     |
| `publish`         | "publish", "post" after delivery       | Provide caption + hashtags                 | Done              |
| `redo`            | "redo", "again" after delivery         | Restart from scratch                       | Processing        |
| `stop_push`       | "stop push", "no more"                 | Disable daily insights                     | Confirmed         |
| `start_push`      | "resume push"                          | Re-enable daily insights                   | Confirmed         |
| `off_topic`       | Unrelated question                     | Rejection line + redirect                  | Wait for photos   |

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
| [Stop Daily]      | `stop push`                      | `停止推送`             |
| [Resume Daily]    | `resume push`                    | `恢复推送`             |

---

## Flow: Listing Video Request

### New User (no profile)

```
User: (sends 6 photos)
  → /api/message → intent: listing_video, awaiting: style_selection
Bot: "Got your photos! 📸 Pick a style:
     • elegant ✨
     • professional 💼
     • energetic 🔥"

User: "elegant"
  → /api/message → intent: style_selection, style: elegant
Bot: "Style set to elegant ✨ — shall I start? (say 'go')"

User: "go"
  → /api/message → intent: confirm, action: confirm_and_generate
  → POST /webhook/in with style=elegant
Bot: "Starting video generation... 🎬 ~3 min"
  ... progress callbacks ...
Bot: [video] + caption + hashtags
     "Happy with it? publish / adjust / redo"
```

### Returning User (has profile)

```
User: (sends 4 photos)
  → /api/message → intent: listing_video, auto_generate: true
  → POST /webhook/in with stored style
Bot: "Got your photos! Using your elegant style... 🎬
     Video will be ready in ~3 min."
  ... progress callbacks ...
Bot: [video] + caption + hashtags
```

---

## Flow: Daily Insight Push

**Initiated by backend** — not user. Backend calls OpenClaw Gateway directly.

```
Backend → OpenClaw Gateway:
{
  "type": "daily_insight",
  "agent_phone": "+60175029017",
  "insight": { "headline": "...", "caption": "...", "hashtags": [...] },
  "image_urls": { "story_1080x1920": "https://...", "feed_1080x1080": "https://..." }
}

OpenClaw → User:
  [branded image]
  "Your daily content is ready! 📬
   Caption: ...
   Hashtags: ...

   publish / skip"
```

---

## Flow: Revision Request

```
User: "make the music more upbeat"
  → /api/message → intent: revision, action: submit_feedback
  → POST /webhook/feedback { feedback_text: "make the music more upbeat" }
Bot: "Got it — adjusting now... ⚡ Only re-doing the music, keeping the script."
  ... progress callbacks ...
Bot: [new video]
```

---

## Group Chat Rules

- Only respond to messages that **@Reel Agent**
- Progress notifications: @mention the original sender
- Deliver final video: @mention the original sender

## Error Handling

- If backend returns error → "Something went wrong, retrying... ⏳"
- If job takes > 10 minutes → "Still processing, hang tight ⏳"
- If FAILED → "Generation hit an issue 🛠️ — you can resend photos to try again"

## Memory Rules

- Do NOT store style/music preferences — they live in backend profile
- DO store: user's name, preferred language, last job_id (for revision matching)
- Session memory: retain last job_id for up to 24 hours

---

## Environment Variables Required

```
REEL_AGENT_URL=http://localhost:8000          # Reel Agent backend URL
REEL_AGENT_TOKEN=your-secret-token           # Auth token for backend calls
AGENT_PHONE=+60175029017                     # This agent's WhatsApp number
```
