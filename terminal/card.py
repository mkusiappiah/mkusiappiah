#!/usr/bin/env python3
"""The profile card in a terminal: the ASCII portrait, what I work with, how to reach me and my GitHub stats.

  python3 terminal/card.py              print it (only in an interactive terminal; --force prints anywhere)
  python3 terminal/card.py --theme dark force the dark or light portrait (normally the terminal's background is asked for)
  python3 terminal/card.py --bundle     print a self-contained copy with the portrait and details built in, for servers

In terminals that show pictures (iTerm2, WezTerm, VS Code with images on) it is the GitHub card itself, as the image the profile
repository publishes daily. Elsewhere it is text: the portrait is the GitHub card's own (art/dark.txt and art/light.txt, 100 x 68 characters) when the window has room for it beside
the details; otherwise the same picture made smaller by tools/ascii_portrait.py (terminal/art/, same photo, crop and method): the
largest that fits the window's width and height, so the top of the head never scrolls away. A narrow window gets a shorter list of
details beside it, a narrower one the details alone, and below 40 columns nothing. The stats come from a local copy of the
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
FILES = 'https://raw.githubusercontent.com/mkusiappiah/mkusiappiah/main/'
DOWNLOADS = ('stats.json', 'dark_mode.png', 'light_mode.png')       # the GitHub card's numbers, and the card itself as images
CACHE = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'profile-card'
WIDTH = 60
COLOURS = {   # 256-colour codes, close to the GitHub card's (the portrait in the card's text colour, as on GitHub)
    'dark': {'key': 215, 'value': 153, 'dots': 240, 'add': 71, 'del': 203, 'art': 252},
    'light': {'key': 130, 'value': 25, 'dots': 250, 'add': 28, 'del': 160, 'art': 236},
}


# ------------------------------------------------------------------------------------------------ what to show
def load():
    """Profile text and portraits (largest first): from the bundle, or from the profile repository this file lives in."""
    if DATA is not None:
        return DATA
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    import profile as card_source                      # the GitHub card's own PROFILE: one place to edit both cards
    sys.path.pop(0)
    art = {}
    for mode in ('dark', 'light'):
        sizes = [(root / 'art' / f'{mode}.txt').read_text()]                     # the GitHub card's own portrait first
        sizes += [path.read_text() for path in sorted((root / 'terminal' / 'art').glob(f'{mode}-*.txt'),
                                                       key=lambda path: -int(path.stem.split('-')[1].split('x')[0]))]
        art[mode] = [trim(text) for text in sizes]
    profile = card_source.PROFILE
    return {'handle': profile['handle'], 'since': profile['uptime_since'].isoformat(), 'info': profile['info'],
            'contact': profile['contact'], 'art': art}


def refresh():
    """Fetch the GitHub card's numbers and images in the background when they are older than 12 hours (or missing): a terminal
    never waits for the network, and the next one shows what was fetched."""
    stamp = CACHE / 'stats.json'
    fresh = stamp.exists() and time.time() - stamp.stat().st_mtime < 12 * 3600
    lock = CACHE / '.fetching'
    if fresh or (lock.exists() and time.time() - lock.stat().st_mtime < 120) or not shutil.which('curl'):
        return
    CACHE.mkdir(parents=True, exist_ok=True)
    steps = [f'touch "{lock}"'] + [f'curl -fsS -m 20 -o "{CACHE / name}.part" "{FILES}{name}" && mv "{CACHE / name}.part" "{CACHE / name}"'
                                   for name in DOWNLOADS] + [f'rm -f "{lock}" "{CACHE}"/*.part']
    subprocess.Popen(['/bin/sh', '-c', '; '.join(steps)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def stats():
    """The cached numbers of the GitHub card (refresh() keeps them current)."""
    refresh()
    try:
        return json.loads((CACHE / 'stats.json').read_text())
    except (OSError, ValueError):
        return None


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
    """Ask the terminal for its background colour (OSC 11); PROFILE_CARD_THEME=dark or light overrides it."""
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
    # No answer: Apple's Terminal follows the macOS appearance; most other terminals (iTerm2, VS Code, Termius) default to dark.
    if sys.platform == 'darwin' and os.environ.get('TERM_PROGRAM') == 'Apple_Terminal':
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


def trim(text):
    """The portrait's lines without the blank rows above the head and below the picture."""
    lines = text.rstrip('\n').split('\n')
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def render(columns, rows, theme, colour=True):
    data, numbers = load(), stats()
    full, room = details(data, numbers), rows - 1                     # a line is left for the prompt
    # the largest portrait that fits beside the full details, else beside the short ones; then the details alone
    for lines in data['art'][theme]:
        width = max(len(line) for line in lines)
        if len(lines) <= room and width + 3 + WIDTH <= columns:
            right, gap = full, 3
            break
        if len(lines) <= room and width + 2 + 34 <= columns and width >= 44:
            right, gap = short_details(data, numbers, columns - width - 3), 2
            break
    else:
        body = full if columns >= WIDTH else short_details(data, numbers, columns - 1) if columns >= 40 else []
        return ''.join(paint(line, theme, colour) + '\n' for line in body)
    top = max(0, (len(lines) - len(right)) // 2)                      # the details sit level with the middle of the portrait
    tint = (lambda text: f'\033[38;5;{COLOURS[theme]["art"]}m{text}\033[0m') if colour else (lambda text: text)
    out = []
    for row in range(max(len(lines), top + len(right))):
        left = lines[row].ljust(width) if row < len(lines) else ' ' * width
        runs = right[row - top] if 0 <= row - top < len(right) else []
        out.append((tint(left) + ' ' * gap + paint(runs, theme, colour)).rstrip())
    return '\n'.join(out) + '\n'


def shows_images():
    """Terminals that show pictures inline (the iTerm2 image protocol): iTerm2, WezTerm, and VS Code once its
    terminal.integrated.enableImages setting is on. PROFILE_CARD_IMAGES=on or off decides instead."""
    choice = os.environ.get('PROFILE_CARD_IMAGES', '').lower()
    if choice in ('on', '1', 'off', '0'):
        return choice in ('on', '1')
    program = os.environ.get('TERM_PROGRAM', '')
    if program in ('iTerm.app', 'WezTerm'):
        return True
    if program == 'vscode':
        settings = Path.home() / 'Library' / 'Application Support' / 'Code' / 'User' / 'settings.json'
        try:
            return re.search(r'^[^/\n]*"terminal\.integrated\.enableImages"\s*:\s*true', settings.read_text(), re.M) is not None
        except OSError:
            return False
    return False


def picture(columns, rows, theme):
    """The GitHub card itself, as an inline image as wide as fits (terminal cells are about twice as tall as wide), or None."""
    path = CACHE / f'{theme}_mode.png'
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        return None
    width, height = int.from_bytes(data[16:20], 'big'), int.from_bytes(data[20:24], 'big')
    cells = min(columns - 1, 150, int((rows - 2) * 2.0 * width / max(1, height)))      # its height, in rows, fits the window
    if cells < 40:
        return None
    import base64
    name = base64.b64encode(b'profile-card.png').decode()
    return f'\033]1337;File=name={name};size={len(data)};inline=1;width={cells};preserveAspectRatio=1:{base64.b64encode(data).decode()}\a\n'


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
    size = shutil.get_terminal_size((100, 30))
    image = picture(size.columns, size.lines, theme) if colour and shows_images() else None
    if image:
        refresh()
        sys.stdout.write(image)
    else:
        sys.stdout.write(render(size.columns, size.lines, theme, colour))


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except Exception:          # a terminal must always open, whatever happens here
        pass
