"""Remove generated test JSON/screenshots; retain Markdown and application inputs."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {".git", ".venv", "node_modules", "__pycache__"}
IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def artifacts() -> list[Path]:
    found: list[Path] = []
    for folder in (ROOT / "docs/verification", ROOT / "output"):
        if not folder.exists() or folder.is_symlink():
            continue
        folder.resolve().relative_to(ROOT)
        for base, dirs, files in os.walk(folder, followlinks=False):
            dirs[:] = [
                name for name in dirs
                if name not in EXCLUDED and not (Path(base) / name).is_symlink()
            ]
            for name in files:
                path = Path(base) / name
                if path.is_symlink() or path.suffix.lower() not in IMAGES | {".json"}:
                    continue
                relative = path.relative_to(folder)
                # These are application inputs copied into installation test workspaces.
                if folder.name == "output" and relative.parts[0].startswith("clean-install-"):
                    if len(relative.parts) > 1 and relative.parts[1] in {"backend", "frontend", "shared"}:
                        continue
                path.resolve().relative_to(folder.resolve())
                path.resolve().relative_to(ROOT)
                found.append(path)
    return sorted(found)


def historical_summary(paths: list[Path]) -> None:
    reports = [p for p in paths if p.suffix.lower() == ".json" and p.is_relative_to(ROOT / "docs/verification")]
    target = ROOT / "docs/verification/历史测试报告摘要.md"
    if not reports or target.exists():
        return
    lines = [
        "# 历史测试报告摘要", "",
        "2026-10-08 按用户要求清理原始测试 JSON 和截图前，静态提取旧报告的顶层结果字段。",
        "本次没有运行测试；本表不是新增通过证明，不改变正式验收状态。专题 Markdown 继续保留。",
        "仅摘录布尔值和退出码；没有统一结果字段、媒体清单或解析失败均不推断为通过。", "",
        "| 原报告路径（相对本目录，文件已删除） | 当时记录的顶层字段 |",
        "| --- | --- |",
    ]
    for path in reports:
        values = []
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                for key in ("passed", "command_passed", "success", "ok", "exit_code", "returncode", "tests_run"):
                    value = data.get(key)
                    if isinstance(value, (bool, int)):
                        values.append(f"{key}={value}")
            result = "; ".join(values) or "无统一结果字段；不推断结果"
        except (ValueError, OSError, UnicodeError):
            result = "旧报告无法解析；不推断结果"
        lines.append(f"| `{path.relative_to(ROOT / 'docs/verification').as_posix()}` | {result} |")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    paths = artifacts()
    counts = Counter("JSON" if p.suffix.lower() == ".json" else "screenshots" for p in paths)
    print(f"{'Would remove' if args.dry_run else 'Removing'}: JSON={counts['JSON']}, screenshots={counts['screenshots']}")
    if args.dry_run:
        return
    historical_summary(paths)
    for path in paths:
        # Revalidate immediately before each deletion; never follow external links.
        if path.is_symlink():
            raise ValueError(f"Refusing symbolic link: {path}")
        path.resolve(strict=True).relative_to(ROOT)
        path.unlink()
    print("Cleanup complete. Markdown records and application inputs retained.")


if __name__ == "__main__":
    main()
