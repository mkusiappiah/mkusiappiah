#!/bin/bash
# Show the profile card whenever a terminal opens: Terminal, iTerm2, VS Code, Termius's local terminal, any terminal on this Mac.
#   bash terminal/install.sh                 add it to ~/.bashrc and ~/.zshrc (each changed file is backed up first)
#   bash terminal/install.sh --remove        take it out again
#   bash terminal/install.sh --ssh user@host also show it in SSH sessions to that server (Termius, ssh): copies a self-contained
#                                            card to ~/.local/bin/profile-card there and adds the same hook to its ~/.bashrc
# The hook runs only in an interactive terminal (never in scripts, tools or `ssh host command`), once per terminal window: a shell
# started inside that window does not show it again. PROFILE_CARD=off silences it.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
CARD="$HERE/card.py"
START='# >>> profile card >>>'
END='# <<< profile card <<<'

python_for_card() {   # the first Python 3.8+ that runs, by its full path, so a conda environment or PATH change cannot break the hook
  for candidate in /Library/Frameworks/Python.framework/Versions/3.1[0-9]/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 \
                   "$(command -v python3 || true)" /usr/bin/python3; do
    [ -n "$candidate" ] && [ -x "$candidate" ] && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 8))' 2>/dev/null \
      && { echo "$candidate"; return; }
  done
  echo "No working Python 3.8 or newer was found" >&2; exit 1
}

hook() {   # $1: bash or zsh, $2: the command that prints the card
  local interactive='[ -n "$PS1" ]'
  [ "$1" = zsh ] && interactive='[[ -o interactive ]]'
  cat <<EOF
$START  (from github.com/mkusiappiah/mkusiappiah; remove with: bash terminal/install.sh --remove)
if $interactive && [ -t 0 ] && [ -t 1 ] && [ "\${TERM:-dumb}" != dumb ] && [ -z "\${CLAUDECODE:-}" ] && [ -z "\${VSCODE_RESOLVING_ENVIRONMENT:-}" ]; then
  __card_tty="\$(tty 2>/dev/null)"
  if [ "\${PROFILE_CARD_TTY:-}" != "\$__card_tty" ]; then   # once per terminal window, not again in a shell started inside it
    export PROFILE_CARD_TTY="\$__card_tty"
    $2 2>/dev/null
  fi
  unset __card_tty
fi
$END
EOF
}

strip() {   # the file without its profile card block
  awk -v start="$START" -v end="$END" 'index($0, start) == 1 { skip = 1 } !skip { print } index($0, end) == 1 { skip = 0 }' "$1"
}

place() {   # $1: rc file, $2: shell
  local file="$1" body
  [ -f "$file" ] || touch "$file"
  cp -p "$file" "$file.before-profile-card"
  body="$(strip "$file")"
  if [ "${REMOVE:-}" = 1 ]; then
    printf '%s\n' "$body" > "$file"; echo "removed from $file (backup: $file.before-profile-card)"
  else
    printf '%s\n\n%s\n' "$body" "$(hook "$2" "\"$PYTHON\" \"$CARD\"")" > "$file"; echo "added to $file (backup: $file.before-profile-card)"
  fi
}

case "${1:-}" in
  --remove)
    REMOVE=1 place "$HOME/.bashrc" bash; REMOVE=1 place "$HOME/.zshrc" zsh ;;
  --ssh)
    target="${2:?usage: install.sh --ssh user@host}"
    PYTHON="$(python_for_card)"
    "$PYTHON" "$CARD" --bundle | ssh "$target" 'mkdir -p ~/.local/bin && cat > ~/.local/bin/profile-card && chmod 755 ~/.local/bin/profile-card && command -v python3 >/dev/null'
    hook bash 'python3 "$HOME/.local/bin/profile-card"' | ssh "$target" "f=~/.bashrc; [ -f \$f ] || touch \$f; cp -p \$f \$f.before-profile-card; \
      awk -v start='$START' -v end='$END' 'index(\$0, start) == 1 { skip = 1 } !skip { print } index(\$0, end) == 1 { skip = 0 }' \$f > \$f.tmp; \
      { cat \$f.tmp; echo; cat; } > \$f; rm -f \$f.tmp"
    echo "installed on $target: it shows in new interactive SSH sessions (remove its block from ~/.bashrc there to undo)" ;;
  "")
    PYTHON="$(python_for_card)"
    place "$HOME/.bashrc" bash; place "$HOME/.zshrc" zsh
    mkdir -p "${XDG_CACHE_HOME:-$HOME/.cache}/profile-card"
    curl -fsS -m 10 -o "${XDG_CACHE_HOME:-$HOME/.cache}/profile-card/stats.json" \
      https://raw.githubusercontent.com/mkusiappiah/mkusiappiah/main/stats.json 2>/dev/null || echo "(the stats arrive with the first terminal)"
    echo "done: open a new terminal window to see it (Python: $PYTHON)" ;;
  *) echo "usage: install.sh [--remove | --ssh user@host]" >&2; exit 2 ;;
esac
