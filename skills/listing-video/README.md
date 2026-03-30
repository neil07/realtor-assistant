# 🎬 Listing Video Agent (Reel Agent)

A single-purpose AI agent that turns real estate listing photos into social media marketing videos.

## What It Does

Send listing photos → Get a ready-to-post marketing video with AI-generated cinematic clips, professional voiceover, and music.

**That's it. Nothing else.**

## How It Works

```
Photos → Vision Analysis → Smart Questions → Storyboard →
AI Video + Slideshow + Voiceover + Music → Final Video (vertical + horizontal)
```

## Tech Stack

| Component        | Tool                   | Cost/video |
| ---------------- | ---------------------- | ---------- |
| Photo Analysis   | Claude Sonnet (Vision) | $0.02      |
| Voiceover Script | Claude Sonnet          | $0.01      |
| AI Video Clips   | Runway Gen-4 Turbo     | $0.75      |
| TTS Voiceover    | ElevenLabs v2          | $0.12      |
| Photo Effects    | ffmpeg (local)         | $0.00      |
| Final Assembly   | ffmpeg (local)         | $0.00      |
| **Total**        |                        | **~$0.90** |

## Required API Keys

```bash
RUNWAY_API_KEY=       # https://dev.runwayml.com
ELEVENLABS_API_KEY=   # https://elevenlabs.io
ANTHROPIC_API_KEY=    # Already configured in OpenClaw
# Optional fallbacks:
GEMINI_API_KEY=       # For Veo 3.1 fallback
OPENAI_API_KEY=       # For OpenAI TTS fallback
```

## Features

- 📸 Intelligent photo analysis (room detection, quality scoring, auto-sort)
- 🎥 Selective AI video generation (hero shots only, cost-efficient)
- 🎤 Natural voiceover scripts (sounds like a real agent, not a brochure)
- 🎙️ Voice cloning (agent's own voice on all future videos)
- 🎵 Background music with voice ducking
- 📱 Dual format output (9:16 vertical + 16:9 horizontal)
- 👤 Per-agent profiles (preferences remembered, never re-asked)
- 🔄 Up to 3 revision rounds per video

## Project Structure

```
skills/listing-video/
├── SKILL.md              # Agent behavior definition
├── README.md             # This file
├── scripts/
│   ├── analyze_photos.py     # Vision analysis
│   ├── generate_script.py    # Voiceover copywriting
│   ├── render_ai_video.py    # Runway API
│   ├── render_slideshow.py   # ffmpeg Ken Burns
│   ├── generate_voice.py     # ElevenLabs TTS
│   ├── assemble_final.py     # Final composition
│   └── profile_manager.py    # Agent profiles
├── prompts/
│   ├── photo_analysis.md     # Vision prompt
│   ├── voiceover_script.md   # Script prompt
│   ├── smart_questions.md    # Question logic
│   └── storyboard.md         # Narrative structure
├── templates/
│   ├── energetic.json        # Fast, bold, upbeat
│   ├── elegant.json          # Slow, serif, piano
│   └── professional.json     # Clean, modern, balanced
├── assets/
│   ├── music/                # Royalty-free BGM
│   ├── fonts/                # Display fonts
│   └── overlays/             # CTA templates
└── profiles/                 # Per-agent data
```

## Status

🟡 **In Development**

- [x] SKILL.md — Agent behavior spec
- [x] Prompts — Photo analysis, voiceover script, questions, storyboard
- [x] Scripts — All 7 pipeline scripts (interface defined)
- [x] Templates — 3 style presets
- [ ] API integration testing (Runway, ElevenLabs)
- [ ] BGM library (royalty-free tracks)
- [ ] Font assets
- [ ] End-to-end test with real listing photos
- [ ] WhatsApp channel connection
- [ ] Voice cloning flow testing
