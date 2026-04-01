# Reel Agent 全业务链路体验走查报告

> 这份报告不是给工程排查细节用的，而是给产品判断“这一环到底顺不顺、哪里会掉人、该让谁改”用的。  
> 技术证据底稿见：
>
> - `doc/prelaunch-experience/report-2026-04-01.md`
> - `doc/prelaunch-experience/evidence/2026-04-01/http-summary.csv`
> - `doc/prelaunch-experience/evidence/2026-04-01/manual-review-notes.md`

---

## 一眼结论

- 当前整体体验不适合直接放大到 OpenClaw 全链路试点。
- 最容易成功的是“用户直接发照片”的视频首试。
- 最容易掉人的是“先问这是什么、安不安全、多少钱、第一步是什么”这类 trust-first 起手。
- 最危险的问题不是视频做不出来，而是系统给用户的下一步不稳定，尤其是 insight refinement、视频 revision、以及 operator 看不到推荐路径。

### 业务链路总分

| 链路环节   | 产品分（5 分） | 当前判断     |
| ---------- | -------------- | ------------ |
| 入口与激活 | `2.1 / 5`      | 红灯         |
| 首次视频   | `2.4 / 5`      | 黄红之间     |
| 首次资讯   | `2.6 / 5`      | 黄灯，但不稳 |
| 长期使用   | `1.8 / 5`      | 红灯         |
| 运营后台   | `2.2 / 5`      | 红灯         |

产品分口径：

- 由 `理解成本 + 信任感 + 时间价值 + 推荐意愿` 4 项均值组成。
- 5 分 = 可以放心给真实用户；3 分 = 能试但会掉人；2 分以下 = 明显会伤激活或口碑。

---

## 1. 入口与激活

### 这一环用户在做什么

用户第一次接触你，会先做四类动作：

- 直接发照片
- 问“这是不是 app / 怎么用”
- 问“安全吗 / 会不会是 spam”
- 问“多少钱 / 第一步是什么”

### 这一环的问题

- 用户一旦不是直接发图，而是先问 trust / setup / price，系统几乎都回同一段 welcome。
- insight-first 只接得住标准命令 `daily insight`，接不住更自然的话术。
- onboarding 仍像“先做功课再试”，不是“先拿价值再补资料”。

### 关键 case

| Case                    | 用户原话                                                 | 当前系统反应                                | 结论                           |
| ----------------------- | -------------------------------------------------------- | ------------------------------------------- | ------------------------------ |
| `INIT-E1-A2-01`         | `Is this an app? How do I use this?`                     | `first_contact / welcome`                   | 没有直接回答问题               |
| `INIT-E1-A3-01`         | `How do I know this is secure and not spam?`             | `first_contact / welcome`                   | `P0`，信任问题被回避           |
| `INIT-E4-A7-01`         | `How much is this per month?`                            | `first_contact / welcome`                   | ROI 问题被回避                 |
| `PROBE-INSIGHTFIRST-01` | `I do not have a listing today but I want daily content` | `property_content / start_property_content` | insight-first 自然话术被错路由 |

### 产品判断

- 这不是“文案还能优化一下”的级别，而是激活链路本身不稳。
- 如果 referral 用户第一句不是发图，而是先确认 trust/price/setup，当前体验会明显掉人。

### 谁来改

- `Backend`
  - 增加 `app/setup`、`trust/security`、`pricing`、`first_step` 这几类 intent。
  - broaden insight-first 识别，不只认 `daily insight`。
- `OpenClaw`
  - 接住 trust-first 用户，不要直接复读 backend welcome。
  - 把回答收敛成“一个短答 + 一个 starter task”。
- `Console / 产品设计`
  - 不要再把 onboarding 当前置入口默认答案。

---

## 2. 首次视频体验

### 这一环用户在做什么

用户已经愿意发图，想尽快看到结果，判断“这个东西到底能不能帮我做事”。

### 这一环的问题

- 视频首试仍不是最短路径，因为用户先被要求选风格。
- 交付质量有上限，但 revision 闭环不稳定。
- 如果用户自然地说“更专业一点”，系统会把它理解成重新选风格，而不是改这个视频。

### 关键 case

| Case            | 用户动作 / 话术             | 当前系统反应                                      | 结论                 |
| --------------- | --------------------------- | ------------------------------------------------- | -------------------- |
| `INIT-E1-A1-01` | 朋友推荐后直接发图          | `listing_video / start_video` + `style_selection` | 能启动，但还不够短   |
| `INIT-E4-A1-01` | 自然流量直接发图            | `listing_video / start_video` + `style_selection` | 能接住，但多一步     |
| `VIDEO-P1-05`   | `make it more professional` | `style_selection / set_style`                     | revision lane 不稳定 |

### 正向信号

- `V1` 这类 mock 说明视频交付有机会达到“经纪人愿意直接发”的水平。

### 产品判断

- 视频是目前最接近可试点的主线。
- 但要进入稳定试点，必须把“发图后第一步减负”和“交付后修改闭环”两件事修掉。

### 谁来改

- `Backend`
  - 新用户发图时默认推荐 style，减少首轮显式选择。
  - 在 delivered context 中优先识别 revision，再看 style keyword。
- `OpenClaw`
  - 把 style 选择降级为可选微调，不要抢在 first win 前面。
  - 把 adjust/revision 保持在同一条修改链里。

---

## 3. 首次资讯体验

### 这一环用户在做什么

用户今天没有 listing，或者暂时只想先看看“你能不能先给我一条能发的内容”。

### 这一环的问题

- 精确命令能跑，自然命令不稳。
- 系统给了 refinement 期待，但 refinement 实际不可用。
- insight callback 契约现在就有测试失败，说明就算前面聊通了，后面交付给 OpenClaw 也可能掉字段。

### 关键 case

| Case                      | 用户动作 / 话术      | 当前系统反应                          | 结论                     |
| ------------------------- | -------------------- | ------------------------------------- | ------------------------ |
| `INIT-E4-A4-01`           | `daily insight`      | `daily_insight / start_daily_insight` | 标准命令可用             |
| `PROBE-INSIGHT-REFINE-01` | `shorter`            | `off_topic / reject`                  | refinement 断裂          |
| `INSIGHT-P2-03`           | `more professional`  | 被拿去做 style selection              | 用户预期和系统行为不一致 |
| callback baseline         | flat insight payload | `headline` 丢空                       | 全链路契约不稳           |

### 正向信号

- `I1` 这种本地化 insight 样式是成立的，说明这条线不是没价值，而是没闭环。

### 产品判断

- 资讯不是不能做首用项，但现在只能说“有潜力”，不能说“已经可放量”。
- 最大问题不是内容质量，而是用户下一步和系统契约不稳定。

### 谁来改

- `Backend`
  - 支持 insight refinement，或者立刻移除对应 hints。
  - 统一 callback payload，兼容 flat 和 v2 shape。
- `OpenClaw`
  - 不要展示 backend 不支持的 refinement 按钮/示例。
  - insight 成功后给出明确的视频下一步。
- `Shared Contract`
  - 为所有用户可见命令和 callback schema 加联调测试。

---

## 4. onboarding 与表单

### 这一环用户在做什么

用户被邀请填资料，或者运营希望先把人“建起来”。

### 这一环的问题

- 邀请文案就是“先给我 60 秒”，明显像 setup 前置。
- 表单标题还是“先个性化内容”，不是“先让你试到价值”。
- 表单完成页是死胡同，而且只强化视频，不强化 insight-first。

### 关键 case

| Case            | 当前看到什么                                                              | 结论                     |
| --------------- | ------------------------------------------------------------------------- | ------------------------ |
| `INIT-E2-A5-01` | `To create your first FREE listing video, I need 60 seconds of your time` | 用户会感到要先做功课     |
| `INIT-E2-A5-02` | form title: `takes about 1 minute`                                        | 用户抗拒时没有退路       |
| completion page | `Next time you send us listing photos...`                                 | 只推视频，没有自然下一步 |

### 产品判断

- onboarding 现在最像“门槛”，不像“加速器”。
- 对 referral / 自然流量 / skeptical 用户，这会显著伤首试概率。

### 谁来改

- `Console / Frontend`
  - 文案从“setup first”改成“optional accelerator”。
  - completion page 给双 CTA：`send first listing` / `try today's market content`。
- `OpenClaw`
  - 对低耐心用户优先走 `T5` 这种 skip-the-form starter task。
- `Backend`
  - 不要让 readiness 逻辑在产品层被误读成“必须先填完才能开始”。

---

## 5. revision / 闭环

### 这一环用户在做什么

用户已经看过内容或视频，开始说自然语言修改意见。

### 这一环的问题

- `make it more professional` 这种非常自然的话，当前会被路由成重新选风格。
- insight lane 里的 refinement 则更糟，直接 reject。

### 关键 case

| Case            | 用户原话                    | 当前系统反应                  | 严重性 |
| --------------- | --------------------------- | ----------------------------- | ------ |
| `VIDEO-P1-05`   | `make it more professional` | `style_selection / set_style` | `P1`   |
| `INSIGHT-P2-03` | `shorter`                   | `off_topic / reject`          | `P0`   |

### 产品判断

- revision 是“像不像助手”的关键时刻。
- 现在这条链路是不可信的，必须在全链路试点前修掉。

### 谁来改

- `Backend`
  - delivered 后自由文本先走 revision，再做更细分类。
- `OpenClaw`
  - 保持一个稳定的修改会话状态，不把它变成重新 onboarding。

---

## 6. 长期使用与记忆

### 这一环用户在做什么

用户不是第一次用了，开始期待“你应该更懂我、更少问我、越来越像老搭档”。

### 这一环的问题

- 系统记住了一些 profile 字段，但没把“路径偏好 / 修改习惯 / 成功入口”真正用起来。
- operator 也看不到这个用户更适合哪条路径。

### 关键 case

| Case          | 当前表现                                  | 结论                   |
| ------------- | ----------------------------------------- | ---------------------- |
| `LONG-P3-01`  | profile 在积累，但 path preference 不可见 | 第 3 次不够明显变轻    |
| `LONG-P10-01` | revision 仍会掉回 style setup             | 第 10 次不像老用户体验 |
| `LONG-P20-01` | console 无 path history / confidence      | 成长感不可见           |

### 产品判断

- 这块现在更像“记住了资料”，不像“记住了工作方式”。
- 如果不补这层，长期壁垒不会成立。

### 谁来改

- `Backend`
  - 持久化 path preference、revision outcome、首用成功路径。
- `Console`
  - 展示 path history、recommended path、confidence。
- `OpenClaw`
  - 下次提示时优先沿用用户上一次成功路径。

---

## 7. 运营后台

### 这一环用户在做什么

不是经纪人在看，而是运营/团队在看：“这位用户现在该怎么推进？”

### 这一环的问题

- dashboard 只能告诉你“ready 不 ready”，不能告诉你“该先推什么”。
- client detail 把信息按采集渠道组织，而不是按业务目标组织。
- Skill brief 编辑过重，更像内部 prompt 工具，而不是业务动作台。

### 关键 case

| Case             | 当前后台看到什么                         | 问题                   |
| ---------------- | ---------------------------------------- | ---------------------- |
| `OPS-DASH-01`    | completeness + 视频/洞察 readiness       | 没有 recommended path  |
| `OPS-CLIENT-01`  | `Bot 待问 / 你来聊 / 表单收集`           | 没有明确 next action   |
| `OPS-ONBOARD-01` | 发完表单链接就显示 `视频就绪 / 洞察就绪` | readiness 被过度营销化 |

### 产品判断

- 现在后台更像“信息展示台”，不像“下一步动作台”。
- 这会让团队在分流上持续误判。

### 谁来改

- `Console`
  - 首页直接显示 `recommended path` + `next best action`。
  - client detail 先给“这位用户现在最该推进什么”，再展示字段细节。
- `Backend`
  - 输出 path recommendation signal，不只是 readiness。
- `OpenClaw`
  - 回传最近一次有效用户动作，让 ops 能看到上下文。

---

## 8. OpenClaw 联动视角

这轮新增的关键判断是：不是所有问题都应该在 backend 修。

### 更适合在 backend 修的

- intent 分类本身不对
- delivered 后 revision 优先级不对
- insight callback payload shape 不一致

### 更适合在 OpenClaw 修的

- trust-first 用户的回答方式
- starter task 呈现
- unsupported command/button 不该显示
- insight 后自然转 video 的引导

### 必须联动修的

- 用户可见命令契约
- `daily_insight` callback schema
- recommended path / next action 的业务定义

---

## 9. 最终建议

### 上线前必须修

1. trust / security / pricing / first-step 这 4 类问题必须有单独回答，不再回通用 welcome。
2. insight refinement 和 video revision 必须形成稳定闭环，不再“教了不会用”。
3. daily insight callback 契约必须先测通，再谈 OpenClaw 全链路。

### 首批试点前应该修

1. onboarding 从门槛改成加速器。
2. dashboard / client detail 补 `recommended path` 和 `next best action`。
3. 把 interview-first 落成真实 starter-task 路径。

### 可以放到下一轮

1. landing page 真正落地
2. path history / memory growth 的可视化
3. 更轻量的 Skill brief 管理方式

---

## 10. 如果只看 3 个最关键 case

| Case            | 为什么一定要看                         |
| --------------- | -------------------------------------- |
| `INIT-E1-A3-01` | 直接说明 trust-first 会不会掉人        |
| `INSIGHT-P2-03` | 直接说明 insight-first 能不能闭环      |
| `OPS-DASH-01`   | 直接说明团队能不能把用户推进到对的路径 |

这 3 个 case 现在都还不能放心过线。
