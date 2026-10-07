#!/usr/bin/env python3
"""The profile card in a terminal: the ASCII portrait, what I work with, how to reach me and my GitHub stats.

  python3 terminal/card.py              print it (only in an interactive terminal; --force prints anywhere)
  python3 terminal/card.py --theme dark force the dark or light portrait (normally the terminal's background is asked for)
  python3 terminal/card.py --bundle     print a self-contained copy with the portrait and details built in, for servers

Fits itself to the window: portrait and details side by side when there is room, a shorter list of details beside the portrait in
a narrower window, the details alone in a narrow one, and nothing below 40 columns. The stats come from a local copy of the
profile repository's stats.json, refreshed in the background at most every 12 hours, so opening a terminal never waits for the
network. Standard library only; works with any Python 3.8 or newer. Set PROFILE_CARD=off to silence it.
"""
from __future__ import annotations

import json
import os
import re
import select
import shutil
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

DATA = None        # filled in by --bundle: everything the card needs, so the copy runs on its own
STATS_URL = 'https://raw.githubusercontent.com/mkusiappiah/mkusiappiah/main/stats.json'
CACHE = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'profile-card'
WIDTH = 60
COLOURS = {   # 256-colour codes, close to the GitHub card's
    'dark': {'key': 215, 'value': 153, 'dots': 240, 'add': 71, 'del': 203, 'art': (238, 255)},
    'light': {'key': 130, 'value': 25, 'dots': 250, 'add': 28, 'del': 160, 'art': (232, 246)},
}


# ------------------------------------------------------------------------------------------------ what to show
def load():
    """Profile text, portraits and shades: from the bundle, or from the profile repository this file lives in."""
    if DATA is not None:
        return DATA
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    import profile as card_source                      # the GitHub card's own PROFILE: one place to edit both cards
    sys.path.pop(0)
    here = Path(__file__).resolve().parent
    art = {mode: {'lines': (here / f'art-{mode}.txt').read_text().rstrip('\n').split('\n'),
                  'shades': (here / f'art-{mode}.shade').read_text().rstrip('\n').split('\n')} for mode in ('dark', 'light')}
    profile = card_source.PROFILE
    return {'handle': profile['handle'], 'since': profile['uptime_since'].isoformat(), 'info': profile['info'],
            'contact': profile['contact'], 'art': art}


def stats():
    """The cached stats, refreshed in the background when older than 12 hours (or missing)."""
    path = CACHE / 'stats.json'
    try:
        found = json.loads(path.read_text())
        fresh = time.time() - path.stat().st_mtime < 12 * 3600
    except (OSError, ValueError):
        found, fresh = None, False
    pending = CACHE / 'stats.json.part'
    if not fresh and not (pending.exists() and time.time() - pending.stat().st_mtime < 120) and shutil.which('curl'):
        CACHE.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(['/bin/sh', '-c', f'curl -fsS -m 10 -o "{pending}" "{STATS_URL}" && mv "{pending}" "{path}" || rm -f "{pending}"'],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return found


def uptime(since):
    today, since = date.today(), date.fromisoformat(since)
    years, months, days = today.year - since.year, today.month - since.month, today.day - since.day
    if days < 0:
        months -= 1
        days += (date(today.year, today.month, 1) - date.resolution).day
    if months < 0:
        years, months = years - 1, months + 12
    plural = lambda n, word: f"{n} {word}{'' if n == 1 else 's'}"
    return f"{plural(years, 'year')}, {plural(months, 'month')}, {plural(days, 'day')}"


# ------------------------------------------------------------------------------------------------ the details, as coloured runs
def keyed(key, value, width):
    """'. Key.Sub: ..... value' exactly ``width`` characters long, as [(text, colour)]."""
    parts = [('. ', 'dots')]
    for index, piece in enumerate(key.split('.')):
        parts += [(piece, 'key'), ('.' if index < key.count('.') else ':', None)]
    used = sum(len(text) for text, _ in parts) + len(value) + 2
    return parts + [(' ' + '.' * max(1, width - used) + ' ', 'dots'), (value, 'value')]


def details(data, numbers, width=WIDTH):
    rule = lambda title: [(title, None), (' ' + '─' * max(0, width - len(title) - 1), None)]
    lines = [rule(data['handle'])]
    for item in data['info']:
        if item is None:
            lines.append([('. ', 'dots')])
        else:
            lines.append(keyed(item[0], item[1].replace('{uptime}', uptime(data['since'])), width))
    lines += [[], rule('- Contact')] + [keyed(key, value, width) for key, value in data['contact']]
    lines += [[], rule('- GitHub Stats')]
    if numbers:
        n = lambda key: f'{numbers[key]:,}'
        # two stats to a line: the left one 36 characters, ' | ', then the right one without its leading '. '
        pair = lambda a, b: keyed(*a, 36) + [(' | ', None)] + keyed(*b, width - 37)[1:]
        lines += [pair(('Repos', f"{n('repos')} {{Contributed: {n('contributed')}}}"), ('Stars', n('stars'))),
                  pair(('Commits', n('commits')), ('Followers', n('followers'))),
                  keyed('Lines of Code', f"{numbers['added'] - numbers['deleted']:,}", width - 11 - len(n('added')) - len(n('deleted')))
                  + [(' ( ', 'value'), (f"{n('added')}++", 'add'), (', ', 'value'), (f"{n('deleted')}--", 'del'), (' )', 'value')]]
    else:
        lines.append([('. ', 'dots'), ('The stats arrive with the next terminal (they are being fetched).', None)])
    return lines


def short_details(data, numbers, width):
    """For narrower windows: the most telling lines as 'Key: value', cut to fit."""
    pick = {'OS', 'Uptime', 'Kernel', 'Languages.Programming'}
    rows = [(key.split('.')[-1] if key != 'Kernel' else 'Focus', value.replace('{uptime}', uptime(data['since'])))
            for key, value in (item for item in data['info'] if item) if key in pick]
    rows += [item for item in data['contact'] if item[0] in ('Email', 'GitHub')]
    if numbers:
        rows += [('GitHub', f"{numbers['repos']} repos, {numbers['commits']:,} commits, {numbers['stars']} stars")]
    cut = lambda text, room: text if len(text) <= room else text[:max(1, room - 1)] + '…'
    lines = [[(cut(data['handle'], width), None)], [('─' * min(width, len(data['handle']) + 4), None)]]
    for key, value in rows:
        lines.append([(key, 'key'), (': ', None), (cut(value, width - len(key) - 2), 'value')])
    return lines


# ------------------------------------------------------------------------------------------------ drawing
def background_is_dark():
    """Ask the terminal for its background colour (OSC 11); without an answer, follow macOS's appearance; else assume dark."""
    choice = os.environ.get('PROFILE_CARD_THEME', '').lower()
    if choice in ('dark', 'light'):
        return choice == 'dark'
    try:
        import termios
        fd = os.open('/dev/tty', os.O_RDWR | os.O_NOCTTY)
        try:
            saved = termios.tcgetattr(fd)
            quiet = termios.tcgetattr(fd)
            quiet[3] &= ~(termios.ICANON | termios.ECHO)
            termios.tcsetattr(fd, termios.TCSANOW, quiet)
            os.write(fd, b'\033]11;?\007')
            answer, end = b'', time.monotonic() + 0.2
            while time.monotonic() < end and not (answer.endswith(b'\007') or answer.endswith(b'\033\\')):
                ready, _, _ = select.select([fd], [], [], max(0, end - time.monotonic()))
                if not ready:
                    break
                answer += os.read(fd, 64)
            termios.tcflush(fd, termios.TCIFLUSH)                 # a late answer must not reach the prompt
            termios.tcsetattr(fd, termios.TCSANOW, saved)
        finally:
            os.close(fd)
        found = re.search(rb'rgb:([0-9a-fA-F]+)/([0-9a-fA-F]+)/([0-9a-fA-F]+)', answer)
        if found:
            r, g, b = (int(x, 16) / (16 ** len(x) - 1) for x in found.groups())
            return 0.2126 * r + 0.7152 * g + 0.0722 * b < 0.5
    except (OSError, ImportError, ValueError):
        pass
    if sys.platform == 'darwin':
        try:
            return subprocess.run(['defaults', 'read', '-g', 'AppleInterfaceStyle'], capture_output=True, text=True, timeout=1).stdout.strip() == 'Dark'
        except (OSError, subprocess.SubprocessError):
            pass
    return True


def paint(runs, theme, colour):
    if not colour:
        return ''.join(text for text, _ in runs)
    out = ''
    for text, kind in runs:
        out += f'\033[38;5;{COLOURS[theme][kind]}m{text}\033[0m' if kind else text
    return out


def portrait_line(text, shades, theme, colour):
    if not colour:
        return text
    low, high = COLOURS[theme]['art']
    out, current = '', None
    for char, shade in zip(text, shades.ljust(len(text))):
        tint = None if shade == ' ' else low + (ord(shade) - ord('a')) * (high - low) // 23
        if tint != current:
            out += '\033[0m' if tint is None else f'\033[38;5;{tint}m'
            current = tint
        out += char
    return out + '\033[0m'


def render(columns, theme, colour=True):
    data, numbers = load(), stats()
    art = data['art'][theme]
    art_width = max(len(line) for line in art['lines'])
    if columns >= art_width + 3 + WIDTH:
        right, gap = details(data, numbers), 3
    elif columns >= art_width + 2 + 30:
        right, gap = short_details(data, numbers, columns - art_width - 3), 2
    elif columns >= WIDTH:
        return '\n'.join(paint(line, theme, colour) for line in details(data, numbers)) + '\n'
    elif columns >= 40:
        return '\n'.join(paint(line, theme, colour) for line in short_details(data, numbers, columns - 1)) + '\n'
    else:
        return ''
    top = max(0, (len(art['lines']) - len(right)) // 2)         # the details sit level with the middle of the portrait
    out = []
    for row in range(max(len(art['lines']), top + len(right))):
        left = portrait_line(art['lines'][row], art['shades'][row], theme, colour) if row < len(art['lines']) else ' ' * art_width
        runs = right[row - top] if 0 <= row - top < len(right) else []
        out.append(left + ' ' * gap + paint(runs, theme, colour))
    return '\n'.join(line.rstrip() for line in out) + '\n'


def bundle():
    data = load()
    source = Path(__file__).read_text()
    return source.replace('DATA = None ', f'DATA = {json.dumps(data, ensure_ascii=False)} ', 1)


def main(argv):
    if '--bundle' in argv:
        sys.stdout.write(bundle())
        return
    if os.environ.get('PROFILE_CARD', '').lower() == 'off':
        return
    if '--force' not in argv and not (sys.stdout.isatty() and sys.stdin.isatty()):
        return
    theme = next((argv[i + 1] for i, arg in enumerate(argv[:-1]) if arg == '--theme'), None) or ('dark' if background_is_dark() else 'light')
    colour = 'NO_COLOR' not in os.environ and os.environ.get('TERM') != 'dumb'
    sys.stdout.write(render(shutil.get_terminal_size((100, 30)).columns, theme, colour))


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except Exception:          # a terminal must always open, whatever happens here
        pass
