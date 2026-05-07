from __future__ import annotations

import os
import sys
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[2]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

# Dev/test-only fallback; production remains strict by default.
os.environ.setdefault("ALLOW_SQLGLOT_FALLBACK", "true")
# Satisfy query-service startup check when pytest loads Django settings.
os.environ.setdefault("INTERNAL_SERVICE_TOKEN", "pytest-query-service-internal-token-32chars")
