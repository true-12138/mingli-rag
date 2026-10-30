"""根目录入口：ModelScope 默认查找 app.py，`streamlit run app.py` 也走这里。

真正的界面在 src/app.py，这里只负责把它接起来。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.app import main

if __name__ == "__main__":
    main()
