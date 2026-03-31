# OpenClaw 真实联调脚本（Reel Agent 2.0）

> 目的：按当前真实接线契约，逐步验证 OpenClaw ↔ Reel Agent 的消息路由、任务触发、回调、revision、daily trigger。

## 0. 环境变量

```bash
export REEL_AGENT_URL=http://localhost:8000
export REEL_AGENT_TOKEN=replace-with-shared-bearer-token
export AGENT_PHONE=+10000000000
export CALLBACK_URL=https://your-openclaw-gateway/events
export MSG_ID=test-msg-001
```

所有受保护接口都要带：

```bash
-H "Authorization: Bearer $REEL_AGENT_TOKEN"
```

---

## 1. help / 首触达

```bash
curl -s -X POST "$REEL_AGENT_URL/api/message" \
  -H "Authorization: Bearer $REEL_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_phone": "'"$AGENT_PHONE"'",
    "text": "help",
    "has_media": false,
    "media_paths": [],
    "callback_url": "'"$CALLBACK_URL"'"
  }' | jq
```

预期：
- `intent = first_contact` 或 `help`
- `action = welcome`
- 有 `response`

---

## 2. Daily Insight 文本触发

```bash
curl -s -X POST "$REEL_AGENT_URL/api/message" \
  -H "Authorization: Bearer $REEL_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_phone": "'"$AGENT_PHONE"'",
    "text": "daily insight",
    "has_media": false,
    "media_paths": [],
    "callback_url": "'"$CALLBACK_URL"'"
  }' | jq
```

预期：
- `intent = daily_insight`
- `action = start_daily_insight`

注意：这里当前只验证路由和 OpenClaw 编排入口，不直接创建后台 job。

---

## 3. Property Content 文本触发

```bash
curl -s -X POST "$REEL_AGENT_URL/api/message" \
  -H "Authorization: Bearer $REEL_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_phone": "'"$AGENT_PHONE"'",
    "text": "123 Main St open house this Sunday 2pm",
    "has_media": false,
    "media_paths": [],
    "callback_url": "'"$CALLBACK_URL"'"
  }' | jq
```

预期：
- `intent = property_content`
- `action = start_property_content`
- `awaiting = media_or_missing_property_context`

---

## 4. 发图 → listing video 路由

```bash
curl -s -X POST "$REEL_AGENT_URL/api/message" \
  -H "Authorization: Bearer $REEL_AGENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_phone": "'"$AGENT_PHONE"'",
    "text": "",
    "has_media": true,
    "media_paths": ["/tmp/job-1/photos/front.jpg"],
    "callback_url": "'"$CALLBACK_URL"'"
  }' | jq
```

预期：
- `intent = listing_video`
- 如果 profile 有 style：
  - `auto_generate = true`
- 如果 profile 没 style：
  - `awaiting = style_selection`

---

## 5. 触发后台生成（OpenClaw → /webhook/in）

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

## 6. revision（OpenClaw → /webhook/feedback）

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

## 7. daily push 开关

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

## 8. 手动触发 daily scheduler

```bash
curl -s -X POST "$REEL_AGENT_URL/api/daily-trigger?secret=" \
  -H "Authorization: Bearer $REEL_AGENT_TOKEN" | jq
```

预期：
- 返回 run summary
- 若当前 agent 是 active 且 daily_push_enabled=true，应向 callback_url 对应的 OpenClaw 侧发送 `daily_insight` 事件

---

## 9. OpenClaw 侧回调验收项

收到后端回调时，至少检查这些事件：

### progress
- `type=progress`
- `job_id`
- `openclaw_msg_id`
- `agent_phone`
- `step`
- `message`

### delivered
- `type=delivered`
- `job_id`
- `video_url`
- `caption`
- `scene_count`
- `aspect_ratio`

### failed
- `type=failed`
- `job_id`
- `error`
- `retry_count`

### daily_insight
- `type=daily_insight`
- `agent_phone`
- `insight.headline`
- `insight.caption`
- `insight.hashtags`
- `image_urls`

---

## 10. 当前高风险检查点

1. OpenClaw 是否真的把所有用户消息先打 `/api/message`
2. `callback_url` 是否真实落到 OpenClaw 可消费的事件入口
3. OpenClaw 是否保存并传回最近一次 `job_id` 用于 revision
4. delivered / daily_insight 到用户端的最终渲染是否符合产品预期
