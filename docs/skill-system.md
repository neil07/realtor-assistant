# Skill 系统设计文档

> 核心理念：平台最终沉淀的资产，是每一个经纪人的 Skill — 个人创意简报 + 偏好 + 反馈历史的累积。

---

## 图一：完整业务流程

```mermaid
flowchart TD
    subgraph 经纪人端
        A1[📱 WhatsApp 发送照片]
        A2[收到视频]
        A3[回复反馈 👍/👎 + 文字]
        A4[早上收到每日资讯图卡]
    end

    subgraph OpenClaw
        B1[接收消息 + 照片]
        B2[POST /webhook/in]
        B3[POST /api/message\n意图分类路由]
    end

    subgraph 编排层 orchestrator
        C1{Profile 存在?}
        C2[创建 Profile\n写入默认偏好]
        C3[加载 Profile]
        C4{Skill Brief 存在?}
        C5[从全局默认复制\nprofiles/briefs/phone/video.md]
        C6[加载个人 Brief]
        C7[提交 Job 到调度队列]
        C8[DailyScheduler\nUTC 13:00 触发]
    end

    subgraph Pipeline 能力层
        D1[🎬 Creative Director\nOpus — 使用个人 Brief\n分析照片+剧本+场景+运镜]
        D2a[🎙️ 并行 TTS\nElevenLabs → OpenAI → IMA]
        D2b[🎥 并发 IMA 视频生成\nThreadPoolExecutor\nwan2.6-i2v × N scenes]
        D3[✂️ 视频组装 FFmpeg]
        D4[⭐ 质量审核 review_video]
        D5[📰 每日资讯生成\ngenerate_daily_insight\n+ render_insight_image]
    end

    subgraph 运营控制台 Console
        E1[GET /console\n查看所有经纪人状态]
        E2[客户详情\n/console/client/phone]
        E3[PUT 保存 Brief\n/console/client/phone/skills/video]
        E4[GET /console/onboard\nH5 入驻表单]
    end

    A1 --> B1 --> B2 --> C1
    C1 -->|No| C2 --> C4
    C1 -->|Yes| C3 --> C4
    C4 -->|No| C5 --> C6
    C4 -->|Yes| C6
    C6 --> C7 --> D1
    D1 --> D2a & D2b
    D2a & D2b --> D3 --> D4
    D4 -->|score ≥ 6.5| A2
    D4 -->|score < 6.5| D3

    C8 --> D5 --> A4

    A2 --> A3 --> E1
    E1 --> E2 --> E3 --> C6
    E4 -.->|onboarding| C2

    style C5 fill:#fef3c7,stroke:#f59e0b
    style D2b fill:#dbeafe,stroke:#3b82f6
    style E3 fill:#dcfce7,stroke:#22c55e
    style D5 fill:#f0fdf4,stroke:#22c55e
    style C8 fill:#eff6ff,stroke:#3b82f6
```

---

## 图二：Skill 飞轮（核心资产增长逻辑）

```mermaid
flowchart LR
    S1[第 1 次\n全局默认 Brief] -->|生成视频| S2[收到反馈\n记录到 profile]
    S2 -->|运营人员在后台调参| S3[更新个人 Brief\n加入风格偏好/禁用词]
    S3 -->|第 N 次| S4[视频更符合\n经纪人个人品牌]
    S4 -->|更多视频 → 更多数据| S2

    style S3 fill:#dcfce7,stroke:#22c55e
    style S4 fill:#dbeafe,stroke:#3b82f6
```

---

## 图三：版本 Diff（1.x → 2.0）

| 维度         | 1.x（旧）                                 | 2.0（新）                                                        |
| ------------ | ----------------------------------------- | ---------------------------------------------------------------- |
| 创意简报     | 所有经纪人共用一份 `creative_director.md` | 每人一个 `profiles/briefs/{phone}/video.md`，运营后台可查看/编辑 |
| 视频生成并发 | 串行 for 循环，scene1→scene2→...          | `ThreadPoolExecutor`，所有 scene 同时提交 IMA，等最慢那个        |
| 视频模型     | `kling-v2-6`（贵、慢、时长限制）          | `wan2.6-i2v`（更快 ~90s/clip，无时长限制）                       |
| TTS 主路径   | IMA TTS（需任务队列，慢）                 | ElevenLabs（单次 HTTP 秒级）→ OpenAI → IMA 兜底                  |
| 反馈闭环     | 无                                        | 反馈记录到 `profile.revision_history`，运营后台可据此更新 Brief  |
| 运营后台     | 无                                        | `/admin` 页面：列表 + 浏览器内 Markdown 编辑器                   |

---

## 图四：Skill 文件结构

```
skills/listing-video/
├── prompts/
│   └── creative_director.md        ← 全局默认（只读，所有人的起点）
└── profiles/
    ├── +60175029017.json            ← 经纪人基础信息 + 反馈历史
    └── briefs/
        ├── 60175029017/
        │   └── video.md             ← Neo 的个人 Skill Brief（可定制）
        ├── 1234567890/
        │   └── video.md             ← Agent B 的个人 Skill Brief
        └── ...
            └── video.md             ← 未来扩展：poster.md, news.md...
```

---

## 运营控制台使用方式

服务启动后，访问 `http://localhost:8000/console`：

| 页面        | URL                                                | 功能                                    |
| ----------- | -------------------------------------------------- | --------------------------------------- |
| 仪表板      | `/console/`                                        | 查看所有经纪人，显示 Brief 是否已定制   |
| 创建客户    | `/console/onboard`                                 | 创建新经纪人 profile + 生成 H5 表单链接 |
| H5 入驻表单 | `/console/form/{token}`                            | 经纪人填写偏好（风格/市场/语言等）      |
| 客户详情    | `/console/client/{phone}`                          | 23-field 详情 + Skill Brief 在线编辑    |
| 保存 Brief  | `PUT /console/client/{phone}/skills/{type}`        | 保存视频或资讯 Skill Brief              |
| 重置 Brief  | `POST /console/client/{phone}/skills/{type}/reset` | 恢复为全局默认                          |
| 字段编辑    | `POST /console/api/update-field`                   | HTMX 内联编辑任意字段（无 reload）      |

---

## 关键设计决策

| 决策点                    | 选择           | 原因                                                      |
| ------------------------- | -------------- | --------------------------------------------------------- |
| Brief 存哪里              | 文件系统 `.md` | 运营人员可直接用编辑器改，无需数据库                      |
| `profile.json` 加不加字段 | 不加           | 路径由 phone 派生，无需显式存储                           |
| 全局 default 改不改       | 不改           | 全局 default 是新经纪人的起点，永远有效                   |
| 反馈 → 自动更新 Brief     | 本期不做       | 先人工调参验证价值，再自动化                              |
| 多 Skill 支持             | 目录结构已预留 | `video.md` 命名，未来加 `poster.md`、`news.md` 零成本扩展 |
