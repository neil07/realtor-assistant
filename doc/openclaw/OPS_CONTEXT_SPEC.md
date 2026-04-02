# Ops Context Write-Back Specification

> How OpenClaw writes session context back to operator-visible state.
> Covers development-checklist Section 5.H (ops context 回流).

---

## Purpose

The operator console needs to answer two questions about every client:

1. **What path should this user go next?** (recommended path)
2. **What did the user just do?** (session lane + last action)

Today the backend provides `recommended_path` via the profile API, but the real-time session context lives in OpenClaw. This spec defines how OpenClaw writes that context to the shared bridge state so the console can display it.

---

## Bridge State File

**Path:** `~/.openclaw/workspace-realtor-social/.openclaw/reel-agent-bridge-state.json`

**Structure:**

```json
{
  "+10000000000": {
    "lastDelivery": {
      "job_id": "job-xxx",
      "timestamp": "2026-04-01T14:30:00Z",
      "video_url": "https://..."
    },
    "lastDailyInsight": {
      "timestamp": "2026-04-01T08:00:00Z",
      "headline": "..."
    },
    "sessionContext": {
      "current_lane": "delivered",
      "last_successful_path": "video",
      "last_recommended_path": "video_first",
      "starter_task_completed": true,
      "last_revision_round": 0,
      "updated_at": "2026-04-01T14:30:00Z"
    }
  }
}
```

---

## Fields

### Existing (already used by backend)

| Field              | Writer                 | Purpose                                        |
| ------------------ | ---------------------- | ---------------------------------------------- |
| `lastDelivery`     | Backend (via callback) | Tells OpenClaw the most recent delivered video |
| `lastDailyInsight` | Backend (via callback) | Tells OpenClaw the most recent daily insight   |

### New: `sessionContext` (written by OpenClaw)

| Field                    | Type     | Write when                                             | Example values                                                                                            |
| ------------------------ | -------- | ------------------------------------------------------ | --------------------------------------------------------------------------------------------------------- |
| `current_lane`           | string   | Every lane change                                      | `idle`, `video_generation`, `delivered`, `revision`, `daily_insight`, `awaiting_style`, `awaiting_photos` |
| `last_successful_path`   | string   | User completes video or insight flow                   | `video`, `insight`                                                                                        |
| `last_recommended_path`  | string   | Backend returns `recommended_path` in profile response | `video_first`, `insight_first`                                                                            |
| `starter_task_completed` | bool     | User successfully completes their first task           | `true`                                                                                                    |
| `last_revision_round`    | int      | Each revision submitted                                | `0`, `1`, `2`, `3`                                                                                        |
| `updated_at`             | ISO 8601 | Every write                                            | `2026-04-01T14:30:00Z`                                                                                    |

---

## Write Rules

### When to write

| Event                                  | Fields to update                                               |
| -------------------------------------- | -------------------------------------------------------------- |
| User sends photos                      | `current_lane = "video_generation"`                            |
| `delivered` callback received          | `current_lane = "delivered"`, `last_successful_path = "video"` |
| User publishes insight                 | `current_lane = "idle"`, `last_successful_path = "insight"`    |
| User skips insight                     | `current_lane = "idle"`                                        |
| User publishes video                   | `current_lane = "idle"`                                        |
| User sends revision                    | `current_lane = "revision"`, `last_revision_round++`           |
| Profile API returns `recommended_path` | `last_recommended_path = value`                                |
| User completes any starter task        | `starter_task_completed = true`                                |

### Write frequency

- Write on lane changes and significant events only.
- Do NOT write on every message (avoid unnecessary I/O).
- Always update `updated_at` on every write.

### Merge strategy

- Read the full file, update only the `sessionContext` block for the current `agent_phone`.
- Do NOT overwrite `lastDelivery` or `lastDailyInsight` (those are backend-managed).
- If the file doesn't exist, create it with the new entry.

---

## Console Consumption

The operator console reads this file to display:

| Console field                          | Source                                                                          |
| -------------------------------------- | ------------------------------------------------------------------------------- |
| "Recommended path" column on dashboard | `sessionContext.last_recommended_path` or backend profile `recommended_path`    |
| "Next best action" on client detail    | Derived from `current_lane` + `last_successful_path` + `starter_task_completed` |
| "Current status" badge                 | `sessionContext.current_lane`                                                   |

### Next best action derivation logic

```
IF starter_task_completed = false:
  → "Recommend starter task: {recommended_path}"

IF current_lane = "delivered":
  → "Waiting for user: publish / revise / redo"

IF current_lane = "revision":
  → "Revision in progress (round {last_revision_round})"

IF current_lane = "daily_insight":
  → "Daily insight delivered, waiting for: publish / skip"

IF last_successful_path = "video" AND no recent insight:
  → "Consider suggesting daily insight"

IF last_successful_path = "insight" AND no recent video:
  → "Consider suggesting listing video"

DEFAULT:
  → "Awaiting user engagement"
```

---

## Expiration

- `sessionContext` entries older than 7 days (by `updated_at`) should be treated as stale.
- Stale entries don't block rendering — just show "Last active: {date}" instead of live status.
- Do NOT auto-delete stale entries. They provide historical context.

---

## Migration

This is a net-new addition. No migration needed for existing bridge state files — the `sessionContext` key simply won't exist for users who haven't had a session yet. Console should handle missing `sessionContext` gracefully (show "No session data" or equivalent).
