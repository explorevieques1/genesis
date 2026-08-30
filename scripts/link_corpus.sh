#!/usr/bin/env bash
# Recreate the corpus symlink. Run after plugging the external SSD back in, or
# on a new machine where the drive mounts somewhere else.
#
#   bash scripts/link_corpus.sh                 # default location
#   bash scripts/link_corpus.sh /path/to/repos  # override
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT="/run/media/${USER}/Extreme SSD/Github Repos/Trading"
TARGET="${1:-$DEFAULT}"

if [ ! -d "$TARGET" ]; then
  echo "✗ not found: $TARGET" >&2
  echo >&2
  echo "  The external SSD is probably unplugged, or udisks mounted it elsewhere." >&2
  echo "  Plug it in and open the drive once in your file manager, then re-run." >&2
  echo "  Currently mounted removable volumes:" >&2
  ls -1 "/run/media/${USER}" 2>/dev/null | sed 's/^/    /' >&2 || echo "    (none)" >&2
  exit 1
fi

ln -sfn "$TARGET" "$ROOT/corpus"
echo "✓ corpus -> $TARGET"
exec python3 "$ROOT/scripts/check_corpus.py"
