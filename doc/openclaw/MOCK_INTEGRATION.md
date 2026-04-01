# OpenClaw Mock 联调清单（Reel Agent 2.0）

> 目标：在不依赖真实 OpenClaw runtime 的前提下，先验证 Reel Agent 后端的生产 API 契约和 test-only router baseline。

## 一、当前接线模型

### 1) 生产态：OpenClaw → Reel Agent

OpenClaw 自己理解用户意图，再调用：

- `POST /webhook/in`
- `POST /webhook/feedback`
- `GET /api/profile/{phone}`
- `POST /api/daily-trigger`

### 2) 测试态：OpenClaw / audit script → Reel Agent

为了本地验证路由 baseline，可调用：

- `POST /api/message`
- `POST /api/router-test`

这两个接口是 **test-only**，不属于生产主链路。

### 3) 出站：Reel Agent → OpenClaw

后端通过 callback 向 OpenClaw 发事件：

- `progress`
- `delivered`
- `failed`
- `daily_insight`
- `onboarding_form`
- `form_completed`

---

## 二、这轮 mock 联调覆盖

### A. test-only router baseline

已验证：

1. trust-first 问题
   - `Is this an app? How do I use this?`
   - `How do I know this is secure and not spam?`
   - `How much per month?`
2. insight-first phrasing
   - `daily insight`
   - `I do not have a listing today but I want daily content`
3. post-render follow-up
   - delivered 后 revision
   - daily insight 后 `shorter` / `more professional`

### B. 生产 API 行为层

已验证：

1. `/webhook/in`
   - daily push 开关
   - 视频任务入队
2. `/webhook/feedback`
   - revision feedback 触发最小化重做
3. `/api/profile/{phone}`
   - 可返回 profile 和 readiness 上下文
4. `/api/daily-trigger`
   - daily pipeline 可被手动触发

### C. 出站 callback 契约

已验证：

1. `delivered`
2. `daily_insight` flat shape
3. `daily_insight` v2 content-pack shape

---

## 三、当前 mock 联调结论

### 已成立

- 生产主链路不再依赖 `/api/message`
- test-only router baseline 仍可用于 prelaunch 审计
- `daily_insight` callback 契约已兼容旧 flat shape 和 v2 content-pack shape
- console 已能展示推荐路径和建议下一步

### 仍需真实联调验证

1. OpenClaw Router Skill 是否真的不再先打 `/api/message`
2. OpenClaw 是否只展示真实支持的 refinement affordance
3. delivered 后 revision 会话是否稳定
4. daily insight 成功后是否加回视频 CTA
5. callback 缺字段时是否有 fallback / operator alert

---

## 四、建议的本地联调顺序

1. 跑 test-only baseline：

```bash
./.venv/bin/pytest -q tests/test_message_routing.py tests/test_openclaw_mock_integration.py
```

2. 直接测生产 API：
   - `GET /api/profile/{phone}`
   - `POST /webhook/in`
   - `POST /webhook/feedback`
   - `POST /api/daily-trigger`
3. 检查 callback bridge 是否能消费 `progress / delivered / daily_insight`
4. 最后再接真实 OpenClaw runtime
