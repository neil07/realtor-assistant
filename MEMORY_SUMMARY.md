# Memory Summary

Reel Agent 项目开发记录摘要，基于 2026-03-16 至 2026-03-23 的工作日志。

## 用户档案

- **用户:** Neil（Neo），电话 +60175029017
- 通过 WhatsApp 沟通，中文交流，英文视频输出
- 视频风格偏好：Elegant ✨ / Modern 音乐 / 不显示价格
- 用户 Profile 存储于 `skills/listing-video/profiles/+60175029017.json`

## 用户对话历程摘要

### Session 1 — 2026-03-15/16：初次接触 + 前两个视频

- **Neo（Neil）首次通过 WhatsApp 联系**，发送了 Washington Condo 的 9 张房源照片
- Agent 收集用户偏好（风格 Elegant、Modern 音乐、不显示价格），保存了用户 Profile
- 使用 Ken Burns + ElevenLabs 生成了第一个视频（竖版 + 横版），通过 GCS 链接交付
- 发现 WhatsApp 文件发送功能故障，改为上传 GCS 公开 bucket 发链接
- Neo 随后发来 Austin Condo 的 5 张照片，生成第二个视频；此时 ElevenLabs 额度耗尽，改用 macOS `say` 作为 TTS
- Neo 又发了一张 Austin 郊区房屋照片，等待更多照片中

### Session 2 — 2026-03-18：Austin Park 多版本迭代

- Neil 要求对 Austin Park（6 张照片）用新的 V2 管线制作视频
- 尝试了 AI 场景规划（Claude Vision）+ Seedance 1.0 Pro AI 视频生成
- 生成了 V1-V3 多个版本，持续迭代优化，全部上传至 GCS
- Seedance 出现超时问题，开始考虑替代方案

### Session 3 — 2026-03-19：爆款视频 + Runway 突破

- Neil 要求制作「爆款/Viral」风格的视频
- 切换到 Runway Gen-4 Turbo（~25s/clip，成功率高），用高动态 prompt 重新生成所有场景
- 加入了背景音乐（Bensound）、PIL 文字叠加、音乐 ducking 等效果
- **V4 版本获得 Neil 认可，评价最好**
- Neil 要求更新 SKILL.md 文档记录技术经验（部分完成）

### Session 4 — 2026-03-22：Austin Park V7 + 模型升级

- 使用 SeeDance 1.5 Pro（通过 IMA Studio API）重新制作 Austin Park
- 5 个场景，31.5 秒，通过 catbox.moe 交付
- IMA Studio 成为新的主力视频生成平台（30 pts/clip）

### Session 5 — 2026-03-23：River Modern 新加坡项目

- Neil 发来 PropertyGuru 链接，要求制作新加坡 River Modern 的视频
- Agent 自动从 PropertyGuru CDN 下载 8 张照片（去重后 6 张有效）
- 使用 SeeDance 1.5 Pro + Edge TTS 生成 46 秒视频
- Neil 提出**重要偏好：视频永远存 GCS，发永久链接，不用临时文件服务**
- 通过 tmpfiles.org 临时交付（后续应改为 GCS）

### 用户反馈要点

- 偏好高动态、有冲击力的视频效果（V4 爆款风格最受认可）
- 要求永久 GCS 链接交付，拒绝临时链接
- 中文沟通，视频内容用英文
- 对视频质量有较高期望，愿意多次迭代

## 已完成视频项目

| 日期 | 项目 | 版本 | 时长 | 技术栈 |
|------|------|------|------|--------|
| 03-15 | Washington Condo | V1 | ~30s | Ken Burns + ElevenLabs TTS |
| 03-16 | Austin Condo | V1 | ~30s | Ken Burns + macOS `say` (ElevenLabs 额度耗尽) |
| 03-18 | Austin Park | V1-V3 | ~23s | Ken Burns → Seedance 1.0 Pro + per-scene TTS |
| 03-19 | Austin Park Viral (V4) | V4 最佳 | ~22s | Runway Gen-4 Turbo + PIL 文字叠加 + 背景音乐 |
| 03-22 | Austin Park | V7 | 31.5s | SeeDance 1.5 Pro (IMA Studio) |
| 03-23 | River Modern (新加坡) | Final | 46s | SeeDance 1.5 Pro + Edge TTS |

## 视频生成管线演进

1. **V1 (03-15):** Ken Burns 平移缩放 + ElevenLabs 语音 → 简单但效果有限
2. **V2 (03-18):** AI 场景规划(Claude Vision) + Seedance 1.0 Pro AI 视频 + 分场景 TTS
3. **V3 (03-19):** Runway Gen-4 Turbo 替代 Seedance（更快更稳定）+ PIL 文字叠加 + 背景音乐自动化
4. **V4 (03-22+):** SeeDance 1.5 Pro via IMA Studio（30pts/clip）+ Edge TTS + 并行生成

## 关键技术栈

- **AI 视频模型:** SeeDance 1.5 Pro (当前主力, IMA Studio API) / Runway Gen-4 Turbo (备选)
- **TTS 链:** ElevenLabs → OpenAI TTS → Edge TTS (en-US-GuyNeural) → macOS `say` (Evan)
- **场景规划:** Claude Vision API 分析照片 → 自动规划场景顺序
- **组装:** ffmpeg concat + 分场景音频对齐 + setpts 速度调整
- **文字叠加:** Python PIL 生成透明 PNG（macOS ffmpeg 无 drawtext）
- **背景音乐:** Bensound 素材，volume=0.15 ducking

## 交付与存储

- **GCS Bucket:** `gs://reel-agent-videos/`（公开读取，永久链接）
- **URL 格式:** `https://storage.googleapis.com/reel-agent-videos/YYYY/MM/filename.mp4`
- 临时方案：tmpfiles.org / catbox.moe（不推荐，不稳定）

## 已知问题与限制

- ElevenLabs 额度耗尽（1000 credits 已用完）
- WhatsApp 文件发送不可用（gateway bug: "No active WhatsApp Web listener"）
- macOS ffmpeg 无 libfreetype，不支持 drawtext filter
- ffmpeg xfade 在 zsh 下有变量展开问题，改用 concat
- PropertyGuru CDN 需要 Referer header 才能下载
- OPENAI_API_KEY 未设置

## 核心脚本

| 脚本 | 用途 |
|------|------|
| `scripts/plan_scenes.py` | Claude Vision AI 场景规划 |
| `scripts/write_video_prompts.py` | AI 生成视频提示词 |
| `scripts/render_ai_video.py` | SeeDance/Runway 视频渲染 |
| `scripts/generate_voice.py` | TTS 语音生成（多引擎） |
| `scripts/assemble_final.py` | V2 视频组装 + 音频对齐 |
| `scripts/job_logger.py` | 结构化日志 |
| `~/.openclaw/workspace/skills/ima-all-ai/scripts/ima_create.py` | IMA Studio API 调用 |
