# CLAUDE.md — Reel Agent

## 产品定位

OpenClaw WhatsApp bot，房产经纪人发 listing 照片，自动生成社媒营销短视频。
参考体验：Listing Videos AI。单一用途，不做其他事。

## 三层架构

```
对外层（唯一入口）  →  WhatsApp → OpenClaw Agent
编排层（异步调度）  →  orchestrator/ + agent/ + db/
能力层（5 个 Skill）→  skills/listing-video/scripts/
模型适配层（引擎）  →  Claude / IMA Studio (Kling/WAN/TTS) + fallback 链
```

### 编排层组件

| 文件                                | 职责                                        |
| ----------------------------------- | ------------------------------------------- |
| `orchestrator/job_manager.py`       | SQLite 状态机，job CRUD，断点续跑           |
| `orchestrator/dispatcher.py`        | asyncio 异步调度，Step2/Step4 并行          |
| `orchestrator/retry_handler.py`     | 重试策略 + fallback 决策                    |
| `orchestrator/progress_notifier.py` | 向 OpenClaw 推送进度/完成/失败              |
| `agent/webhook_router.py`           | 接收 OpenClaw 入站 webhook                  |
| `agent/callback_client.py`          | 向 OpenClaw 发出站回调（httpx）             |
| `db/jobs.db`                        | SQLite 数据库（运行时自动创建，.gitignore） |

### 五个 Skill（KPI 驱动，非 SOP）

| Skill    | KPI                         | 脚本                                                                                  |
| -------- | --------------------------- | ------------------------------------------------------------------------------------- |
| 需求深挖 | 挖出完整可执行的视频需求    | `analyze_photos.py`, `profile_manager.py`                                             |
| 剧本     | 产出打动人的叙事 + 配音文案 | `plan_scenes.py`, `generate_script.py`                                                |
| 分镜     | 每个镜头有精准视觉指令      | `write_video_prompts.py`                                                              |
| 生成     | 输出经纪人愿意直接发的成品  | `render_ai_video.py`, `generate_voice.py`, `assemble_final.py`, `render_slideshow.py` |
| 复盘     | 每轮反馈让下次更准          | `job_logger.py` + 收敛逻辑（待建）                                                    |

### 模型适配原则

同一个 Skill，不同模型不同写法：

- **强推理模型**（Opus）→ 只给目标，让它自己决定方法
- **中等模型**（Sonnet）→ 给关键步骤 + 约束（当前 prompt 级别）
- **弱模型**（Flash/Haiku）→ 给详细 SOP + 示例

换模型只改适配层，不动 Skill 定义。

## 架构硬约束

### 状态机（不可跳步）

```
QUEUED → ANALYZING → SCRIPTING → PROMPTING → PRODUCING → ASSEMBLING → DELIVERED
                                                                       ↓
                                                               FAILED | CANCELLED
```

### 脚本双模运行

每个 Python 脚本必须支持两种调用方式：

1. `build_*_request()` → 返回请求对象，给 OpenClaw 调度
2. `run()` → 独立执行，直接调用 API，用于本地测试

### AI 视频红线

- 禁止添加照片中没有的物体（家具、人、车、宠物）
- 禁止改变天气、季节、时间
- 禁止虚拟 staging
- 禁止修改房屋结构或外观
- 只允许：运镜、光影微变、自然摆动、景深变化

### 密钥安全

- `.env` 存真实密钥（已在 .gitignore）
- `.env.example` 只放占位符
- 提交前检查：无 UUID 格式 key、无 `eyJ` JWT、无 `sk-` 前缀

### 视频质量问题诊断规则（Diagnostics-First）

发现视频质量问题时，**禁止直接翻日志**。先读诊断接口，逐层排查。

#### 入口

```
GET /api/status/{job_id}
```

读返回里的 `diagnostics`（自动归因）和 `review`（质量评审）。没有 diagnostics 时，从 output 目录的文件和 run.jsonl 推断。

#### 五层诊断（由浅入深，L1 没问题才看 L2）

---

**L1 — 服务故障：东西坏了吗？**

典型现象：视频完全没声音、某个镜头黑屏/缺失、配音中间断掉、节奏忽快忽慢

| 看什么                    | 怎么判断                                                                                         |
| ------------------------- | ------------------------------------------------------------------------------------------------ |
| 整条视频有没有声音        | `final_has_audio = false` → 全片静音，最高优先级                                                 |
| 有没有镜头渲染失败        | `render_fallback_scenes` 有值 → 降级成了幻灯片式运镜；`render_failed_scenes` 有值 → 镜头直接丢了 |
| 配音有没有生成            | `tts_failed_scenes` 有值 → 那些镜头没配音；`tts_fallback_scenes` 有值 → 换了备用语音引擎         |
| 镜头有没有被强行拉伸/截断 | `assembly_adjusted_scenes` 有值 → 画面和配音时长对不上，被强行调了                               |
| 产出文件齐不齐            | clips/ 或 voice/ 里的文件数跟场景数对不上 → 有东西没生成出来                                     |

> **L1 有问题** → 这是 bug，需要修代码或重跑受影响的步骤。
> （技术参考：查 `diagnostics.json` 里对应 scene 的 `render.attempts[]` / `tts.attempts[]`，看 `error_type`）

---

**L2 — AI 出品质量：模型干活干得怎么样？**

典型现象：画面像 PPT 慢慢推（运镜幅度极小）、画面有畸变/变形、配音念错地名、语速不自然

| 看什么   | 怎么判断                                                          |
| -------- | ----------------------------------------------------------------- |
| 运镜效果 | 打开 clips/ 里的单个镜头视频看——运镜几乎感觉不到 = 模型输出质量差 |
| 画面质量 | 有没有桶形畸变、色彩突变、物体变形                                |
| 配音质量 | 听 voice/ 里的单个音频——地名念错、语速诡异、情绪跟风格不搭        |
| 时长偏差 | 要求 5 秒但出了 8 秒 = 模型没按指令来（偏差 >20% 算异常）         |

> **L2 有问题** → 需要换模型或调模型参数。
> （技术参考：`diagnostics.json` 每个 scene 的 `render.model` / `tts.model`；`render.probe.duration` vs `render.requested_duration`）

---

**L3 — 创意指令：给 AI 的"剧本"写对了吗？**

典型现象：开头没有 hook、文案太长/太短、所有镜头运镜方式都一样、配音内容跟画面无关

| 看什么   | 怎么判断                                                                                       |
| -------- | ---------------------------------------------------------------------------------------------- |
| 照片理解 | `analysis.json` — 房间类型有没有判断错？核心卖点有没有漏？好照片有没有被误判为"不适合做视频"？ |
| 场景规划 | `scenes.json` — 叙事有没有 hook → 主体 → 收尾 的弧线？还是平铺直叙？                           |
| 配音文案 | `script.json` — 字数合不合适（目标 80-120 词/30 秒）？开头 hook 够不够抓人？有没有 cliche？    |
| 运镜指令 | `prompts.json` — 每个镜头的运镜写得够不够具体？6 个镜头是不是都写了 "slow pan"？               |
| 安全护栏 | `prompts.json` — 有没有加"禁止添加不存在的物体"的约束？没加 → AI 可能会幻觉出家具/人           |

> **L3 有问题** → 需要改 prompt 模板（`prompts/` 或 `refer/` 目录），改完从对应步骤重跑。

---

**L4 — 流程编排：pipeline 的安排合理吗？**

典型现象：5 张照片做出了 6 个镜头（重复）、总时长 41 秒（太长）、泳池出现两次、结尾没有 CTA

| 看什么               | 怎么判断                                                                 |
| -------------------- | ------------------------------------------------------------------------ |
| 镜头数 vs 照片数     | 镜头数 > 照片数 → 同一张照片被拆成了多个镜头                             |
| 总时长               | 超过 30 秒 → 超出 Reels 完播率甜区；单镜头超过 6 秒 → 拖沓               |
| 画面和配音的时长匹配 | 偏差太大 → 画面被强行拉伸/循环/截断，节奏会很怪                          |
| 叙事结构             | hook 有没有放在第一个镜头？最后有没有收尾（CTA）？有没有镜头完全没配音？ |
| 风格一致性           | 选了 "professional" 但配了欢快 BGM？色调指导有没有执行？                 |

> **L4 有问题** → 需要改场景规划或调度逻辑（`plan_scenes.py` / `dispatcher.py`）。

---

**L5 — 原始素材：经纪人给的照片够好吗？**

典型现象：照片太暗/太糊、5 张都是同个角度、缺少室内/外观/设施等关键区域

| 看什么     | 怎么判断                                                        |
| ---------- | --------------------------------------------------------------- |
| 照片质量   | `analysis.json` 里的质量评分——低于 6 分的照片会拉低整体视频质量 |
| 照片多样性 | 全是同一种类型（比如 5 张都是外观）→ 视频内容会很单调           |
| 背景音乐   | `bgm.mp3` 存不存在？不存在 → 音乐生成也失败了                   |

> **L5 有问题** → 建议经纪人补充照片（不同角度、不同区域），或在分析阶段自动过滤低质照片。

---

#### 诊断结论（每次必须回答这 5 条）

1. **主要原因** — 一句话说清楚，属于哪一层（可以多层叠加，比如"L1 配音全挂 + L4 镜头数太多"）
2. **哪几个镜头有问题** — 列出具体编号（scene_01, scene_03...）
3. **需不需要重新生成** — 是/否
4. **最小重做范围** — 从哪一步开始重跑、哪些镜头要重做
5. **下一步行动** — 是修代码、改 prompt、换模型，还是让经纪人补照片

#### 代码层硬性要求

- 每个 job 必须自动生成 `diagnostics.json`（由 `video_diagnostics.py` 写入）
- pipeline 结束前必须检查最终视频有没有音频轨
- 配音全部失败时，不能输出无声视频——至少加上背景音乐兜底
- 日志里记录的配音数量必须跟实际生成的音频文件数一致（防止"假成功"）
- pipeline 每步必须把中间产物落盘到 output 目录：`analysis.json`、`scenes.json`、`script.json`、`prompts.json`（没有这些文件，L3 创意指令层无法诊断）
- 诊断时**严格逐层**：L1 没问题才看 L2，避免误判

## 代码规范

- Python 3.11+
- 格式化：Ruff（`ruff format`）
- Lint：Ruff（`ruff check`）
- 类型注解：函数签名必须有，内部变量按需
- 文档字符串：公开函数用 Google style
- 命名：snake_case（函数/变量），PascalCase（类）

## 文件结构

```
video-mvp1.0/
├── CLAUDE.md              # 本文件（项目宪法）
├── SOUL.md                # Agent 人格定义
├── AGENTS.md              # Agent 行为规则
├── server.py              # FastAPI 入口，lifespan 启动编排层
├── requirements.txt
├── .env                   # 真实密钥（.gitignore）
├── .env.example           # 占位符模板
├── orchestrator/          # 编排层
│   ├── job_manager.py     # SQLite 状态机
│   ├── dispatcher.py      # asyncio 异步调度
│   ├── retry_handler.py   # 重试 + fallback
│   └── progress_notifier.py  # 向 OpenClaw 推送进度
├── agent/                 # 对外接口层
│   ├── webhook_router.py  # 接收入站 webhook
│   └── callback_client.py # 发出站回调
├── db/                    # SQLite 数据库（.gitignore）
│   └── jobs.db            # 运行时自动创建
└── skills/
    └── listing-video/
        ├── SKILL.md        # Skill 完整定义
        ├── scripts/        # pipeline 脚本（含 pipeline.py）
        ├── prompts/        # 4 个 prompt 模板
        ├── templates/      # 3 个风格模板 (energetic/elegant/professional)
        ├── profiles/       # 用户画像 JSON
        ├── assets/         # 音乐、字体、叠加层
        └── output/         # 视频产出（.gitignore）
```

## 当前进度

### P1/P2 已完成（2026-03）

- Agent 人格 + 行为 spec（SOUL/AGENTS/IDENTITY/SKILL）
- 4 个 prompt 模板，3 个风格模板
- 10 个 pipeline 脚本 + pipeline.py 端到端 orchestrator
- `job_logger.py` 重构为 per-job `JobLogger` 类（并发安全）
- `orchestrator/job_manager.py` — SQLite 状态机 + CRUD
- `orchestrator/dispatcher.py` — asyncio 异步调度，Step2/Step4 并行
- `orchestrator/progress_notifier.py` — OpenClaw 进度推送
- `agent/callback_client.py` — httpx 出站回调
- `server.py` 改造 — lifespan 启动恢复 + webhook_router + `/api/generate` 非阻塞

### Prompt 质量优化已完成（2026-03）

- `refer/video_planner` — 重写：6 段叙事弧、Hook-First 模式、anti-cliché 禁用词表、scene_desc 格式规范
- `refer/video_prompt_writer` — 重写：运镜指令格式、单轴运动优先、negative prompt 后缀（no added objects/people/staging）、hallucination 风险分级
- `dispatcher.py` — `_distribute_script_to_scenes()`：generate_script 的 hook/walkthrough/closer 分配到各场景 text_narration，取代 video_planner 的泛化 narration
- `dispatcher.py` — step 3 后回写 scenes，motion_prompt 持久化到 DB

### P4 待做（SDK 改造）

- [ ] `analyze_photos.py` — Files API 上传，`file_ids` 跨步传递
- [ ] `generate_script.py` — Structured Outputs（Pydantic `ScriptOutput`）
- [ ] `plan_scenes.py` — prompt caching（`cache_control: ephemeral`）
- [ ] `write_video_prompts.py` — `run_batch_async()` asyncio.gather 并发
- [ ] Kling 模型分级：室内用 Kling 2.6，first/last frame 过渡用 Kling O1（需 IMA Studio API 支持 per-clip model_id）

### P5/P6 待做

- [ ] `agent/webhook_router.py` 完整实现（OpenClaw 入站）
- [ ] `/webhook/manual-override` 人工接管端点
- [ ] API 集成测试（IMA Studio 视频 + TTS）
- [ ] BGM 素材 + 字体资源
- [ ] 端到端测试（真实房源照片跑通）
