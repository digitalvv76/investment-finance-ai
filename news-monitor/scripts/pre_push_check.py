#!/usr/bin/env python3
"""Pre-push check — triggered on 'git push'. Protects v1-stable from direct pushes.

Always warns for v1-stable pushes; blocks unless ALLOW_V1_PUSH=1 is set.
"""

import os
import sys


def main() -> int:
    args = os.environ.get("ARGUMENTS", "")

    # Only care about push operations
    if "push" not in args.lower():
        return 0

    # Check if pushing to v1-stable directly (not from a fix/ branch)
    branch = os.environ.get("GIT_BRANCH", "")
    if "v1-stable" not in args:
        return 0

    print()
    print("=" * 50)
    print("  ⛔ v1-stable 保护")
    print("=" * 50)
    print()
    print("  不允许直接推送到 v1-stable 分支。")
    print("  V1 生产修复流程:")
    print("    1. git checkout v1-stable")
    print("    2. git checkout -b fix/<description>")
    print("    3. 在 fix 分支上修改 + 提交")
    print("    4. git push origin fix/<description>")
    print("    5. 创建 PR 合入 v1-stable")
    print()
    print("  紧急绕过: export ALLOW_V1_PUSH=1")

    if os.environ.get("ALLOW_V1_PUSH") == "1":
        print()
        print("  ⚠️  ALLOW_V1_PUSH=1 — 已绕过保护")
        print()
        return 0

    print()
    return 1


if __name__ == "__main__":
    sys.exit(main())
