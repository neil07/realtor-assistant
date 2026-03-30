# RUNBOOK — Reel Agent

启动、测试、验证、回滚的最小闭环路径。

---

## 1. 启动开发环境

```bash
# 前置要求：Python 3.11+, ffmpeg
python3 --version     # 确认 >= 3.11
ffmpeg -version       # 确认已安装

# 创建虚拟环境 + 安装依赖
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 配置密钥
cp .env.example .env
# 编辑 .env，填入真实 API key：
#   ANTHROPIC_API_KEY（必须）
#   IMA_API_KEY（必须）
#   ELEVENLABS_API_KEY（可选 fallback）
#   OPENAI_API_KEY（可选 fallback）

# 启动 server
uvicorn server:app --reload --port 8000
# 打开 http://localhost:8000 查看测试 UI
```

## 2. 本地测试（单条 pipeline，不走 server）

```bash
cd skills/listing-video/scripts
python pipeline.py \
  --photos /path/to/listing/photos \
  --address "123 Main St, City" \
  --price "$850,000" \
  --style professional
# 输出在 skills/listing-video/output/{timestamp}/ 下
# 检查中间产物：analysis.json, scenes.json, script.json, prompts.json
```

## 3. API 测试（走 server）

```bash
# 提交生成任务
curl -X POST http://localhost:8000/api/generate \
  -F "photos=@photo1.jpg" \
  -F "photos=@photo2.jpg" \
  -F "style=professional" \
  -F "address=123 Main St"
# 返回 {"job_id": "xxx"}

# 轮询状态
curl http://localhost:8000/api/status/{job_id}
# 状态流转：QUEUED → ANALYZING → SCRIPTING → PROMPTING → PRODUCING → ASSEMBLING → DELIVERED

# 查看 agent profile
curl http://localhost:8000/api/profile/{phone}
```

## 4. 验证质量系统

```bash
cd skills/listing-video/scripts

# Motion metrics 单独验证
python motion_metrics.py /path/to/video.mp4
# 输出：dynamic_degree, motion_smoothness, labels

# Review 单独验证（参数：video_path, duration, has_audio, scene_count）
python review_video.py /path/to/video.mp4 30 true 6
# 输出：auto_review.json（overall_score, top_issues, motion_metrics）
```

## 5. 代码检查

```bash
ruff format .          # 格式化
ruff check .           # lint
ruff check . --fix     # 自动修复
```

## 6. 回滚

```bash
git log --oneline -10   # 查看最近 commit
git revert <commit>     # 创建回滚 commit（安全，不丢历史）
# 不要用 git reset --hard，会丢失未提交的工作
```

## 关键路径文件

| 场景         | 入口文件                                     |
| ------------ | -------------------------------------------- |
| 完整 server  | server.py                                    |
| CLI 单条测试 | skills/listing-video/scripts/pipeline.py     |
| Job 状态查询 | orchestrator/job_manager.py                  |
| 异步调度     | orchestrator/dispatcher.py                   |
| 质量评审     | skills/listing-video/scripts/review_video.py |
