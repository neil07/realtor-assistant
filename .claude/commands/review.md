# /review — 代码审查

对最近修改的代码进行审查：

1. `git diff` 查看未提交的改动
2. 检查每个改动文件：
   - 是否符合 CLAUDE.md 中的架构约束（双模运行、AI 视频红线等）
   - 是否有密钥泄露风险（UUID、eyJ、sk- 模式）
   - 是否符合代码规范（类型注解、命名规范）
3. 运行 `ruff check` + `ruff format --check`
4. 检查是否有新增的 TODO/FIXME 需要跟踪
5. 输出审查结果 + 建议
