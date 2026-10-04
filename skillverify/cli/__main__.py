"""支持 `python -m skillverify.cli`（免安装直接跑 repo 的入口，git hook 也用它）。"""

import sys

from . import main

if __name__ == "__main__":
    sys.exit(main())
