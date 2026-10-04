"""支持 `python -m skillverify`（等价于 `python -m skillverify.cli`）。"""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
