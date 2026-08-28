"""`python3 -m yayg` 로 실행할 수 있게 한다 (패키지 설치본이 쓰는 경로)."""

import sys

from .app import main

if __name__ == "__main__":
    sys.exit(main())
