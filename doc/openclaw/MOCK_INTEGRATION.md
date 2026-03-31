# OpenClaw Mock 联调清单（Reel Agent 2.0）

> 目标：在不依赖真实 OpenClaw 机器人编排的前提下，先验证 Reel Agent 后端是否满足当前接线契约。

## 一、当前接线模型

### 1) 入站：OpenClaw → Reel Agent

OpenClaw 收到用户消息后，统一先打：

- `POST /api/message`

根据返回结果再决定：

- 只回复文案
- 等待下一轮文本/图片
- 触发 `POST /webhook/in`
- 触发 `POST /webhook/feedback`

### 2) 出站：Reel Agent → OpenClaw

后端通过 callback 向 OpenClaw 发事件：

- `progress`
- `delivered`
- `failed`
- `daily_insight`
- （console onboarding 还有 `onboarding_form` / `form_completed`）

默认回调目标：

- `OPENCLAW_CALLBACK_BASE_URL + /events`

或使用 job 上携带的 `callback_url`。

---

## 二、这轮 mock 联调实际覆盖

### A. `/api/message` 路由层

已验证：

1. 新用户 `daily insight`
   - 预期：`daily_insight / start_daily_insight`
   - 结果：通过

2. 老用户 + 最近一单已 DELIVERED，再发 property text
   - 输入：`123 Main St open house this Sunday 2pm`
   - 预期：优先走 `property_content / start_property_content`，不能误判成 revision
   - 结果：通过

### B. `/webhook/in` 行为层

已验证：

3. daily push control
   - 输入：`params.action = disable_daily_push`
   - 预期：更新 profile 的 `content_preferences.daily_push_enabled = false`
   - 结果：通过

4. 视频生成主路径
   - 输入：带 `photo_paths + callback_url + openclaw_msg_id + params`
   - 预期：创建 job，并调用 dispatcher.submit(job_id)
   - 结果：通过

### C. 出站 callback 契约

已验证：

5. delivered callback
   - 预期字段：
     - `type=delivered`
     - `job_id`
     - `openclaw_msg_id`
     - `agent_phone`
     - `video_url`
     - `caption`
     - `scene_count`
     - `word_count`
     - `aspect_ratio`
   - 结果：通过

---

## 三、当前 mock 联调结论

### 已成立

- `/api/message` 已能作为统一文本入口
- 新用户不会再被错误打回 welcome，能直接进入：
  - `daily insight`
  - `property content`
- `/webhook/in` 已能承接：
  - daily push 开关
  - 视频任务入队
- `ProgressNotifier` 的 `delivered` 事件已满足 OpenClaw 消费所需的最小字段

### 仍需真实联调验证

1. **OpenClaw 侧 action 编排是否已接好**
   - `start_daily_insight` 返回后，OpenClaw 是仅回复文案，还是还要继续触发某个 skill？
   - `start_property_content` 返回后，OpenClaw 是否正确等待用户继续发图，而不是误结束会话？

2. **callback_url 的真实落点**
   - 当前文档默认是 `/events`
   - 需要和真实 OpenClaw gateway / agent runtime 的事件入口完全对齐

3. **delivered / daily_insight 的用户态渲染**
   - OpenClaw 是否会把：
     - 视频文件/URL
     - caption
     - publish / adjust / redo
     这些按预期发回终端

4. **revision 流的真实 last_job_id 绑定**
   - mock 已证实分类没问题
   - 但真实 OpenClaw 是否正确持有并传回最近一次 `job_id`，还需真联调

---

## 四、findings first（高置信）

### Finding 1：新用户主链路误路由

- 文件：`server.py`
- 问题：此前 `not profile` 判断过早，新用户的 `daily insight / property content` 会直接被打回 welcome。
- 状态：已修复，并已被测试覆盖。

### Finding 2：缺少 API 级接线回归

- 文件：`tests/test_openclaw_mock_integration.py`
- 问题：之前只有 `_classify_intent` 级别测试，没有验证真实 HTTP 入口和 callback 契约。
- 状态：已补 mock 联调测试。

### Finding 3：鉴权契约已补齐

- 文档里要求：
  - `Authorization: Bearer $REEL_AGENT_TOKEN`
- 当前 `server.py` 已对这些 OpenClaw-facing 接口补上 Bearer token 校验：
  - `/api/message`
  - `/webhook/in`
  - `/webhook/feedback`
  - `/api/daily-trigger`
- 行为：
  - 未设置 `REEL_AGENT_TOKEN` 时：兼容本地开发，允许无鉴权
  - 设置后：缺失或错误 token 返回 `401`

---

## 五、建议的真实联调顺序

1. OpenClaw 发一条 `help`
2. OpenClaw 发一条 `daily insight`
3. OpenClaw 发一条 property text
4. OpenClaw 发一张/多张图片，确认 `/api/message -> start_video` 行为
5. OpenClaw 在 `auto_generate=true` 时打 `/webhook/in`
6. 后端回发 `progress / delivered`
7. 用户发 revision 文本，确认 `/webhook/feedback`
8. 手动触发 `POST /api/daily-trigger`，确认 `daily_insight` callback 到 OpenClaw

---

## 六、如何跑本地 mock 联调测试

```bash
./.venv/bin/pytest -q tests/test_message_routing.py tests/test_openclaw_mock_integration.py
```

预期：全部通过。
