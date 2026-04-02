# Video Quality Assurance Architecture

> 视频质量保障模块的完整业务流程、组件职责、数据流和决策逻辑。
> 最后更新：2026-04-02

---

## 设计目标

AI 视频生成质量天然不稳定。本模块的目标：

1. **100% 有产出** — 降级也要交付（Ken Burns fallback），绝不让用户等了几分钟后什么都没拿到
2. **精准修复** — 哪个镜头差就重做哪个，不浪费钱全量重跑
3. **零额外成本** — 质量检测全部本地运行（OpenCV + numpy），不调用任何 API
4. **静音即故障** — 完全无声的视频绝不发给用户

---

## 业务流程图

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Pipeline 主流程                               │
│                                                                     │
│  照片分析 → 场景规划 → 剧本生成 → 运镜 Prompt → 渲染 + 配音 → 拼接  │
└─────────────────────────────────┬───────────────────────────────────┘
                                  │
                    ┌─────────────▼──────────────┐
                    │                            │
          ┌────────▼────────┐          ┌────────▼────────┐
          │   渲染每个 Clip   │          │  配音每个场景    │
          │  (IMA Studio)    │          │  (TTS 引擎)     │
          └────────┬────────┘          └────────┬────────┘
                   │                            │
          ┌────────▼────────┐          ┌────────▼────────┐
          │  L1 Per-Clip     │          │  L2 TTS          │
          │  Quality Gate    │          │  Fallback Chain   │
          │  ─────────────   │          │  ───────────────  │
          │  3 维检测:       │          │  ElevenLabs       │
          │  · 运镜幅度 dd   │          │    ↓ 失败         │
          │  · 平滑度 ms     │          │  OpenAI TTS       │
          │  · 闪烁度 tf     │          │    ↓ 失败         │
          └────────┬────────┘          │  IMA Studio TTS   │
                   │                   └────────┬────────┘
          ┌────────▼────────┐                   │
          │  通过?           │                   │
          │                  │                   │
          │  YES → 继续      │                   │
          │                  │                   │
          │  NO → 重渲染 1 次 │                   │
          │    ↓             │                   │
          │  v1 vs v2 取好的  │                   │
          │    ↓             │                   │
          │  仍极差?          │                   │
          │  YES → Ken Burns │                   │
          │  NO  → 继续      │                   │
          └────────┬────────┘                   │
                   │                            │
                   └──────────┬─────────────────┘
                              │
                    ┌─────────▼──────────┐
                    │  L3 Assembly        │
                    │  ──────────────     │
                    │  FFmpeg 拼接        │
                    │  时长不匹配时:      │
                    │  · stretch (拉伸)   │
                    │  · loop (循环)      │
                    │  · trim (裁剪)      │
                    │  记录到 diagnostics │
                    └─────────┬──────────┘
                              │
                    ┌─────────▼──────────┐
                    │  L4 Structural Gate │
                    │  ──────────────     │
                    │  ✓ 文件存在?        │  ← critical
                    │  ✓ 文件非空?        │  ← critical
                    │  ✓ 有音频轨?        │  ← critical (静音=故障)
                    │  ✓ 字幕叠加?        │  ← warning
                    └─────────┬──────────┘
                              │
                    ┌─────────▼──────────┐
                    │  L5 Claude Vision   │
                    │  Review             │
                    │  ──────────────     │
                    │  输入:              │
                    │  · 6 帧截图         │
                    │  · metadata         │
                    │  · motion 上下文    │  ← L1 数据流入
                    │                     │
                    │  输出:              │
                    │  · 11 维评分        │
                    │  · overall_score    │
                    │  · motion penalty   │  ← 量化指标影响评分
                    │  · deliverable      │
                    └─────────┬──────────┘
                              │
                    ┌─────────▼──────────┐
                    │  score < 4.0?       │
                    │                     │
                    │  NO → 交付给用户    │
                    │                     │
                    │  YES → Auto-Retry   │
                    │  (全量重跑 1 次)    │
                    │    ↓                │
                    │  v1 vs v2 取好的    │
                    │    ↓                │
                    │  仍 < 4.0?          │
                    │  YES → 拦截,通知    │
                    │  NO  → 交付给用户   │
                    └─────────────────────┘
```

---

## 5 层质量检查详解

### L1: Per-Clip Motion Gate

> **位置：** `render_ai_video.py` 的 `_generate_one()` 内部
> **时机：** 每个 clip 渲染完成后立即执行
> **成本：** $0（本地 OpenCV Farneback 光流 + SSIM）
> **延迟：** < 1 秒/clip

#### 三维检测

| 维度       | 指标                  | 算法                       | 阈值          | 含义                 |
| ---------- | --------------------- | -------------------------- | ------------- | -------------------- |
| 运镜幅度   | `dynamic_degree`      | Farneback 光流 top-5% 幅度 | < 0.10 → 重做 | 太低 = PPT 幻灯片感  |
| 运动平滑度 | `motion_smoothness`   | 光流帧间变化量             | < 0.35 → 重做 | 太低 = 画面抖动畸变  |
| 时间闪烁   | `temporal_flickering` | 帧间 SSIM 均值反转         | > 0.15 → 重做 | 太高 = 亮度/颜色突变 |

这 3 个维度覆盖了 VBench（CVPR 2024）评估 AI 视频质量的前 3 高频故障模式。

#### 决策逻辑

```
检测 3 维指标
  ↓
全通过 → 接受 clip
  ↓
任一不通过 → 用相同 prompt 重渲染到 _qg.mp4
  ↓
v1 vs v2 比较 dynamic_degree，取较好版
  ↓
最好版 dd < 0.05（hopeless） → 标记 quality_fallback → Ken Burns slideshow
```

#### 关键阈值

| 常量                     | 值   | 用途                          |
| ------------------------ | ---- | ----------------------------- |
| `_CLIP_MIN_DYNAMIC`      | 0.10 | 低于此值触发重渲染            |
| `_CLIP_MIN_SMOOTHNESS`   | 0.35 | 低于此值触发重渲染            |
| `_CLIP_MAX_FLICKERING`   | 0.15 | 高于此值触发重渲染            |
| `_CLIP_HOPELESS_DYNAMIC` | 0.05 | 低于此值放弃 AI，走 Ken Burns |

### L2: TTS Fallback Chain

> **位置：** `generate_voice.py`
> **时机：** 每个场景配音生成时
> **成本：** 主引擎 $0.01-0.03/场景

#### 三级降级

```
ElevenLabs (主引擎, 质量最高)
  ↓ 失败
OpenAI TTS (备选 1, 稳定性好)
  ↓ 失败
IMA Studio TTS (备选 2, 任务队列式)
  ↓ 全部失败
该场景无配音，assembly 时用 BGM 兜底
```

每次尝试都记录到 `diagnostics.json` → `tts.attempts[]`，包含 engine、status、error_type。

### L3: Assembly Adjustment

> **位置：** `assemble_final.py`
> **时机：** FFmpeg 拼接视频 + 音频时
> **成本：** $0

当 clip 时长和配音时长不匹配时，自动调整：

| 调整方式  | 触发条件          | 效果                     |
| --------- | ----------------- | ------------------------ |
| `stretch` | clip 比配音短     | 拉伸视频，可能有慢动作感 |
| `loop`    | clip 比配音短很多 | 循环播放视频             |
| `trim`    | clip 比配音长     | 截断多余视频             |

调整方式和比例记录到 `diagnostics.json` → `assembly.adjustment`。

### L4: Structural Gates

> **位置：** `dispatcher.py` 的 `_check_quality_gate()`
> **时机：** 每个 pipeline 步骤完成后
> **成本：** $0

这是**结构完整性检查**，不是质量评估。确保 pipeline 每步的产出存在且可用。

#### after_assemble gate（最关键）

| 检查项           | 级别         | 说明                      |
| ---------------- | ------------ | ------------------------- |
| 最终视频文件存在 | **critical** | 不存在则 pipeline 失败    |
| 最终视频文件非空 | **critical** | 0 字节则 pipeline 失败    |
| 最终视频有音频轨 | **critical** | 静音视频 = 故障，不可发布 |
| 字幕叠加成功     | warning      | 叠加失败只告警，不阻断    |

### L5: Claude Vision Review + Auto-Retry + Delivery Block

> **位置：** `review_video.py`（评审）+ `dispatcher.py`（决策）
> **时机：** 整条视频拼接完成后
> **成本：** ~$0.03-0.05/次（Claude Sonnet Vision 调用）

#### 评审流程

```
提取 6 帧关键画面
  ↓
本地计算 motion_metrics（整条视频，非单 clip）
  ↓
构建 prompt：metadata + motion 上下文 + 6 帧图片 + 评分指令
  ↓
Claude Sonnet Vision 打分（11 个维度 + overall_score）
  ↓
Motion penalty 调整 overall_score
  ↓
输出 auto_review.json
```

#### 双视角 11 维评分

**买家视角（Real Estate Buyer）：**

| 维度                  | 含义                                   |
| --------------------- | -------------------------------------- |
| `hook`                | 前 3 秒能不能让人停下滑动              |
| `immersion`           | 像在实地看房还是在看 PPT               |
| `decision_efficiency` | 30 秒内能看到地址/价格/联系方式吗      |
| `professionalism`     | 质感是否匹配专业经纪人形象             |
| `authenticity`        | 有没有 AI 幻觉（凭空出现的家具/人/车） |

**创作者视角（Short Video Creator）：**

| 维度                | 含义                                   |
| ------------------- | -------------------------------------- |
| `pacing`            | 节奏：2-4 秒/镜头最佳，>6 秒拖沓       |
| `narrative_arc`     | Hook → Reveal → Climax → CTA 叙事弧    |
| `ai_quality`        | 画面清晰度、运镜流畅度、无畸变         |
| `audio_visual_sync` | 画面和配音节奏是否匹配                 |
| `text_overlays`     | 字幕排版、地址/价格/CTA 是否可见       |
| `platform_fit`      | 9:16 构图利用率，是否适合 Reels/TikTok |

#### Motion Penalty（量化指标影响评分）

Claude 只看 6 帧截图，无法感知运镜/闪烁。因此 `motion_metrics` 检测到的问题会直接降分：

| 问题严重度 | 关键词                        | 惩罚     |
| ---------- | ----------------------------- | -------- |
| 严重       | slideshow, severe, jerky      | **-1.0** |
| 轻微       | low motion, rough, noticeable | **-0.5** |

公式：`final_score = max(0, claude_score - motion_penalty)`

#### 决策链

| 条件                                           | 动作                                         |
| ---------------------------------------------- | -------------------------------------------- |
| `overall_score >= 4.0` 且 `deliverable = true` | 交付给用户                                   |
| `overall_score < 4.0` 且未重试过               | Auto-Retry：全量重跑 render + TTS + assembly |
| 重试后 `overall_score >= 4.0`                  | 取 v1/v2 中较高分版本交付                    |
| 重试后仍 `< 4.0`                               | **Delivery Block**：拦截，通知用户质量不达标 |

#### 不可交付条件（任一触发）

- `has_audio = false`（无声视频）
- `duration > 35s`（超出完播率甜区）
- `hook < 4`（开头无法吸引注意力）
- `overall_score < 5`（综合质量过低）

---

## 数据流

```
motion_metrics.py                    video_diagnostics.py
  ├─ compute_motion_metrics()          ├─ record_render_diagnostics()
  │   返回: dd, ms, tf,               │   写入: diagnostics.json
  │   mean_flow, variance             │     每个 scene 的 attempts[]
  └─ interpret_motion()                │     每次 attempt 的 motion_metrics
      返回: labels + issues            └─ record_final_diagnostics()
        │                                  写入: final output probe
        │
        ├──→ render_ai_video.py          review_video.py
        │     _assess_clip_quality()       ├─ meta_block 含 motion 上下文
        │     _clip_needs_rerender()       ├─ Claude Vision 11 维评分
        │     ↳ 决定: 接受/重渲染/Ken Burns  ├─ motion penalty 降分
        │                                  └─ format_score_summary()
        │                                       显示 dd/ms/tf 3 维
        │
        └──→ diagnostics.json            auto_review.json
              per-clip metrics             overall_score (adjusted)
              per-clip attempts            deliverable
              assembly adjustments         top_issues (含 motion issues)
              final probe                  motion_metrics
```

**核心原则：一次计算，多处消费。**

- L1 的 per-clip metrics → 写入 `diagnostics.json`，驱动重渲染决策
- L5 的 whole-video metrics → 注入 Claude prompt，驱动 motion penalty
- 两者不同：per-clip 是单个原始 clip，whole-video 是拼接后的完整视频（含 stretch/loop/trim 效果）

---

## 阈值速查表

| 常量                       | 值   | 位置                     | 用途                             |
| -------------------------- | ---- | ------------------------ | -------------------------------- |
| `_CLIP_MIN_DYNAMIC`        | 0.10 | render_ai_video.py:21    | Per-clip: 运镜太弱 → 重渲染      |
| `_CLIP_MIN_SMOOTHNESS`     | 0.35 | render_ai_video.py:22    | Per-clip: 运动抖动 → 重渲染      |
| `_CLIP_MAX_FLICKERING`     | 0.15 | render_ai_video.py:23    | Per-clip: 画面闪烁 → 重渲染      |
| `_CLIP_HOPELESS_DYNAMIC`   | 0.05 | render_ai_video.py:24    | Per-clip: 绝望 → Ken Burns       |
| `AUTO_RETRY_THRESHOLD`     | 4.0  | dispatcher.py:36         | Whole-video: 低于此分 → 全量重跑 |
| `DELIVERY_BLOCK_THRESHOLD` | 4.0  | dispatcher.py:39         | Whole-video: 重跑后仍低于 → 拦截 |
| `COST_LIMIT_CREDIT`        | 200  | dispatcher.py (env)      | 成本上限: 超过则跳过 retry       |
| `RENDER_MAX_WORKERS`       | 6    | render_ai_video.py (env) | 并发渲染线程数上限               |

---

## 诊断入口

当视频质量有问题时，按 CLAUDE.md 五层诊断框架排查：

```
GET /api/status/{job_id}
```

返回的 `diagnostics` 字段包含：

| 路径                                            | 含义                      |
| ----------------------------------------------- | ------------------------- |
| `summary.render_fallback_scenes`                | 哪些镜头降级为 Ken Burns  |
| `summary.render_failed_scenes`                  | 哪些镜头渲染完全失败      |
| `summary.tts_fallback_scenes`                   | 哪些镜头用了备用 TTS 引擎 |
| `summary.tts_failed_scenes`                     | 哪些镜头配音完全失败      |
| `summary.assembly_adjusted_scenes`              | 哪些镜头被强行调速        |
| `summary.scene_clips_without_audio`             | 哪些镜头拼接后无音频      |
| `summary.suspected_causes`                      | 自动归因的可能原因列表    |
| `scenes.{key}.render.attempts[].motion_metrics` | 每次渲染尝试的 3 维指标   |

---

## 业界对标

| 我们的实现                   | 对标项目                        | 论文/来源                          |
| ---------------------------- | ------------------------------- | ---------------------------------- |
| Per-clip selective re-render | ViMax (HKU 2025)                | "per-shot targeted regeneration"   |
| 3 维运动检测 (dd + ms + tf)  | VBench (CVPR 2024)              | 16 维中前 3 高频维度               |
| Best-of-2 比较               | 3R Framework (arXiv 2603.01509) | "best-of-N 在 API 场景下 N=2 最优" |
| Farneback 光流替代 RAFT      | VBench lightweight mode         | CPU-only, ~50MB vs ~4GB            |
| SSIM-based flickering        | VBench temporal_flickering      | 帧间结构相似度方差                 |

---

## 原则对照

| 原则          | 体现                                                                                       |
| ------------- | ------------------------------------------------------------------------------------------ |
| **P1 可靠**   | 三层 fallback（re-render → Ken Burns → delivery block），100% 有产出；静音 = critical 拦截 |
| **A3 上下文** | motion metrics 注入 Claude prompt，下游决策者看到上游信息                                  |
| **A4 验证**   | per-clip 即时验证 + motion penalty 影响评分 + delivery block 最终兜底                      |
| **A6 成本**   | 检测 $0，精准到单 clip 重做（vs 全量 6 clip），Auto-Retry 阈值 4.0 极少触发                |
| **A7 高频**   | 只覆盖 3 个最高频故障（静止、畸变、闪烁），不做 16 维全量评估                              |
| **A8 可观测** | diagnostics.json 记录每个 clip 每次尝试的指标，auto_review.json 记录评审详情               |
