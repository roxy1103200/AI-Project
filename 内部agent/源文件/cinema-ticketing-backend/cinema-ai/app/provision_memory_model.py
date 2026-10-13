"""Download the fixed embedding model before starting memory services."""

# 导入当前步骤使用的模块或类型。
# isort: off
import os

# 导入当前步骤使用的模块或类型。
from dotenv import load_dotenv
# 导入当前步骤使用的模块或类型。
from sentence_transformers import SentenceTransformer

# 导入当前步骤使用的模块或类型。
from app.memory import MODEL, MODEL_REVISION
# isort: on

# 检查 `if __name__ == "__main__"`，据此选择当前处理分支。
if __name__ == "__main__":
    # 执行当前步骤中的业务处理表达式。
    load_dotenv(".env")
    # 为 `target` 保存当前步骤所需的值。
    target = os.getenv("MEMORY_MODEL_PATH", "../data/models/bge-small-zh-v1.5")
    # 执行当前步骤中的业务处理表达式。
    SentenceTransformer(MODEL, revision=MODEL_REVISION, device="cpu").save(target)
    # 执行当前步骤中的业务处理表达式。
    print(f"Memory embedding model saved to {target}")
