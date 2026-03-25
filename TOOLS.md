# TOOLS.md - Local Notes

Skills define _how_ tools work. This file is for _your_ specifics — the stuff that's unique to your setup.

## What Goes Here

Things like:

- Camera names and locations
- SSH hosts and aliases
- Preferred voices for TTS
- Speaker/room names
- Device nicknames
- Anything environment-specific

## IMA Studio Skills (mandatory for video pipeline)

For **image-to-video** and **TTS** API calls, use IMA Studio skills instead of direct Seedance/Runway/ElevenLabs:

- **ima-video-ai** skill: `~/.openclaw/workspace/skills/ima-video-ai/`
  - Script: `scripts/ima_video_create.py`
  - Use for: image_to_video, first_last_frame_to_video, text_to_video
  - Default i2v model: Wan 2.6 (`wan2.6-i2v`, 25 pts)
  - Premium: Kling O1 (`kling-video-o1`, 48 pts)
  - Env: `IMA_API_KEY`

- **ima-all-ai** skill: `~/.openclaw/workspace/skills/ima-all-ai/`
  - Script: `scripts/ima_create.py`
  - Use for: all media types (image, video, music, TTS)
  - TTS: `text_to_speech` task type via IMA API
  - Music: Suno (`sonic`), DouBao BGM (`GenBGM`)
  - Env: `IMA_API_KEY`

**Pipeline mapping:**
| Step | Implementation |
|------|---------------|
| AI video generation | `render_ai_video.py` → IMA (primary) → Seedance (fallback 1) → Runway (fallback 2) |
| TTS | `ima_create.py --task-type text_to_speech` |
| Music | `ima_create.py --task-type text_to_music` |

Note: `render_ai_video.py` now calls `ima_video_create.py` via subprocess internally.
Agent does NOT need to call `ima_video_create.py` directly for the video pipeline.

## Google Cloud Storage (video delivery)

- **Bucket**: `openclaw-videos` (override with `GCS_BUCKET` env var)
- **Auth**: `GOOGLE_APPLICATION_CREDENTIALS` env var pointing to service account JSON
- **Script**: `skills/listing-video/scripts/upload_gcs.py`
- **Blob path**: `videos/{listing_id}/{filename}.mp4`
- **Public URL**: `https://storage.googleapis.com/openclaw-videos/videos/{listing_id}/...`

## Google Cloud Storage (视频交付)

- Bucket: `gs://reel-agent-videos/`
- Public URL: `https://storage.googleapis.com/reel-agent-videos/<filename>`
- 权限: allUsers:objectViewer（上传即公开）
- 账户: yaosj07@gmail.com (gcloud auth)
- 上传命令: `gsutil cp <file> gs://reel-agent-videos/<name>.mp4`

## Why Separate?

Skills are shared. Your setup is yours. Keeping them apart means you can update skills without losing your notes, and share skills without leaking your infrastructure.

---

Add whatever helps you do your job. This is your cheat sheet.
