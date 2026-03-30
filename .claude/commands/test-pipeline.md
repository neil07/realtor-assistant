# /test-pipeline — 测试端到端 pipeline

用真实照片测试完整视频生成流程：

1. 确认测试照片路径（用户提供或用 skills/listing-video/output/ 下已有的）
2. 逐步执行 pipeline：
   - Skill 1: analyze_photos.py → 验证照片分析输出
   - Skill 2: plan_scenes.py + generate_script.py → 验证场景规划 + 脚本
   - Skill 3: write_video_prompts.py → 验证 AI 视频 prompt
   - Skill 4: render_ai_video.py + generate_voice.py + assemble_final.py → 验证生成
3. 每步输出中间结果供检查
4. 记录耗时和成本
5. 输出测试报告
