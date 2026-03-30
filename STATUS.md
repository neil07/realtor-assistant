# STATUS — Reel Agent

> 最后更新：2026-03-30

## Active Theme

alpha 阶段——视频质量打磨 + 偏好记忆 + 零摩擦入口

## Doing

（无活跃任务）

## Done Recently

- Motion metrics（OpenCV Farneback 光流）集成到 review_video.py — commit 556f49b
- 5 个 per-step quality gates 加入 dispatcher.py（critical=中止, warning=继续）
- Prompt 质量优化：video_planner 重写（6 段叙事弧 + Hook-First）、video_prompt_writer 重写（运镜指令 + hallucination 风险分级）
- 编排层完成：job_manager（SQLite 状态机）+ dispatcher（asyncio 并行调度）+ progress_notifier + callback_client
- server.py 全端点实现（/api/generate, /api/status, /webhook/feedback, /webhook/manual-override, /api/daily-trigger）
- 10 个 pipeline 脚本 + pipeline.py CLI 端到端
- Agent 人格 + 行为 spec（SOUL / AGENTS / SKILL）
- 4 个 prompt 模板，3 个风格模板
- macOS 部署打通：真实仓 `/Users/lsy/projects/realtor-social` 已完成依赖安装、`.env` 配置、服务常驻启动
- 端到端真实图验证跑通：job `1774874734_09f47354` 成功交付 `Gym_Amenity_Test_4_9x16.mp4`（4.5s / has_audio=true）
- 装配层修复：单镜头 concat 临时文件双删 bug 修复；per-scene narration duration 读取改为 mutagen 优先，避免 `ffprobe` 缺失导致 0.0s

## Blocked

- **IMA Studio per-clip model_id** — API 暂不支持按镜头指定模型 → Kling 分级（室内 2.6 / 过渡 O1）无法实现
- **webhook_router.py** — 待 OpenClaw 入站 webhook 规格确认后才能完整实现

## Next Actions

1. **P4: SDK 改造**
   - analyze_photos.py → Files API 上传
   - generate_script.py → Structured Outputs（Pydantic）
   - plan_scenes.py → prompt caching（cache_control: ephemeral）
   - write_video_prompts.py → asyncio.gather 并发
2. **P5: 集成**
   - webhook_router.py 完整实现
   - API 集成测试（IMA Studio 视频 + TTS 真实调用，覆盖多图 / 多镜头 / CTA / BGM）
   - BGM 素材 + 字体资源
3. **P6: 端到端验证**
   - 用真实房源多图继续回归，重点看最终音频稳定性、scene clip 音轨一致性、review 输出完整性
