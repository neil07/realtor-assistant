# OpenClaw 真实联调脚本（Reel Agent 2.0）

> 目的：按 D9 之后的真实接线契约，验证 OpenClaw Router Skill 是否直接调用生产 API，而不是把生产流量交给 `/api/message`。

## 0. 环境变量

先确保本机 OpenClaw 接线层已从 repo 安装：

```bash
/Users/lsy/projects/realtor-social/scripts/openclaw/install-local-wiring.sh
```

```bash
export REEL_AGENT_URL=http://127.0.0.1:8000
export REEL_AGENT_TOKEN=replace-with-shared-bearer-token
export AGENT_PHONE=+10000000000
export OPENCLAW_CALLBACK_BASE_URL=http://127.0.0.1:18789/reel-agent
export OPENCLAW_CALLBACK_SECRET=replace-with-shared-callback-secret
export CALLBACK_URL="$OPENCLAW_CALLBACK_BASE_URL/events"
export MSG_ID=test-msg-001
```

---

Repo-owned bridge source of truth:

- `/Users/lsy/projects/realtor-social/openclaw/extensions/reel-agent-bridge`
- install / relink via `/Users/lsy/projects/realtor-social/scripts/openclaw/install-local-wiring.sh`

Do not use:

- Telegram transport webhook paths such as `/telegram-webhook`
- `"$OPENCLAW_GATEWAY_URL"/api/sessions/main/messages`

Bridge auth: `X-Reel-Secret: $OPENCLAW_CALLBACK_SECRET`

---

## 1. 先查 profile

```bash
curl -s -X GET "$REEL_AGENT_URL/api/profile/$AGENT_PHONE" \
  -H "Authorization: Bearer $REEL_AGENT_TOKEN" | jq
```

确认：

- 有没有 style
- readiness 如何
- OpenClaw 应该推视频、资讯还是先做 interview-first

---

## 2. 发图走视频主链路

```bash
curl -s -X POST "$REEL_AGENT_URL/webhook/in" \
  -H "Authorization: Bearer $REEL_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_phone": "'"$AGENT_PHONE"'",
    "photo_paths": ["/tmp/job-1/photos/front.jpg"],
    "callback_url": "'"$CALLBACK_URL"'",
    "openclaw_msg_id": "'"$MSG_ID"'",
    "params": {
      "style": "professional",
      "music": "modern",
      "language": "en",
      "aspect_ratio": "9:16"
    }
  }' | jq
```

预期：

- 返回 `job_id`
- 返回 `status = QUEUED`

---

## 3. revision 走反馈链路

```bash
export LAST_JOB_ID=replace-with-real-job-id

curl -s -X POST "$REEL_AGENT_URL/webhook/feedback" \
  -H "Authorization: Bearer $REEL_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "job_id": "'"$LAST_JOB_ID"'",
    "agent_phone": "'"$AGENT_PHONE"'",
    "feedback_text": "make the music more upbeat",
    "revision_round": 1
  }' | jq
```

预期：

- 返回新的 `job_id`
- 有 `re_run_from`
- 有 `classified`

---

## 4. daily insight 走 daily trigger

```bash
curl -s -X POST "$REEL_AGENT_URL/api/daily-trigger?secret=" \
  -H "Authorization: Bearer $REEL_AGENT_TOKEN" | jq
```

预期：

- scheduler run once
- OpenClaw bridge 收到 `daily_insight`

---

## 5. daily push 开关

### disable

```bash
curl -s -X POST "$REEL_AGENT_URL/webhook/in" \
  -H "Authorization: Bearer $REEL_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_phone": "'"$AGENT_PHONE"'",
    "photo_paths": [],
    "params": {"action": "disable_daily_push"}
  }' | jq
```

### enable

```bash
curl -s -X POST "$REEL_AGENT_URL/webhook/in" \
  -H "Authorization: Bearer $REEL_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_phone": "'"$AGENT_PHONE"'",
    "photo_paths": [],
    "params": {"action": "enable_daily_push"}
  }' | jq
```

---

## 6. Callback 验证清单

OpenClaw bridge 必须能消费：

- `progress`
- `delivered`
- `failed`
- `daily_insight`
- `onboarding_form`
- `form_completed`

### `daily_insight` 关键字段

收到 callback 后先检查：

- `insight.headline`
- `insight.caption`
- `image_urls`

缺任何一个都不应直接发给用户。

---

## 7. test-only baseline

如果要验证本地路由桩，而不是生产主链路，可单独调用：

- `POST /api/message`
- `POST /api/router-test`

用途仅限：

- prelaunch 审计
- regression baseline
- no-OpenClaw 本地联调

不要把这一步当成生产联调必经节点。
