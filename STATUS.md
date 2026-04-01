# STATUS — Reel Agent

> 最后更新：2026-04-02

## Active Theme

alpha 阶段——Reel Agent 2.0 demo-ready dual-closure / OpenClaw 消息主链路收口

## Doing

- 当前活跃任务：`Reel Agent 2.0 / demo-ready dual-closure`
- 当前阶段：`USER_WALKTHROUGH_READY`
- 当前焦点：准备 owner Telegram walkthrough；文本主链路、daily push control、listing-photo handoff 已具备运行时证据，等待明天按真实手机路径顺序体验

## Done Recently

- `/api/message` 已收敛为消息统一入口，补齐 help / daily insight / property content 路由修正
- 修复新用户被过早打回 welcome 的高置信路由 bug
- OpenClaw-facing 接口已补 Bearer token 鉴权：`/api/message`、`/webhook/in`、`/webhook/feedback`、`/api/daily-trigger`
- 已补 mock 联调与路由回归测试：`tests/test_message_routing.py`、`tests/test_openclaw_mock_integration.py`
- 已沉淀联调文档：`doc/openclaw/MOCK_INTEGRATION.md`、`doc/openclaw/REAL_INTEGRATION.md`
- 已落地 OpenClaw-side deterministic callback bridge，并把 `last_job_id` 镜像到结构化 state 文件
- callback bridge 已完成 smoke test 与隔离验证：错误 secret → `401`，未知 event type → `400`
- 最新修复 `ceefc62`：补 daily insight post-render 上下文识别，`publish / skip` 可基于 bridge state 正确命中；同时新增 `/health` 活性探针与对应测试
- 最新修复：`/api/daily-trigger` 的 `Scheduler not ready` 503 已修复（`lifespan` 正确挂全局 `_scheduler`）
- OpenClaw Router 文本主链路已拿到 live 证据：`help`、`daily insight`、`property content`
- `listing photos -> style -> go -> /webhook/in` 已通过 deterministic plugin harness 验证
- `stop push / resume push -> /webhook/in params.action` 已通过 deterministic plugin harness 验证

## Blocked

- **剩余风险是“首轮真人 Telegram walkthrough 还没跑”** —— 生产路由与 bridge 已基本就绪，但 `listing photos` 入口目前只有 runtime harness 证据，明天第一轮 owner 实测应优先验证这一刀

## Next Actions

1. 明天 owner 在 Telegram 依次走：`help` → `property content` → 发房源图 → `daily insight` → `stop push / resume push`
2. 体验时重点观察 4 件事：是否正确起 lane、是否保存 `last_job_id`、是否能接回 callback、是否正确渲染 delivered / daily insight
3. 若第一轮真人 walkthrough 无阻塞问题，则进入更广的 owner usage；若有问题，优先回收 runtime/plugin 证据，不先扩写文档
