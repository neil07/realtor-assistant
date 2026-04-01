# 文档索引 — Reel Agent

> 最后更新：2026-04-01

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

| 文件                   | 内容                                                          | 状态 |
| ---------------------- | ------------------------------------------------------------- | ---- |
| `doc/PRD.md`           | **产品需求文档（PRD）**：完整功能清单、体验路径、指标、路线图 | 现行 |
| `PRODUCT_ROADMAP.md`   | 产品方向、用户画像（Prita）、路线图、指标                     | 现行 |
| `docs/skill-system.md` | 系统交互流程图（业务主线 + 每日资讯分支 + 运营控制台）        | 现行 |

---

## 体验压测（上线前必读）

| 文件                                                          | 内容                                       | 状态 |
| ------------------------------------------------------------- | ------------------------------------------ | ---- |
| `doc/prelaunch-experience/README.md`                          | 预上线体验压测总入口                       | 现行 |
| `doc/prelaunch-experience/master-journeys.md`                 | 初始化、视频、资讯、长期使用、后台五条主线 | 现行 |
| `doc/prelaunch-experience/initialization-playbook.md`         | 入口分流、访谈转任务、首用路径专项打法     | 现行 |
| `doc/prelaunch-experience/friction-taxonomy.md`               | 缺陷码、严重级别、口碑传播阻断点           | 现行 |
| `doc/prelaunch-experience/report-template.md`                 | 体验报告模板                               | 现行 |
| `doc/prelaunch-experience/report-2026-04-01.md`               | 2026-04-01 预上线体检正式报告              | 现行 |
| `doc/prelaunch-experience/business-walkthrough-2026-04-01.md` | 2026-04-01 产品视角业务链路走查报告        | 现行 |
| `doc/prelaunch-experience/fix-playbook-2026-04-01.md`         | 2026-04-01 体验问题修复指引                | 现行 |
| `doc/prelaunch-experience/scenario-catalog.json`              | 结构化场景目录                             | 现行 |
| `doc/prelaunch-experience/mock-output-packs.json`             | 模拟输出结果包                             | 现行 |
| `doc/prelaunch-experience/scoring-template.csv`               | 统一评分模板                               | 现行 |
| `doc/prelaunch-experience/scoring-2026-04-01.csv`             | 2026-04-01 场景评分结果                    | 现行 |
| `tools/run_dialogue_eval.py`                                  | 真实 `/api/message` 批量压测脚本           | 现行 |
| `tools/run_prelaunch_audit.py`                                | 预上线体检执行脚本                         | 现行 |

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

---

## 运营控制台（运行时访问）

| URL                            | 功能                                 |
| ------------------------------ | ------------------------------------ |
| `GET  /console/`               | 客户仪表板：所有经纪人列表 + 完整度  |
| `GET  /console/onboard`        | 创建新客户 + 生成 H5 入驻表单链接    |
| `GET  /console/form/{token}`   | H5 经纪人偏好填写表单                |
| `GET  /console/client/{phone}` | 23-field 客户详情 + Skill Brief 编辑 |
