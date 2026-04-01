# Manual Review Notes

## Scope

- Surfaces reviewed:
  - `console/router.py`
  - `console/templates/onboarding.html`
  - `console/templates/onboarding_form.html`
  - `console/templates/form_done.html`
  - `console/templates/dashboard.html`
  - `console/templates/client_detail.html`
  - `console/memory_schema.py`
  - `orchestrator/progress_notifier.py`
  - `doc/prelaunch-experience/mock-output-packs.json`
- Evidence mode:
  - page/template/code review
  - mock output pack review
  - baseline pytest failure cross-check

## Initialization And Activation

### INIT-E2-A5-01 / INIT-E2-A5-02

- Evidence:
  - `console/router.py` onboarding invite says `To create your first FREE listing video, I need 60 seconds of your time`
  - `console/templates/onboarding_form.html` headline says `Help us personalize your content — takes about 1 minute.`
  - `console/templates/form_done.html` only tells the user to send listing photos next time.
- Finding:
  - onboarding is framed as a prerequisite before first value, not an accelerator after first value
  - form completion is a dead-end and reinforces only the video lane
- Friction codes:
  - `INIT-05`
  - `VALUE-01`
  - `VALUE-03`
- Full-chain fix ownership:
  - `console`: reframe the form as optional acceleration, not required setup
  - `OpenClaw`: offer a skip-the-form starter task for skeptical users
  - `backend`: allow first trial without form-gated readiness assumptions

### INIT-E3-A6-01

- Evidence:
  - no implemented interview-first starter-task surface exists in console or `/api/message`
  - mock packs `T2`, `T3`, `T5` show the intended assistant-style task framing, but current product surfaces do not expose it
- Finding:
  - interview-first is still a concept, not a runnable path
  - the product has no concrete "starter tasks" layer after a conversation
- Friction codes:
  - `INIT-06`
  - `VALUE-04`
- Full-chain fix ownership:
  - `OpenClaw`: generate and present short starter tasks after trust-building chat
  - `backend`: expose a minimal next-step recommendation contract instead of only raw intent lanes
  - `console`: show the recommended path and pending first task for operators

### INIT-E2-A8-01 / INIT-E2-A1-01 / INIT-E2-A4-01

- Evidence:
  - there is no implemented landing page surface in repo; only onboarding/console exists
  - mock packs `T1`, `T2`, `T5` define good CTA behavior, but no page implements them
- Finding:
  - landing-page entry promises cannot be validated in code today
  - path choice between video-first and insight-first is therefore unsupported at this surface
- Friction codes:
  - `INIT-03`
  - `INIT-05`
- Full-chain fix ownership:
  - `console/frontend`: build a single-primary-CTA landing entry before claiming the path exists
  - `OpenClaw`: if the landing page remains absent, keep the first-use decision inside the chat experience

## Video And Insight Experience

### VIDEO-P1-03

- Evidence:
  - mock pack `V4` shows progress text like `SCRIPTING COMPLETE. PROMPTING STARTED. PRODUCING FRAME SEQUENCES.`
  - current server progress contract is pipeline-step oriented, not agent-assistant oriented
- Finding:
  - progress updates are at risk of sounding like internal logs instead of assistant reassurance
- Friction codes:
  - `FLOW-01`
  - `FLOW-02`
- Full-chain fix ownership:
  - `backend`: emit user-facing progress states, not internal step names
  - `OpenClaw`: phrase progress in conversational language and time anchors

### VIDEO-P1-04 / VIDEO-P1-05

- Evidence:
  - mock pack `V1` is strong and publishable
  - live HTTP evidence shows post-delivery free-text style requests get hijacked into `style_selection`
- Finding:
  - delivery quality can be good, but the revision lane is not stable enough to preserve trust
- Friction codes:
  - `FLOW-03`
  - `OUTPUT-05`
- Full-chain fix ownership:
  - `backend`: make delivered-context revision precedence beat bare style keyword matching
  - `OpenClaw`: keep "adjust" inside a revision lane instead of turning it into a global style reset

### INSIGHT-P2-01 / INSIGHT-P2-03 / INSIGHT-P2-04

- Evidence:
  - exact `daily insight` phrasing works
  - live HTTP evidence shows `shorter` is rejected and `more professional` is repurposed as style selection
  - `doc/openclaw/AGENTS.md` still teaches those refinement commands via `text_commands.examples`
- Finding:
  - insight-first works only for the narrow canonical phrase
  - the refinement contract is broken across backend and OpenClaw-facing examples
  - there is no explicit handoff from insight back to video
- Friction codes:
  - `INIT-04`
  - `FLOW-04`
  - `MEM-04`
- Full-chain fix ownership:
  - `backend`: support refinement intents or remove them from hints
  - `OpenClaw`: do not render unsupported refinement buttons/examples
  - `shared contract`: add contract tests for every command shown to the user

### INSIGHT Callback Contract

- Evidence:
  - baseline pytest failure: `test_progress_notifier_daily_insight_uses_bridge_contract`
  - `orchestrator/progress_notifier.py` currently reads `briefing.headline`, `social_post.caption`, `_meta.topic_type`
  - failing test passes flat insight fields and expects them to survive into the callback payload
- Finding:
  - the backend and bridge contract disagree on the insight payload shape
  - even if insight-first routing works, downstream delivery can still lose critical fields
- Friction codes:
  - `OUTPUT-04`
  - `FLOW-04`
- Full-chain fix ownership:
  - `backend`: normalize both flat and v2 content-pack shapes before sending callback payloads
  - `shared contract`: freeze one callback schema and test it on both sides
  - `OpenClaw`: validate required fields before rendering a user-facing insight card

## Operator Surfaces

### OPS-DASH-01

- Evidence:
  - `console/templates/dashboard.html` shows only total count, readiness badges, form state, completeness
  - `console/memory_schema.py` computes readiness only for `video` and `insight`
- Finding:
  - dashboard can tell who is "ready", but not who should go `video-first`, `insight-first`, or `interview-first`
  - the operator is left with state, not guidance
- Friction codes:
  - `OPS-01`
  - `OPS-02`
- Full-chain fix ownership:
  - `console`: add recommended path and next action per client
  - `backend`: expose a lightweight path recommendation signal
  - `OpenClaw`: surface whether the user is in trust-building, activation, or revision mode

### OPS-CLIENT-01

- Evidence:
  - `client_detail.html` shows field completeness, skill briefs, and missing fields by collection channel
  - "待完成事项" is channel-centric (`Bot 待问`, `你来聊`, `表单收集`), not outcome-centric
- Finding:
  - client detail helps data collection, but still does not answer "what should happen next"
  - skill brief editing is powerful but feels internal and operationally heavy
- Friction codes:
  - `OPS-02`
  - `OPS-04`
- Full-chain fix ownership:
  - `console`: show one recommended next move, not only missing-field bins
  - `backend`: compute path + next action from profile completeness plus recent interaction state
  - `OpenClaw`: feed back the last meaningful user action so ops can understand context

### OPS-ONBOARD-01

- Evidence:
  - `console/templates/onboarding.html` displays `视频就绪` and `洞察就绪` immediately after sending the form link
  - `console/router.py` form completion callback tells operators `Video Ready ✅ — you can now send listing photos.`
- Finding:
  - operator UI overstates readiness before the user has actually taken the next action
  - the completion path still privileges video over insight
- Friction codes:
  - `OPS-01`
  - `VALUE-04`
- Full-chain fix ownership:
  - `console`: replace binary readiness marketing with actual state progression
  - `backend`: distinguish `profile complete` from `activation successful`
  - `OpenClaw`: route completed-form users to the best next trial instead of always video

## Longitudinal Risks

### LONG-P3-01 / LONG-P10-01 / LONG-P20-01 / LONG-P20-02

- Evidence:
  - live HTTP evidence still shows returning revision commands collapsing into style setup
  - `console/memory_schema.py` tracks readiness, not lane preference or activation history
  - no operator view exposes whether the user prefers video-first, insight-first, or interview-first
- Finding:
  - memory is present for profile fields, but weak for behavioral adaptation
  - the product does not yet make growth visible across the first, tenth, and twentieth use
- Friction codes:
  - `MEM-01`
  - `MEM-02`
  - `MEM-03`
  - `MEM-04`
- Full-chain fix ownership:
  - `backend`: persist path preference and revision outcomes
  - `console`: display path history and confidence
  - `OpenClaw`: tailor prompts based on last successful lane, not only static preferences
