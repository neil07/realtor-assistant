# STATUS — Reel Agent

> 最后更新：2026-04-02

## Active Theme

alpha 阶段——Reel Agent 2.0 demo-ready dual-closure / OpenClaw 消息主链路收口

## Doing

- 当前活跃任务：`Reel Agent 2.0 / demo-ready dual-closure`
- 当前阶段：`USER_WALKTHROUGH_READY`
- 当前焦点：准备 owner Telegram walkthrough；文本主链路、daily push control、listing-photo handoff 已具备运行时证据，等待明天按真实手机路径顺序体验

## Done Recently

- **运营控制台 `console/`** — 仪表板 + onboarding flow + H5 入驻表单 + 客户详情 + Skill Brief 在线编辑（/console 路由族）
- **每日资讯管线** — `DailyScheduler`（UTC 13:00 触发）+ `generate_daily_insight.py` + `render_insight_image.py` + `market_data_fetcher.py` + `redfin_data_fetcher.py`；对所有 daily_push_enabled 经纪人按市场区域推送品牌图卡
- **`/api/message` 意图分类路由** — 10 种 intent 分类（listing_video / daily_insight / style_selection / confirm / stop_push / resume_push / publish / revision / redo / off_topic）；text-command 兜底保证无按钮渠道体验一致
- **后台守护任务** — `_job_watchdog_loop`（每 60s 检测 stall job）+ `_callback_retry_loop`（每 30s 刷新失败回调队列）
- **OpenClaw bridge state 读取** — `_read_bridge_agent_state()` + `_infer_post_render_context()`，支持跨视频/资讯的交付上下文判断
- Motion metrics（OpenCV Farneback 光流）集成到 review_video.py — commit 556f49b
- 5 个 per-step quality gates 加入 dispatcher.py（critical=中止, warning=继续）
- Prompt 质量优化：video_planner 重写（6 段叙事弧 + Hook-First）、video_prompt_writer 重写（运镜指令 + hallucination 风险分级）
- 编排层完成：job_manager（SQLite 状态机）+ dispatcher（asyncio 并行调度）+ progress_notifier + callback_client
- server.py 全端点实现（/api/generate, /api/status, /webhook/feedback, /webhook/manual-override, /api/daily-trigger）
- 10 个 pipeline 脚本 + pipeline.py CLI 端到端
- Agent 人格 + 行为 spec（SOUL / AGENTS / SKILL）
- 4 个 prompt 模板，3 个风格模板
- 端到端真实图验证跑通：job `1774874734_09f47354` 成功交付 `Gym_Amenity_Test_4_9x16.mp4`（4.5s / has_audio=true）
- `/api/message` 已收敛为消息统一入口，补齐 help / daily insight / property content 路由修正
- 修复新用户被过早打回 welcome 的高置信路由 bug
- OpenClaw-facing 接口已补 Bearer token 鉴权：`/api/message`、`/webhook/in`、`/webhook/feedback`、`/api/daily-trigger`
- 已补 mock 联调与路由回归测试：`tests/test_message_routing.py`、`tests/test_openclaw_mock_integration.py`
- 已沉淀联调文档：`doc/openclaw/MOCK_INTEGRATION.md`、`doc/openclaw/REAL_INTEGRATION.md`
- 已落地 OpenClaw-side deterministic callback bridge，并把 `last_job_id` 镜像到结构化 state 文件
- 已将 OpenClaw 接线层 GitHub 化：repo 现在持有 `openclaw/extensions/reel-agent-bridge` 源码与 `scripts/openclaw/install-local-wiring.sh`
- callback bridge 已完成 smoke test 与隔离验证：错误 secret → `401`，未知 event type → `400`
- 最新修复 `ceefc62`：补 daily insight post-render 上下文识别，`publish / skip` 可基于 bridge state 正确命中；同时新增 `/health` 活性探针与对应测试
- 最新修复：`/api/daily-trigger` 的 `Scheduler not ready` 503 已修复（`lifespan` 正确挂全局 `_scheduler`）
- OpenClaw Router 文本主链路已拿到 live 证据：`help`、`daily insight`、`property content`
- `listing photos -> style -> go -> /webhook/in` 已通过 deterministic plugin harness 验证
- `stop push / resume push -> /webhook/in params.action` 已通过 deterministic plugin harness 验证

## Blocked

- **剩余风险是"首轮真人 Telegram walkthrough 还没跑"** —— 生产路由与 bridge 已基本就绪，但 `listing photos` 入口目前只有 runtime harness 证据，明天第一轮 owner 实测应优先验证这一刀

## Next Actions

1. 明天 owner 在 Telegram 依次走：`help` → `property content` → 发房源图 → `daily insight` → `stop push / resume push`
2. 体验时重点观察 4 件事：是否正确起 lane、是否保存 `last_job_id`、是否能接回 callback、是否正确渲染 delivered / daily insight
3. 若第一轮真人 walkthrough 无阻塞问题，则进入更广的 owner usage；若有问题，优先回收 runtime/plugin 证据，不先扩写文档
