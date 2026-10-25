# scripts/

| 脚本 | 用途 | 运行 |
|------|------|------|
| `start_local.py` | 本机服务入口：读取仓库 `.env`，只监听 `127.0.0.1`；由根目录 `start.command` 调用，本机 LaunchAgent 登录时启动它 | `./start.command` |
| `verify_cross_market.py` | 美股研究数据的只读验收：只读事务 + HTTP GET，不采集、不迁移、不通知 | `.venv/bin/python scripts/verify_cross_market.py --help` |

本机服务的启动、重启与日志见 [docs/operations/local-service.md](../docs/operations/local-service.md)。
