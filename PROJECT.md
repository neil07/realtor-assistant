# PROJECT — Reel Agent

## 一句话定位

房产经纪人的 AI 社媒助手。经纪人发 listing 照片，自动生成营销短视频。
WhatsApp / Telegram / iMessage 都可以作为入口，OpenClaw 负责对话层，后台异步生产。

## 架构

```
经纪人 → WhatsApp / Telegram / iMessage → OpenClaw（对话层）→ Reel Agent 后台（生产层）→ 视频
                                                                  ↓
                                                        Claude / IMA Studio / ElevenLabs / ffmpeg
```

三层：对话层（OpenClaw agent）、编排层（orchestrator/ + agent/ + db/）、能力层（skills/listing-video/scripts/）

## 技术栈

| 层          | 技术                                                      |
| ----------- | --------------------------------------------------------- |
| 语言        | Python 3.11+                                              |
| AI 推理     | Claude Sonnet 4.6（剧本/分析/分镜/Review）                |
| AI 视频     | IMA Studio（Kling 2.6 / WAN），fallback Ken Burns 幻灯片  |
| AI 配音     | IMA Studio TTS → ElevenLabs → OpenAI TTS（三级 fallback） |
| 视频合成    | ffmpeg（拼接 + 转场 + 配音 + BGM + 字幕）                 |
| 存储        | SQLite（aiosqlite，job 状态机）                           |
| Web 框架    | FastAPI + uvicorn                                         |
| 格式化/Lint | Ruff                                                      |

## 五个 Skill

| Skill    | KPI                         |
| -------- | --------------------------- |
| 需求深挖 | 挖出完整可执行的视频需求    |
| 剧本     | 产出打动人的叙事 + 配音文案 |
| 分镜     | 每个镜头有精准视觉指令      |
| 生成     | 输出经纪人愿意直接发的成品  |
| 复盘     | 每轮反馈让下次更准          |

## 状态机

```
QUEUED → ANALYZING → SCRIPTING → PROMPTING → PRODUCING → ASSEMBLING → DELIVERED | FAILED
```

## AI 视频红线

1. 禁止添加照片中没有的物体（家具、人、车、宠物）
2. 禁止改变天气、季节、时间
3. 禁止虚拟 staging
4. 禁止修改房屋结构或外观
5. 只允许：运镜、光影微变、自然摆动、景深变化

## 成本结构

| 内容类型     | 单条成本    |
| ------------ | ----------- |
| 新上房源视频 | ~$2.82      |
| 每日市场资讯 | ~$0.05-0.08 |

## 代码规范

- Ruff format + lint，行宽 100
- 函数签名必须有类型注解
- 公开函数 Google style docstring
- snake_case（函数/变量），PascalCase（类）

## 关键文档

详细技术约束 → `CLAUDE.md`（项目宪法）
Agent 人格 → `SOUL.md`
Agent 行为 → `AGENTS.md`
产品方向 → `PRODUCT_ROADMAP.md`
全部文档 → `docs/INDEX.md`
