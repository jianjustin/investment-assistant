# 项目约定

- **主干开发为主。** 默认直接在 `main` 上开发、测试和提交，不另开分支或 worktree。只有用户明确要求隔离时才用分支或 worktree，完成后快进合并回 `main`，并删除该分支和 worktree。
- **文档位置。** 设计 spec 放 `docs/specs/YYYY-MM-DD-<topic>-design.md`，实施 plan 放 `docs/plans/YYYY-MM-DD-<topic>.md`，写成后只增不改；功能、架构与运维文档随代码同一个提交更新。分类与维护规则见 `docs/README.md`。
