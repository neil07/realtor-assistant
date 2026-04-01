# Reel Agent 预上线体验诊断报告

> 诊断基于压测包 v3，目标是尽可能在上线前暴露会伤激活、信任和口碑传播的问题。

---

## 1. 执行摘要

### 当前结论

产品还没有到“放心放给 40+ 资深经纪人自然试用并期待口碑传播”的状态。

不是因为视频链路不能跑，而是因为**激活链路、首用分流、修改闭环、运营分流**这四块存在系统性摩擦。当前最大风险是：

- 用户一进来带着模糊意图时，系统接不住真实问题
- 产品承诺了 `video-first / insight-first / interview-first` 三条首用路径，但当前实现里只有“照片驱动视频”相对完整
- onboarding 和后台状态正在把团队带向“先收集资料再给价值”，而不是“先让用户感受到价值”

### 最严重的判断

1. `daily insight` 的 refinements（如 `shorter`, `more professional`）与视频 revision 的自然语言修改，当前路由都不可靠，属于用户最容易直接撞上的断点。
2. 新用户的安全、价格、设置方式等高敏感问题没有被正面回答，而是被一律打回通用 welcome。
3. onboarding 仍被设计成激活前置环节，并且运营后台会被错误暗示“发了表单就已经视频/洞察就绪”。
4. 后台没有告诉运营“这位用户应该先推视频、资讯还是人工访谈”，导致人也接不住初始化分流。

### 总体建议

上线前优先修 `P0 + P1`：

- 先把消息入口分类做对
- 再把 onboarding 从“门槛”改成“加速器”
- 再把后台从“信息展示”改成“下一步动作台”

---

## 2. 诊断方法

本次诊断使用了三类证据：

### A. 压测包场景映射

使用了：

- [`scenario-catalog.json`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/prelaunch-experience/scenario-catalog.json)
- [`friction-taxonomy.md`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/prelaunch-experience/friction-taxonomy.md)
- [`initialization-playbook.md`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/prelaunch-experience/initialization-playbook.md)

### B. 代码与模板证据

重点审查：

- [`server.py`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/server.py)
- [`console/router.py`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/router.py)
- [`console/templates/onboarding.html`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/templates/onboarding.html)
- [`console/templates/onboarding_form.html`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/templates/onboarding_form.html)
- [`console/templates/form_done.html`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/templates/form_done.html)
- [`console/templates/dashboard.html`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/templates/dashboard.html)
- [`console/templates/client_detail.html`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/templates/client_detail.html)
- [`console/memory_schema.py`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/memory_schema.py)
- [`orchestrator/progress_notifier.py`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/orchestrator/progress_notifier.py)

### C. 针对性消息路由探针

直接调用了 `_classify_intent()` 做真实路由探针，得到以下关键结果：

```json
{"text":"How much is this per month?","intent":"first_contact","action":"welcome"}
{"text":"This sounds like spam.","intent":"first_contact","action":"welcome"}
{"text":"I don't know these tools, tell me the first step","intent":"first_contact","action":"welcome"}
{"text":"I do not have a listing today but I want daily content","intent":"property_content","action":"start_property_content"}
{"text":"shorter","intent":"off_topic","action":"reject"}
{"text":"more professional","intent":"style_selection","action":"set_style"}
{"text":"make it more professional","intent":"style_selection","action":"set_style"}
```

这些结果不是假设，是当前实现的直接行为。

---

## 3. Launch Blockers（P0）

### P0-1：`daily insight` 的 refinements 被承诺了，但实际接不住

- 缺陷码：`INIT-04`, `FLOW-04`
- 影响场景：
  - `INIT-E4-A4-01`
  - `INSIGHT-P2-03`
- 证据：
  - [`server.py:1164`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/server.py#L1164) 到 [`server.py:1167`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/server.py#L1167) 把 `shorter`、`more professional` 作为 daily insight 的示例命令展示给用户。
  - 但 [`server.py:1028`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/server.py#L1028) 到 [`server.py:1041`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/server.py#L1041) 在 `daily_insight` post-render 上只支持 `publish` / `skip`。
  - 实测：
    - `shorter` → `off_topic / reject`
    - `more professional` → `style_selection / set_style`
- 为什么严重：
  - 这是产品主动教给用户的交互方式，但用户一用就撞墙。
  - 会直接破坏“先试资讯”的第一印象。
  - 对低耐心用户来说，这不是小 bug，而是“这个东西不靠谱”。
- 建议：
  - 要么真正支持 `shorter` / `more professional` 的 insight refinement
  - 要么立刻删掉这两个提示，不要承诺不存在的操作

### P0-2：视频修订里的自然语言“改得更专业一点”会被误判成 style selection

- 缺陷码：`FLOW-03`, `MEM-01`
- 影响场景：
  - `VIDEO-P1-05`
  - `LONG-P10-01`
- 证据：
  - [`server.py:953`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/server.py#L953) 到 [`server.py:961`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/server.py#L961) 的 style keyword 匹配，优先于 [`server.py:1043`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/server.py#L1043) 到 [`server.py:1063`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/server.py#L1063) 的 post-delivery revision 逻辑。
  - 实测：
    - `more professional` → `style_selection`
    - `make it more professional` → `style_selection`
    - `change to elegant` → `style_selection`
- 为什么严重：
  - 这类话术就是资深经纪人最自然的修改方式。
  - 当前实现会把“我要你改视频”理解成“我要设置全局风格”，既不透明，也不可靠。
  - 这会直接摧毁 revision 作为核心体验的一致性。
- 建议：
  - 在 `DELIVERED` 上下文中，先判 revision，再判 style keyword
  - 把风格切换作为 revision 的一种 subtype，而不是单独劫持消息

---

## 4. P1 高优先级问题

### P1-1：安全、价格、设置方式等高敏感问题没有被正面接住

- 缺陷码：`TRUST-01`, `TRUST-02`, `INIT-04`
- 影响场景：
  - `INIT-E1-A2-01`
  - `INIT-E1-A3-01`
  - `INIT-E4-A7-01`
- 证据：
  - [`server.py:1065`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/server.py#L1065) 到 [`server.py:1072`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/server.py#L1072) 对新用户未知输入一律 fallback 到 welcome。
  - 实测：
    - `How much is this per month?` → 通用 welcome
    - `This sounds like spam.` → 通用 welcome
    - `I don't know these tools, tell me the first step` → 通用 welcome
- 为什么严重：
  - 目标用户最先问的往往不是功能，而是“这是什么”“安不安全”“值不值得”
  - 现在系统没有接住这些高意图问题，而是在重复自己
  - 会被理解成 bot 套话，而不是可信助手
- 建议：
  - 新增 `trust_question` / `pricing_question` / `setup_question` intents
  - 每个意图只返回一个短答复 + 一个单一步骤，不要回到大欢迎词

### P1-2：自然的 insight-first 话术很容易被错路由到 property content

- 缺陷码：`INIT-04`, `VALUE-03`
- 影响场景：
  - `INIT-E2-A4-01`
  - `INIT-E4-A4-01`
  - `INSIGHT-P2-01`
- 证据：
  - [`server.py:790`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/server.py#L790) 到 [`server.py:803`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/server.py#L803) 只要句子里有 `listing`、`photos`、`property` 等词，就容易触发 property content。
  - 实测：
    - `I do not have a listing today but I want daily content` → `property_content / start_property_content`
- 为什么严重：
  - 用户真实表达不会只说标准命令 `daily insight`
  - 一旦把“我想先试 daily content”误导到“发照片吧”，就把 insight-first 首用路径打断了
- 建议：
  - 补充 `daily content`, `market content`, `content for today`, `no listing today` 等语义
  - 对 `listing` + `daily content` 的混合句加 disambiguation，而不是硬判 property content

### P1-3：新用户视频首试仍然是 2 步，不是最短路径

- 缺陷码：`VALUE-02`, `INIT-05`
- 影响场景：
  - `INIT-E1-A1-01`
  - `INIT-E4-A1-01`
  - `VIDEO-P1-01`
- 证据：
  - [`server.py:1141`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/server.py#L1141) 到 [`server.py:1149`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/server.py#L1149) 对所有无 style 的新用户强制先选风格。
  - 但 [`orchestrator/dispatcher.py:283`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/orchestrator/dispatcher.py#L283) 到 [`orchestrator/dispatcher.py:293`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/orchestrator/dispatcher.py#L293) 已经支持根据 `estimated_tier` 自动推荐 style。
- 为什么严重：
  - 前端交互仍然把 style 当作首要选择，抵消了后端已有的自动减负能力
  - 这和 [`PRINCIPLES.md`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/PRINCIPLES.md) 对 `P5 减负 > 加功能` 的目标直接不一致
- 建议：
  - 新用户发照片后默认直接进试做，用 auto-recommend style
  - style 放到 storyboard 预览或第一轮 revision 里再微调

### P1-4：`property_content` 的 text hints 会把用户引到错误下一步

- 缺陷码：`INIT-01`, `A2`
- 影响场景：
  - `INIT-E4-A1-01`
  - `VIDEO-P1-01`
- 证据：
  - `property_content` 的主回复是“发照片吧”：
    [`server.py:1017`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/server.py#L1017) 到 [`server.py:1025`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/server.py#L1025)
  - 但如果 profile 里已有 style，`text_commands.next` 会变成：
    `Confirm or change style`
    [`server.py:1169`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/server.py#L1169) 到 [`server.py:1178`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/server.py#L1178)
  - 实测 `_get_text_hints('property_content', profile)` 返回：
    `{"next":"Confirm or change style","examples":["go","elegant","professional"]}`
- 为什么严重：
  - 用户明明还没发照片，系统却在提示“确认或改风格”
  - 这会把注意力从“先把素材发上来”拉走
- 建议：
  - `property_content` 场景统一把 next step 固定成 `send photos`
  - style 只在素材已到位时才上屏

### P1-5：onboarding 被设计成激活前置，而不是激活加速器

- 缺陷码：`INIT-05`, `VALUE-01`
- 影响场景：
  - `INIT-E2-A5-01`
  - `INIT-E2-A5-02`
  - `INIT-E3-A6-01`
- 证据：
  - 邀请消息直接说“先给我 60 秒”：
    [`console/router.py:142`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/router.py#L142) 到 [`console/router.py:149`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/router.py#L149)
  - 表单页面标题是“Help us personalize your content — takes about 1 minute.”
    [`console/templates/onboarding_form.html:37`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/templates/onboarding_form.html#L37) 到 [`console/templates/onboarding_form.html:43`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/templates/onboarding_form.html#L43)
  - 表单直接收 7 个字段，再进入试用
- 为什么严重：
  - 对低耐心用户，“先填表再试”就是典型摩擦
  - 特别是朋友推荐或自然流量进入时，这种前置 setup 会显著降低首试概率
- 建议：
  - onboarding 改成 optional accelerator
  - 允许“先试 1 次，再补 profile”
  - 对不同入口动态决定是否展示 form

### P1-6：onboarding 页面向运营错误展示“视频就绪 / 洞察就绪”

- 缺陷码：`OPS-01`, `OPS-02`
- 影响场景：
  - `OPS-ONBOARD-01`
  - `OPS-DASH-01`
- 证据：
  - 在创建客户并发送表单后，页面静态显示：
    `视频就绪` / `洞察就绪`
    [`console/templates/onboarding.html:103`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/templates/onboarding.html#L103) 到 [`console/templates/onboarding.html:112`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/templates/onboarding.html#L112)
  - 但此时用户还没有填表，也没有真正 ready
- 为什么严重：
  - 这是运营误导，不是小文案问题
  - 运营会误以为用户已 ready，实际却还没发生任何用户动作
- 建议：
  - 把这两个 badge 改成“填写后将具备”
  - 并显示当前真实状态：`link sent / form unopened / form opened / form completed`

### P1-7：form completion 页面是死胡同，而且只强化视频，不强化资讯

- 缺陷码：`VALUE-01`, `INIT-03`
- 影响场景：
  - `INIT-E2-A5-02`
  - `INSIGHT-P2-01`
- 证据：
  - 完成页只说：
    `Next time you send us listing photos, we'll create a video...`
    [`console/templates/form_done.html:39`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/templates/form_done.html#L39) 到 [`console/templates/form_done.html:44`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/templates/form_done.html#L44)
  - 没有任何立即行动按钮、bot 深链、资讯试用入口
- 为什么严重：
  - 用户刚提交完最有行动意愿，此时却没有下一步
  - 同时把产品心智重新压回“只是视频工具”，削弱了 insight-first 首用路径
- 建议：
  - 完成页加单一 CTA：
    - `Send your first listing now`
    - 或 `Try today's market content`
  - 基于入口动态推荐下一步

### P1-8：`/api/profile` 读错语言字段，已收集的语言偏好不会正确返回

- 缺陷码：`MEM-04`, `A3`
- 影响场景：
  - `INIT-E2-A5-01`
  - `LONG-P10-01`
- 证据：
  - form submit 把语言写到 `preferences.language`：
    [`console/router.py:238`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/router.py#L238) 到 [`console/router.py:241`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/router.py#L241)
  - memory schema 也定义语言路径为 `preferences.language`：
    [`console/memory_schema.py:120`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/memory_schema.py#L120) 到 [`console/memory_schema.py:125`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/memory_schema.py#L125)
  - 但 `/api/profile` 却从 `content_preferences.language` 读取：
    [`server.py:1303`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/server.py#L1303) 到 [`server.py:1311`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/server.py#L1311)
- 为什么严重：
  - 这是实打实的数据错位
  - 会导致 OpenClaw 认为用户语言仍是默认值
- 建议：
  - `/api/profile` 改读 `prefs.get("language")`
  - 并补测试覆盖这个字段

### P1-9：insight-first 路径没有真正收集 market context，就可能开始生成

- 缺陷码：`VALUE-03`, `OUTPUT-06`
- 影响场景：
  - `INIT-E4-A4-01`
  - `INSIGHT-P2-01`
- 证据：
  - `/api/message` 在新用户 `daily insight` 时允许 `market_area = null`
    [`server.py:996`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/server.py#L996) 到 [`server.py:1015`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/server.py#L1015)
  - 但 insight readiness 明确要求 `name + market_area + language`
    [`console/memory_schema.py:232`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/memory_schema.py#L232) 到 [`console/memory_schema.py:236`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/memory_schema.py#L232)
- 为什么严重：
  - 这会导致 insight-first 流程天然更容易产出 generic content
  - 也意味着“试资讯”目前缺一个关键的最小上下文收集动作
- 建议：
  - 若 `market_area` 缺失，不要直接生成
  - 用一句最短问题先补齐：`Which market should I use for your daily content?`

### P1-10：后台没有“recommended path / next best action”，运营接不住初始化分流

- 缺陷码：`OPS-01`, `OPS-02`
- 影响场景：
  - `OPS-DASH-01`
  - `OPS-CLIENT-01`
- 证据：
  - dashboard 只展示总数、完整度、视频/洞察 readiness
    [`console/templates/dashboard.html:28`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/templates/dashboard.html#L28) 到 [`console/templates/dashboard.html:179`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/templates/dashboard.html#L179)
  - client detail 只把缺失字段按 `form / bot / human / organic` 分组
    [`console/templates/client_detail.html:344`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/templates/client_detail.html#L344) 到 [`console/templates/client_detail.html:456`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/templates/client_detail.html#L456)
- 为什么严重：
  - 运营知道“缺什么字段”，但不知道“现在应该先推视频、资讯还是访谈”
  - 这不支持压测包里最关键的初始化分流能力
- 建议：
  - 增加：
    - `entry_point`
    - `first_intent`
    - `recommended_first_task`
    - `recommended_activation_path`

---

## 5. P2 中优先级问题

### P2-1：delivery / progress contract 更像传输层，不像用户体验层

- 缺陷码：`OUTPUT-05`, `FLOW-02`
- 证据：
  - `notify_delivered()` 只发 `video_url`, `caption`, `scene_count`, `word_count`, `aspect_ratio`
    [`orchestrator/progress_notifier.py:57`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/orchestrator/progress_notifier.py#L57) 到 [`orchestrator/progress_notifier.py:84`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/orchestrator/progress_notifier.py#L84)
  - `STEP_MESSAGES` 也偏系统状态，不够“真人助手化”
    [`orchestrator/progress_notifier.py:19`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/orchestrator/progress_notifier.py#L19) 到 [`orchestrator/progress_notifier.py:27`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/orchestrator/progress_notifier.py#L27)
- 风险：
  - 用户体验过度依赖 OpenClaw 额外包装
  - 一旦包装层不完整，体验会快速掉到“裸协议”

### P2-2：`more professional` 这类语句在多个上下文中存在语义冲突

- 缺陷码：`FLOW-03`
- 证据：
  - 任何包含 `professional` 的句子优先命中 style keyword
    [`server.py:953`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/server.py#L953) 到 [`server.py:961`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/server.py#L961)
- 风险：
  - 这不仅影响视频 revision，也影响 insight tone adjustment
- 建议：
  - 关键词分类必须引入上下文优先级，而不是只做字符串匹配

### P2-3：completion / onboarding / invite 三处都在强化“视频主线”，削弱“资讯主线”

- 缺陷码：`INIT-03`, `VALUE-03`
- 证据：
  - invite message 只强调 first free listing video
    [`console/router.py:142`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/router.py#L142) 到 [`console/router.py:149`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/router.py#L149)
  - form done 只强调下次发照片
    [`console/templates/form_done.html:39`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/templates/form_done.html#L39) 到 [`console/templates/form_done.html:44`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/templates/form_done.html#L44)
- 风险：
  - 资讯线会一直像“附加功能”，很难成为真正的首用路径

### P2-4：Skill editor 对普通运营太内部化

- 缺陷码：`OPS-04`
- 证据：
  - client detail 直接暴露 markdown brief 编辑器和 reset 动作
    [`console/templates/client_detail.html:222`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/templates/client_detail.html#L222) 到 [`console/templates/client_detail.html:341`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/console/templates/client_detail.html#L341)
- 风险：
  - 熟悉产品的人会觉得强大
  - 普通运营会觉得“这个系统还得懂 prompt”

---

## 6. 按主线的诊断结论

### Track 0：初始化与激活

当前最严重的问题不是入口不够多，而是入口一多，系统没有真正的分流能力。

现状更像：

- 有多个入口
- 但最终都在逼用户尽快走“发照片 / 填表”

而不是：

- 根据入口和用户起手动作，智能选择首用路径

### Track 1：首次视频体验

视频链路是当前最完整的一条，但首试前仍有不必要摩擦：

- style 前置
- 缺少 sample-first 策略
- revision 自然语言不稳

### Track 2：首次资讯体验

这是当前最脆弱的一条线：

- 能触发，但不等于能体验好
- refinement 基本不成立
- 入口语义太窄
- 缺最小 market context 收集

### Track 3：长期使用

长期价值方向是对的，但目前“成长感”和“记忆感”的体验出口还弱：

- `/api/profile` 语言字段就有错位
- revision 话术会被误分类
- 系统没有主动告诉用户“我学到了什么”

### Track 4：运营与后台

后台现在更像“客户资料总览”，还不是“初始化与跟进指挥台”。

---

## 7. Top 10 问题

| 排名 | 级别 | 问题                                                |
| ---- | ---- | --------------------------------------------------- |
| 1    | `P0` | `daily insight` refinement 被承诺但接不住           |
| 2    | `P0` | 视频 revision 自然话术被 style selection 劫持       |
| 3    | `P1` | 安全/价格/设置方式问题被通用 welcome 吞掉           |
| 4    | `P1` | insight-first 自然表达容易被误判为 property content |
| 5    | `P1` | 新用户视频首试仍需手动选 style                      |
| 6    | `P1` | `property_content` 的 next hints 指错路             |
| 7    | `P1` | onboarding 仍是前置门槛，而不是可选加速器           |
| 8    | `P1` | onboarding 页面向运营错误展示 ready 状态            |
| 9    | `P1` | form completion 没有立即下一步，而且只强化视频      |
| 10   | `P1` | 后台没有 recommended path / next best action        |

---

## 8. 上线前优先修复路线

### 第一批：先修入口和修改闭环

1. 修消息分类优先级：
   - `DELIVERED` 上下文先判 revision
   - `daily_insight` 上下文先判 refinement
2. 为新用户增加：
   - `pricing_question`
   - `trust_question`
   - `setup_question`
3. 去掉或实现 `shorter` / `more professional`

### 第二批：把 onboarding 从门槛改成加速器

1. 允许 trial-first
2. form done 加立即 CTA
3. invite / form / done 三处重新梳理视频线和资讯线

### 第三批：让后台能真正分流

1. 增加 `entry_point`, `first_intent`, `recommended_first_task`
2. dashboard 展示 recommended path
3. client detail 展示初始化历史和下一步建议

---

## 9. 最终判断

如果现在直接把产品推给目标用户，最可能发生的不是“功能不够多”，而是：

- 有兴趣的人被入口和 welcome 套话劝退
- 想先试资讯的人被错误推去发照片
- 愿意修改的人发现系统没听懂
- 运营知道用户资料不完整，但不知道最该推哪一步

换句话说，当前最需要修的不是模型，而是**激活协议、分流逻辑、和下一步设计**。

只要把这些先修顺，现有视频能力和内容能力才有机会真正被感知成“非常棒的体验”。
