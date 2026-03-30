# /start — 启动开发环境

执行以下步骤：

1. 检查 Python 版本 >= 3.11
2. 检查 .venv 是否存在，不存在则创建：`python3 -m venv .venv`
3. 激活 venv 并安装依赖：`pip install -r requirements.txt`
4. 检查 .env 是否存在，不存在则从 .env.example 复制并提示填写 API keys
5. 检查 ffmpeg 是否安装
6. 运行 `ruff check skills/listing-video/scripts/` 确认代码无报错
7. 输出环境状态摘要
