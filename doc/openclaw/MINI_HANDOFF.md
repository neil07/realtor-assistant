# Mini 机 Claude 执行交接文档

> 把这段直接贴给 mini 机上的 Claude，让它接着干。

---

## 给 Claude 的执行指令

```
你现在要在 OpenClaw runtime 侧完成 Reel Agent 的生产接线。

## 背景

Reel Agent 是一个 WhatsApp bot，帮房产经纪人把 listing 照片变成社媒营销短视频。
架构是三层：OpenClaw（对话路由 + UI）→ Reel Agent 后端（pipeline 执行）→ IMA Studio（视频生成）。

D9 决策已确定：生产态意图识别归 OpenClaw Router Skill，Reel Agent 后端的 /api/message 只是 test-only baseline。

后端已全部就绪（49 tests 全绿，4 个生产 API 已实现），OpenClaw 侧的 8 项工作需要你来完成。

## 后端生产 API（已实现，直接调用）

| API | 用途 | Auth |
|-----|------|------|
| `GET $REEL_AGENT_URL/api/profile/{phone}` | 读取用户偏好（style, market_area 等） | Bearer $REEL_AGENT_TOKEN |
| `POST $REEL_AGENT_URL/webhook/in` | 启动视频生成 / daily push 开关 | Bearer $REEL_AGENT_TOKEN |
| `POST $REEL_AGENT_URL/webhook/feedback` | 提交 revision 反馈 | Bearer $REEL_AGENT_TOKEN |
| `POST $REEL_AGENT_URL/api/daily-trigger` | 触发 daily insight 生成 | Bearer $REEL_AGENT_TOKEN |

后端会向 `$OPENCLAW_CALLBACK_BASE_URL/events` 发送 callback（progress/delivered/failed/daily_insight 等），header 带 `X-Reel-Secret`。

## 你需要做的 8 件事

### A. Router Skill 落地
OpenClaw 不再把生产流量打 `/api/message`，而是直接根据用户消息调用上面 4 个 API。
完整的 Router Skill system prompt 已经写好，在仓库的 `doc/openclaw/ROUTER_SKILL_PROMPT.md`。
请把这个 prompt 部署到 OpenClaw runtime 作为 Router Skill 的 system prompt 或行为定义。

### B. trust-first 渲染
用户问 "Is this an app?" / "How do I know this is secure?" / "How much?" / "What's the first step?" 时：
- 给 2-3 句短答（不要大段说明书）
- 附一个 starter task（发照片 或 说 'daily insight'）
- 不要像销售话术
具体模板见 ROUTER_SKILL_PROMPT.md Rules 2-4。

### C. delivered 后 revision session continuity
视频交付后，用户发的自由文本（"make it more professional"、"shorter"、"change music"）必须走 revision：
- 绑定最近的 `job_id`
- 调用 `POST /webhook/feedback`
- 不要把 "professional" 当成全局 style selection
- 不要跳回 welcome
具体规则见 ROUTER_SKILL_PROMPT.md Rule 7。

### D. daily insight follow-up 对齐
daily_insight callback 送达后，只展示这 4 个 follow-up：
1. publish
2. skip
3. shorter
4. more professional
不要展示其他按钮或命令。具体见 ROUTER_SKILL_PROMPT.md Rule 8。

### E. callback 渲染前校验
收到 `daily_insight` callback 时，必须先校验三个字段：
- `insight.headline` 非空
- `insight.caption` 非空
- `image_urls` 至少一个
缺任何一个都不发给用户，走内部告警。
完整校验规则见 `doc/openclaw/CALLBACK_RENDERING.md`。

### F. insight-to-video handoff
用户 publish 了 daily insight 后，追加一句：
"Nice! By the way — whenever you have a listing, just send 6-10 photos and I'll make a video too."
每个 session 只说一次。

### G. starter-task / interview-first runtime
对犹豫型用户，先走 starter task，不默认推 onboarding form。
form 是 optional accelerator，不是前置门槛。
首次成功交付后才可以建议填表。

### H. ops context 回流
OpenClaw 在 session 中记录的状态（current_lane, last_successful_path, starter_task_completed 等），
写回到 `reel-agent-bridge-state.json` 的 `sessionContext` 字段。
完整 schema 见 `doc/openclaw/OPS_CONTEXT_SPEC.md`。

## 关键文件（在 Reel Agent 仓库里，需要先读）

**必读（按顺序）：**
1. `doc/openclaw/ROUTER_SKILL_PROMPT.md` — 完整 Router Skill system prompt（核心）
2. `doc/openclaw/CALLBACK_RENDERING.md` — 10 种 callback 的渲染规范
3. `doc/openclaw/OPS_CONTEXT_SPEC.md` — session context 回流规范
4. `doc/openclaw/AGENTS.md` — 生产边界 + 回调契约
5. `doc/openclaw/SKILL.md` — 5 个 Skill 的 curl 示例

**参考（需要时读）：**
- `doc/openclaw/REAL_INTEGRATION.md` — 真实联调 curl 脚本
- `doc/openclaw/TELEGRAM_WALKTHROUGH.md` — 端到端验收清单 (T1-T8)
- `SOUL.md` — Agent 人格定义
- `DECISIONS.md` — D9 等架构决策

## bridge 接线目标

- bridge route: `POST http://127.0.0.1:18789/reel-agent/events`
- bridge auth: `X-Reel-Secret: $OPENCLAW_CALLBACK_SECRET`
- bridge state: `~/.openclaw/workspace-realtor-social/.openclaw/reel-agent-bridge-state.json`

## 验收标准（Go/No-Go）

全部满足才能通知人工进 Telegram 体验：

- [ ] G1 Router Skill 直接调生产 API，不走 /api/message
- [ ] G2 能用 Bearer token 调通 /webhook/in 和 /webhook/feedback
- [ ] G3 bridge route 能接收 callback
- [ ] G4 progress/delivered/failed/daily_insight 能渲染到 Telegram
- [ ] G5 last_job_id 能持久化，revision 能绑定正确的 job
- [x] G6 后端 API 全部就绪（已验证）

## Telegram 演示顺序（验收时逐一跑通）

T1. help → 首触达
T2. property content → 等待发图
T3. listing photos → 触发生成
T4. progress → 进度消息渲染
T5. delivered → 视频交付渲染
T6. revision → "make the music more upbeat"
T7. daily insight → 资讯交付 + follow-up
T8. daily push control → stop push / resume push

## 环境变量

确保这些都设好：
REEL_AGENT_URL=http://127.0.0.1:8000   # 或后端部署地址
REEL_AGENT_TOKEN=（共享 bearer token）
OPENCLAW_CALLBACK_BASE_URL=http://127.0.0.1:18789/reel-agent
OPENCLAW_CALLBACK_SECRET=（共享回调密钥）

## 执行顺序建议

1. 先读 ROUTER_SKILL_PROMPT.md，理解完整决策树
2. 实现 bridge route（接收 callback）
3. 部署 Router Skill（意图识别 + API 调度）
4. 实现 session state 持久化（last_job_id, last_daily_insight, lane）
5. 实现 callback 渲染（progress → delivered → daily_insight → failed）
6. 逐一跑通 T1-T8
7. 回写 bridge-state.json 的 sessionContext

每完成一步就用对应的 curl 命令验证。curl 示例在 REAL_INTEGRATION.md 里。
```
