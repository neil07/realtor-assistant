# 文档索引 — Reel Agent

> 最后更新：2026-03-30

新 agent 从这里开始。先读"核心事实层"4 个文件，再按需查"项目宪法"和"产品文档"。

---

## 核心事实层（新 agent 必读，3 分钟吸收项目）

| 文件           | 内容                               | 状态             |
| -------------- | ---------------------------------- | ---------------- |
| `PROJECT.md`   | 项目身份证：定位、架构、技术栈     | 现行             |
| `STATUS.md`    | 项目状态板：doing / blocked / next | 现行，需持续更新 |
| `DECISIONS.md` | 8 条关键决策（每条有原因和影响）   | 现行             |
| `RUNBOOK.md`   | 启动、测试、验证、回滚             | 现行             |

---

## 项目宪法（开发必读，权威技术文档）

| 文件                             | 内容                                 | 状态 |
| -------------------------------- | ------------------------------------ | ---- |
| `CLAUDE.md`                      | 架构硬约束、代码规范、诊断规则、进度 | 现行 |
| `SOUL.md`                        | Agent 人格定义                       | 现行 |
| `AGENTS.md`                      | Agent 行为规则 + 5 Skill 展开        | 现行 |
| `skills/listing-video/SKILL.md`  | Skill 层行为 spec（6 状态机）        | 现行 |
| `skills/listing-video/README.md` | 技术栈 + 成本 + API key 清单         | 现行 |

---

## 产品文档

| 文件                  | 内容                                      | 状态 |
| --------------------- | ----------------------------------------- | ---- |
| `PRODUCT_ROADMAP.md`  | 产品方向、用户画像（Prita）、路线图、指标 | 现行 |
| `doc/PRODUCT_FLOW.md` | 系统交互流程图（4 个场景 + 记忆分工）     | 现行 |

---

## 参考文档（不需要日常读，按需查用）

| 文件                                                   | 内容                   | 状态                                        |
| ------------------------------------------------------ | ---------------------- | ------------------------------------------- |
| `doc/产品原则概述.md`                                  | 1.0→2.0 升级思考原始稿 | 仅供参考——核心结论已进入 PRODUCT_ROADMAP.md |
| `doc/Principle - 面向 Agent 的产品设计 5 原则_副本.md` | Agent 产品设计框架     | 仅供参考                                    |
| `IDENTITY.md`                                          | Agent 身份卡片         | OpenClaw 模板——身份定义见 SOUL.md           |
| `TOOLS.md`                                             | 本地环境模板           | OpenClaw 模板——未填充                       |
| `USER.md`                                              | 用户上下文模板         | OpenClaw 模板——未填充                       |
| `HEARTBEAT.md`                                         | 周期任务占位           | OpenClaw 模板——空文件                       |

---

## 用户研究（一手资料）

| 文件                                | 内容                                               |
| ----------------------------------- | -------------------------------------------------- |
| `doc/prita-interview-transcript.md` | Prita 访谈（核心用户，10 年经纪人，100% referral） |
| `doc/Stephanie-01.md`               | Stephanie 访谈                                     |
| `doc/natalie-transcript(1).md`      | Natalie 访谈                                       |
| `doc/Stephanie-01.pdf`              | Stephanie 访谈 PDF                                 |
| `doc/FrankLu-03.pdf`                | Frank 访谈 PDF                                     |
| `doc/John-04.pdf`                   | John 访谈 PDF                                      |
| `doc/Yvonne-02.pdf`                 | Yvonne 访谈 PDF                                    |
| `doc/Natalie-06.pdf`                | Natalie 访谈 PDF                                   |
| `doc/audio*.txt`                    | 访谈音频转录                                       |
| `doc/Agent 产品设计框架*.pdf`       | Agent 设计框架参考                                 |

---

## 框架参考（外部文档）

| 文件                     | 内容                        |
| ------------------------ | --------------------------- |
| `doc/openclaw/SOUL.md`   | OpenClaw SOUL.md 格式说明   |
| `doc/openclaw/AGENTS.md` | OpenClaw AGENTS.md 格式说明 |
| `doc/openclaw/SKILL.md`  | OpenClaw SKILL.md 格式说明  |

---

## 开发者工具

| 文件                                | 内容                            |
| ----------------------------------- | ------------------------------- |
| `.claude/commands/start.md`         | /start 命令：环境检查 + 启动    |
| `.claude/commands/test-pipeline.md` | /test-pipeline 命令：端到端测试 |
| `.claude/commands/debug.md`         | /debug 命令：排查流程           |
| `.claude/commands/review.md`        | /review 命令：代码审查清单      |
| `.claude/settings.local.json`       | Hook：保存时自动 ruff format    |
