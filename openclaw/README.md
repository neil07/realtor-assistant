# OpenClaw 接线层

> 这层的目标不是替代项目后端，而是把「渠道接线 + plugin 运行时 + 本机 OpenClaw 装配」也纳入仓库真相。

## 目录结构

```text
openclaw/
├── README.md
├── config/
│   └── reel-agent-bridge.config.example.json
└── extensions/
    └── reel-agent-bridge/
        ├── index.ts
        ├── openclaw.plugin.json
        └── package.json

scripts/
└── openclaw/
    └── install-local-wiring.sh
```

## 版本化什么

这些内容应该进 GitHub：

- `openclaw/extensions/reel-agent-bridge/*`
- `doc/openclaw/*` 里的接线契约、walkthrough、state schema
- `scripts/openclaw/install-local-wiring.sh`

这些内容继续留在本机：

- `~/.openclaw/openclaw.json` 里的真实密钥
- `~/.openclaw/plugins/reel-agent-bridge/state.json`
- `~/.openclaw/workspace-realtor-social/.openclaw/reel-agent-bridge-state.json`
- sessions / logs / cache

## 本机安装

拉下仓库后，运行：

```bash
/Users/lsy/projects/realtor-social/scripts/openclaw/install-local-wiring.sh
```

脚本会做 3 件事：

1. 把 `~/.openclaw/extensions/reel-agent-bridge` 切成指向仓内源码的符号链接
2. 在 `~/.openclaw/openclaw.json` 里补齐 `reel-agent-bridge` 的 load path 和本机配置
3. 用现有 `.env` / 环境变量里的 `OPENCLAW_CALLBACK_SECRET` 补全 plugin config

如果你只想手工核对配置结构，可参考：

- `/Users/lsy/projects/realtor-social/openclaw/config/reel-agent-bridge.config.example.json`

## 多机迁移

另一台 Mac 要端到端接管时，最少做这些：

1. pull 本仓
2. 同步 `.env`
3. 运行 `scripts/openclaw/install-local-wiring.sh`
4. 重启 OpenClaw gateway
5. 只保留一台机器作为 Telegram / OpenClaw 的活跃入口

## 当前约定

- repo-owned source of truth:
  - `openclaw/extensions/reel-agent-bridge`
- local runtime mount:
  - `~/.openclaw/extensions/reel-agent-bridge`
- backend callback contract:
  - `POST $OPENCLAW_CALLBACK_BASE_URL/events`
- workspace state mirror:
  - `~/.openclaw/workspace-realtor-social/.openclaw/reel-agent-bridge-state.json`
