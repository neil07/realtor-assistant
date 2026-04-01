# 预上线体验压测包 — Reel Agent

> 目的不是证明产品“能用”，而是尽可能在上线前把体验问题逼出来。
> 这套压测包默认采用最苛刻视角：40+、资深、低耐心、不熟工具、强 ROI 导向的经纪人。

---

## 这套压测包解决什么问题

Reel Agent 的核心风险不是“功能缺一个按钮”，而是以下几类体验断点：

- 用户第一分钟就搞不清下一步
- 用户不信任入口，不敢继续
- onboarding 挡住首次价值验证
- 第一次输出看起来“太 AI”或“不像我会发的东西”
- 第 10 次体验和第 1 次没有明显变轻松
- 运营后台看不出该把用户导向视频、资讯还是人工访谈

这套压测包把这些风险拆成可执行素材，确保每个问题都能被记录、归因、排序，而不是靠印象争论。

---

## 压测原则

### 1. 不帮产品找借口

评估者不能自动脑补：

- “用户应该能理解这个”
- “真实情况下我们会解释一下”
- “这是因为现在还没接模型”

只记录用户当下看到和听到的东西。

### 2. 证据优先

每个发现都必须附上至少一条证据：

- 原始用户话术
- 原始系统回复
- 原始页面截图或页面片段
- 模拟输出包编号

没有证据，不进报告。

### 3. 第一反应最重要

首轮体验的价值在于捕捉“本能反应”：

- 迷惑
- 怀疑
- 不耐烦
- 愿不愿继续

不要在用户已经被解释过之后再回头补打分。

### 4. 先测激活，再测优化

顺序固定：

1. 初始化与激活
2. 首次价值验证
3. 修订与持续使用
4. 运营与后台动作

如果第 1 步就没过，第 2-4 步再漂亮也不能掩盖首用失败。

### 5. 按“口碑传播”而不是“功能存在”来判断

最终判断标准不是：

- 功能是否已实现
- 模型是否理论上能做

而是：

- 用户会不会继续用
- 用户会不会推荐同事
- 用户会不会把你和“又一个复杂工具”归到一起

---

## 最重要的压测维度

这套包重点压以下原则：

| 原则                | 为什么在体验压测里最重要                   |
| ------------------- | ------------------------------------------ |
| `P1 可靠 > 炫技`    | 一次“没出来”或“看起来不能发”就可能永久流失 |
| `P2 记忆是资产`     | 第 10 次还像第 1 次，产品没有壁垒          |
| `P4 协作者非执行器` | 系统要像制片人，不是死执行器               |
| `P5 减负 > 加功能`  | 每多一步都在伤激活率                       |
| `P6 成长可感知`     | 用户必须感受到“它越来越懂我了”             |
| `A2 闭环优先`       | 每个流程都要有明确下一步                   |
| `A8 可观测优先`     | 没有结构化证据，体验问题会被争论掉         |

---

## 文件地图

| 文件                                                                                                                                 | 用途                                      |
| ------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------- |
| [`master-journeys.md`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/prelaunch-experience/master-journeys.md)                 | 人可直接走读的完整体验主线                |
| [`initialization-playbook.md`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/prelaunch-experience/initialization-playbook.md) | 初始化、入口分流、访谈转任务的专项打法    |
| [`friction-taxonomy.md`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/prelaunch-experience/friction-taxonomy.md)             | 缺陷分类、严重级别、口碑风险映射          |
| [`scenario-catalog.json`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/prelaunch-experience/scenario-catalog.json)           | 结构化场景目录，供脚本和人工共用          |
| [`mock-output-packs.json`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/prelaunch-experience/mock-output-packs.json)         | 视频/资讯/任务编排模拟结果包              |
| [`scoring-template.csv`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/prelaunch-experience/scoring-template.csv)             | 统一评分表                                |
| [`report-template.md`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/prelaunch-experience/report-template.md)                 | 最终体验报告模板                          |
| [`run_dialogue_eval.py`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/tools/run_dialogue_eval.py)                                | 批量调用真实 `/api/message`，记录消息返回 |

---

## 推荐执行方式

### 角色分工

- `Facilitator`：控场，不替系统解释
- `Evaluator`：扮演目标用户，给出第一反应
- `Scribe`：实时记录证据、评分、缺陷码
- `Owner`：最后决定优先级

### 轮次

#### Round 1：激活压测

只看入口、首消息、首任务、首轮信任建立。

目标：

- 找出为什么用户不往下走
- 决定视频、资讯、访谈三条首用路径谁更顺

#### Round 2：首次价值压测

引入模拟 storyboard、模拟交付、模拟资讯卡片。

目标：

- 找出“能不能发”
- 找出“像不像 AI”
- 找出“是不是太麻烦”

#### Round 3：长期使用压测

模拟第 3 次、第 10 次、第 20 次。

目标：

- 记忆是否起作用
- 是否真的更快
- 是否形成“老搭档”心智

#### Round 4：运营台压测

只看内部动作。

目标：

- 运营是否一眼知道下一步
- 是否能判断用户该走哪条初始化路径

---

## Stop-The-Line 红线

出现以下任意一条，默认记为上线前必须处理：

- 新用户第一分钟还不知道下一步做什么
- 首条价值验证被 onboarding 或解释流程挡住
- 系统接不住用户的自然起手动作
- 输出虚构内容或明显违背真实房源
- returning user 被重复问明显已知偏好
- 运营后台无法看出“该先推视频、资讯还是人工访谈”

详细分类见 [`friction-taxonomy.md`](/Users/liusiyuan/Desktop/RealEeaste/video-mvp1.0/doc/prelaunch-experience/friction-taxonomy.md)。

---

## 用真实对话层压测

本项目允许对话层走真实服务。批量记录可使用：

```bash
python tools/run_dialogue_eval.py \
  --base-url http://localhost:8000 \
  --token "$REEL_AGENT_TOKEN" \
  --output /tmp/reel-agent-dialogue-eval.jsonl
```

默认只跑 `scenario-catalog.json` 里标记为 `live_dialogue` 的场景。

如需映射 returning-user 手机号：

```bash
python tools/run_dialogue_eval.py \
  --base-url http://localhost:8000 \
  --token "$REEL_AGENT_TOKEN" \
  --phone-map /path/to/phone-map.json \
  --scenario INIT-E1-A2-01 \
  --scenario INIT-E4-A7-01
```

`phone-map.json` 示例：

```json
{
  "new_user_referral": "+15550001001",
  "returning_user_basic": "+15550001002"
}
```

---

## 产出标准

压测结束时，至少要能明确回答：

1. 哪种入口最容易激活
2. 哪种入口最容易流失
3. onboarding 应不应该前置
4. 资讯应该作为首用项还是留存项
5. 访谈转任务是否比直接塞表单更适合目标用户
6. 哪些问题会直接阻断口碑传播

如果这些问题答不清，这轮压测还不算完成。
