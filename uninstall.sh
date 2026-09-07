#!/bin/bash
set -euo pipefail
SOURCE_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec /usr/bin/python "$SOURCE_DIR/scripts/user-install.py" --remove "$@"
