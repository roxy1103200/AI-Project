"""Launch local memory services with explicit paths and dotenv configuration."""

# 导入当前步骤使用的模块或类型。
# isort: off
import argparse
# 导入当前步骤使用的模块或类型。
import asyncio
# 导入当前步骤使用的模块或类型。
import os
# 导入当前步骤使用的模块或类型。
import subprocess
# 导入当前步骤使用的模块或类型。
import sys
# 导入当前步骤使用的模块或类型。
from pathlib import Path

# 导入当前步骤使用的模块或类型。
from dotenv import load_dotenv
# isort: on


# 定义函数 `main`：Start the persistent loopback server or private index worker.
def main() -> None:
    """Start the persistent loopback server or private index worker."""
    # 为 `parser` 保存当前步骤所需的值。
    parser = argparse.ArgumentParser()
    # 执行当前步骤中的业务处理表达式。
    parser.add_argument("--service", choices=["chroma", "memory"], required=True)
    # 执行当前步骤中的业务处理表达式。
    parser.add_argument("--project-root", type=Path, required=True)
    # 为 `args` 保存当前步骤所需的值。
    args = parser.parse_args()
    # 为 `root` 保存当前步骤所需的值。
    root = args.project_root.resolve()
    # 执行当前步骤中的业务处理表达式。
    load_dotenv(root / "cinema-ai" / ".env")
    # 执行当前步骤中的业务处理表达式。
    os.environ.setdefault("MEMORY_MODEL_PATH", str(root / "data" / "models" / "bge-small-zh-v1.5"))
    # 检查 `if args.service == "chroma"`，据此选择当前处理分支。
    if args.service == "chroma":
        # 执行当前步骤中的业务处理表达式。
        subprocess.run(
            # 执行当前步骤中的业务处理表达式。
            [
                # 补充当前表达式的 `str(Path(sys.executable).with_name("chroma.e` 参数或元素。
                str(Path(sys.executable).with_name("chroma.exe")),
                # 补充当前表达式的 `"run"` 参数或元素。
                "run",
                # 补充当前表达式的 `"--path"` 参数或元素。
                "--path",
                # 补充当前表达式的 `str(root / "data" / "chroma")` 参数或元素。
                str(root / "data" / "chroma"),
                # 补充当前表达式的 `"--host"` 参数或元素。
                "--host",
                # 补充当前表达式的 `"127.0.0.1"` 参数或元素。
                "127.0.0.1",
                # 补充当前表达式的 `"--port"` 参数或元素。
                "--port",
                # 补充当前表达式的 `os.getenv("CHROMA_PORT", "8030")` 参数或元素。
                os.getenv("CHROMA_PORT", "8030"),
            ],
            # 为 `check` 保存当前步骤所需的值。
            check=True,
        )
    # 进入对应的循环、异常处理或资源管理分支。
    else:
        # 导入当前步骤使用的模块或类型。
        from app.memory_worker import run

        # 执行当前步骤中的业务处理表达式。
        asyncio.run(run())


# 检查 `if __name__ == "__main__"`，据此选择当前处理分支。
if __name__ == "__main__":
    # 执行当前步骤中的业务处理表达式。
    main()
