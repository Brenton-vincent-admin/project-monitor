#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

if ! command -v python3 >/dev/null; then
  echo "Python is required. On Omarchy: omarchy pkg add python"
  exit 1
fi
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else "Python 3.11 or newer is required")'

if command -v uv >/dev/null; then
  if [[ ! -x .venv/bin/python ]]; then uv venv .venv; fi
  uv pip install --python .venv/bin/python -r requirements.txt
else
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements.txt
fi

.venv/bin/python - <<'PY'
import os
from pathlib import Path

project = Path.cwd()
applications = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share') / 'applications'
applications.mkdir(parents=True, exist_ok=True)

def exec_quote(path):
    value = str(path).replace('%', '%%')
    for character in ('\\', '"', '`', '$'):
        value = value.replace(character, '\\' + character)
    return '"' + value + '"'

entry = '\n'.join([
    '[Desktop Entry]', 'Type=Application', 'Name=Project Monitor',
    'Comment=Codex account usage and session monitor',
    'Exec=' + exec_quote(project / 'run.sh'),
    'Icon=' + str(project / 'icon.svg'),
    'Terminal=false', 'Categories=Development;Utility;', '',
])
(applications / 'project-monitor.desktop').write_text(entry)
print('Installed the Project Monitor app launcher.')
PY

for program in codex curl wtype hyprctl; do
  if ! command -v "$program" >/dev/null; then
    echo "Missing optional runtime tool: $program (see README for setup)."
  fi
done
echo "Open Project Monitor from your app launcher, or run ./run.sh"
