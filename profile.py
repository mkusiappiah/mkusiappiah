"""Builds the profile card (dark_mode.svg and light_mode.svg): a neofetch-style card with an ASCII portrait and live GitHub stats.

Run by .github/workflows/update.yml every day; locally: GITHUB_TOKEN=<token> python profile.py
Standard library only. Edit PROFILE below to change what the card says; tools/ascii_portrait.py remakes the portrait.

Stats (from GitHub's GraphQL API):
  repos         repositories you own;  contributed: those you own, collaborate on or reach through an organisation
  stars         stars on the repositories you own
  followers     people following you
  commits       commit contributions over every year since the account was created
  lines of code additions and deletions of your own commits on each repository's default branch (cached in cache/loc.json,
                so a repository is read again only when its commit count changes)
Only public repositories count, unless INCLUDE_PRIVATE=1 and the token may read private ones (a fine-grained token in the
STATS_TOKEN secret). The workflow's own token sees public data, which is all the card needs.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent
USER = os.environ.get('USER_NAME', 'mkusiappiah')

# ------------------------------------------------------------------------------------------------ what the card says
PROFILE = {
    'handle': 'michael@kusi-appiah',
    'uptime_since': date(2019, 8, 29),        # the reference counts from a birthday; until one is set, the day this account began
    'info': [
        ('OS', 'macOS, Linux, Windows'),
        ('Uptime', '{uptime}'),
        ('Host', 'Independent'),
        ('Kernel', 'Machine learning & fraud analytics'),
        ('IDE', 'VS Code, Jupyter, RStudio'),
        None,
        ('Languages.Programming', 'Python, R, TypeScript, SQL'),
        ('Languages.Computer', 'HTML, CSS, JSON, YAML, Markdown'),
        ('Languages.Real', 'English'),
        None,
        ('Hobbies.Software', 'Reinforcement learning, LLMs'),
        ('Hobbies.Hardware', 'Homelab: Proxmox, Kubernetes'),
    ],
    'contact': [
        ('Email', 'appiah.michael@yahoo.com'),
        ('GitHub', 'mkusiappiah'),
        ('Website', 'mkusiappiah.github.io/replayx'),
    ],
}
# The portrait: 100 x 68 characters in a small font (tools/ascii_portrait.py), each line stretched to ART_WIDTH pixels so it keeps its
# shape in any monospace font. Line height / font size is 1.2, as the converter assumes.
ART_FONT, ART_LINE, ART_WIDTH, ART_TOP = 6.25, 7.5, 365, 16
WIDTH = 60                    # characters in every line of the right-hand column
COLUMN = 395                  # where it starts, in pixels: the portrait ends before it
CHAR = (985 - COLUMN - 15) / WIDTH    # pixels per character in that column, whatever the viewer's font
LEFT = 36                     # characters of the left stat when two share a line
THEMES = {
    'dark_mode.svg': {'background': '#161b22', 'text': '#c9d1d9', 'key': '#ffa657', 'value': '#a5d6ff', 'dots': '#616e7f',
                      'add': '#3fb950', 'del': '#f85149', 'art': 'art/dark.txt'},
    'light_mode.svg': {'background': '#f6f8fa', 'text': '#24292f', 'key': '#953800', 'value': '#0a3069', 'dots': '#c2cfde',
                       'add': '#1a7f37', 'del': '#cf222e', 'art': 'art/light.txt'},
}


# ------------------------------------------------------------------------------------------------ GitHub's GraphQL API
def graphql(query, variables):
    token = os.environ.get('STATS_TOKEN') or os.environ.get('GITHUB_TOKEN') or os.environ.get('ACCESS_TOKEN')
    if not token:
        sys.exit('Set GITHUB_TOKEN (the workflow does) or STATS_TOKEN to read the stats')
    request = urllib.request.Request('https://api.github.com/graphql', data=json.dumps({'query': query, 'variables': variables}).encode(),
                                     headers={'Authorization': f'bearer {token}', 'User-Agent': f'{USER}-profile-card'})
    with urllib.request.urlopen(request, timeout=60) as response:
        body = json.load(response)
    if body.get('errors'):
        raise RuntimeError(json.dumps(body['errors'])[:500])
    return body['data']


def account():
    data = graphql('query($login: String!) { user(login: $login) { id createdAt followers { totalCount } } }', {'login': USER})['user']
    return data['id'], datetime.fromisoformat(data['createdAt'].replace('Z', '+00:00')), data['followers']['totalCount']


def repositories(affiliations, private):
    """Every repository of the user with these affiliations: name, stars, and the default branch's commit count."""
    query = '''query($login: String!, $cursor: String, $affiliations: [RepositoryAffiliation], $privacy: RepositoryPrivacy) {
      user(login: $login) { repositories(first: 50, after: $cursor, ownerAffiliations: $affiliations, privacy: $privacy) {
        totalCount pageInfo { hasNextPage endCursor }
        nodes { nameWithOwner stargazerCount defaultBranchRef { target { ... on Commit { history { totalCount } } } } } } } }'''
    found, cursor = [], None
    while True:
        page = graphql(query, {'login': USER, 'cursor': cursor, 'affiliations': affiliations, 'privacy': None if private else 'PUBLIC'})['user']['repositories']
        found += page['nodes']
        if not page['pageInfo']['hasNextPage']:
            return found
        cursor = page['pageInfo']['endCursor']


def commits_since(created, private):
    """Commit contributions, a year at a time (the API's longest span), from the account's creation to now."""
    query = '''query($login: String!, $from: DateTime!, $to: DateTime!) { user(login: $login) {
      contributionsCollection(from: $from, to: $to) { totalCommitContributions restrictedContributionsCount } } }'''
    total, start, now = 0, created, datetime.now(timezone.utc)
    while start < now:
        end = min(now, start + timedelta(days=365))
        found = graphql(query, {'login': USER, 'from': start.isoformat(), 'to': end.isoformat()})['user']['contributionsCollection']
        total += found['totalCommitContributions'] + (found['restrictedContributionsCount'] if private else 0)
        start = end
    return total


def own_lines(name, author_id):
    """Additions, deletions and number of the user's own commits on a repository's default branch."""
    owner, repo = name.split('/')
    query = '''query($owner: String!, $repo: String!, $cursor: String, $author: ID!) { repository(owner: $owner, name: $repo) {
      defaultBranchRef { target { ... on Commit { history(first: 100, after: $cursor, author: {id: $author}) {
        pageInfo { hasNextPage endCursor } nodes { additions deletions } } } } } } }'''
    added = deleted = count = 0
    cursor = None
    while True:
        branch = graphql(query, {'owner': owner, 'repo': repo, 'cursor': cursor, 'author': author_id})['repository']['defaultBranchRef']
        if branch is None:
            return 0, 0, 0
        history = branch['target']['history']
        for node in history['nodes']:
            added, deleted, count = added + node['additions'], deleted + node['deletions'], count + 1
        if not history['pageInfo']['hasNextPage']:
            return added, deleted, count
        cursor = history['pageInfo']['endCursor']


def lines_of_code(repos, author_id):
    """Your additions and deletions over every repository, re-reading only those whose commit count changed (cache/loc.json)."""
    path = ROOT / 'cache' / 'loc.json'
    cache = json.loads(path.read_text()) if path.exists() else {}
    fresh = {}
    for repo in repos:
        name, ref = repo['nameWithOwner'], repo['defaultBranchRef']
        total = ref['target']['history']['totalCount'] if ref else 0
        known = cache.get(name)
        if known and known['commits'] == total:
            fresh[name] = known
        else:
            added, deleted, mine = own_lines(name, author_id) if total else (0, 0, 0)
            fresh[name] = {'commits': total, 'additions': added, 'deletions': deleted, 'mine': mine}
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(fresh, indent=1, sort_keys=True) + '\n')
    return sum(item['additions'] for item in fresh.values()), sum(item['deletions'] for item in fresh.values())


def uptime(since):
    today = date.today()
    years, months, days = today.year - since.year, today.month - since.month, today.day - since.day
    if days < 0:
        months -= 1
        previous = date(today.year, today.month, 1) - date.resolution
        days += previous.day
    if months < 0:
        years, months = years - 1, months + 12
    plural = lambda n, word: f"{n} {word}{'' if n == 1 else 's'}"
    return f"{plural(years, 'year')}, {plural(months, 'month')}, {plural(days, 'day')}" + (' 🎂' if (months, days) == (0, 0) else '')


def collect():
    private = os.environ.get('INCLUDE_PRIVATE') == '1'
    author_id, created, followers = account()
    owned = repositories(['OWNER'], private)
    every = repositories(['OWNER', 'COLLABORATOR', 'ORGANIZATION_MEMBER'], private)
    added, deleted = lines_of_code(every, author_id)
    return {'repos': len(owned), 'contributed': len(every), 'stars': sum(repo['stargazerCount'] for repo in owned),
            'followers': followers, 'commits': commits_since(created, private), 'added': added, 'deleted': deleted}


# ------------------------------------------------------------------------------------------------ the card
def number(value):
    return f'{value:,}'


def line(parts, width=WIDTH):
    """One info line as [(text, css class)], with dots between the key and the value so every line is ``width`` long."""
    used = sum(len(text) for text, _ in parts if text != '{fill}')
    fill = ' ' + '.' * max(1, width - used - 2) + ' '
    return [(fill if text == '{fill}' else text, kind) for text, kind in parts]


def keyed(key, value):
    path = key.split('.')
    parts = [('. ', 'dots')]
    for index, piece in enumerate(path):
        parts += [(piece, 'key')] + ([('.', None)] if index < len(path) - 1 else [(':', None)])
    return line(parts + [('{fill}', 'dots'), (value, 'value')])


def pair(left, right):
    """Two stats on one line: the left one padded to LEFT characters, the right one to the rest, joined by ' | '."""
    a = line([('. ', 'dots'), (left[0], 'key'), (':', None), ('{fill}', 'dots'), (left[1], 'value')], LEFT)
    b = line([(right[0], 'key'), (':', None), ('{fill}', 'dots'), (right[1], 'value')], WIDTH - 3 - LEFT)
    return a + [(' | ', None)] + b


def heading(title):
    return [(title, None), (' ' + '─' * (WIDTH - len(title) - 1), None)]


def placed(text, start, step, kind=None):
    """A run of text with every character at its own x (start + i * step): the same layout in every browser and font, where
    textLength is not honoured everywhere (WebKit ignores it on text with differently styled parts)."""
    if not text:
        return ''
    xs = ' '.join(f'{start + i * step:.1f}' for i in range(len(text)))
    style = f' class="{kind}"' if kind else ''
    return f'<tspan x="{xs}"{style}>{escape(text)}</tspan>'


def card(stats, theme):
    lines = [heading(PROFILE['handle'])]
    for item in PROFILE['info']:
        lines.append([('. ', 'dots')] if item is None else keyed(item[0], item[1].format(uptime=uptime(PROFILE['uptime_since']))))
    lines += [[], heading('- Contact')] + [keyed(key, value) for key, value in PROFILE['contact']]
    loc = stats['added'] - stats['deleted']
    lines += [[], heading('- GitHub Stats'),
              pair(('Repos', f"{number(stats['repos'])} {{Contributed: {number(stats['contributed'])}}}"), ('Stars', number(stats['stars']))),
              pair(('Commits', number(stats['commits'])), ('Followers', number(stats['followers']))),
              line([('. ', 'dots'), ('Lines of Code', 'key'), (':', None), ('{fill}', 'dots'),
                    (f"{number(loc)} ( ", 'value'), (f"{number(stats['added'])}++", 'add'), (', ', 'value'), (f"{number(stats['deleted'])}--", 'del'), (' )', 'value')])]
    for parts in lines:                         # a line longer than the column would run off the card: say which, and stop
        text = ''.join(text for text, _ in parts)
        if len(text) > WIDTH:
            raise ValueError(f'This line is {len(text)} characters, more than {WIDTH}: shorten it in PROFILE: {text!r}')
    art = (ROOT / theme['art']).read_text().rstrip('\n').split('\n')
    height = round(max(ART_TOP + ART_LINE * len(art) + 12, 30 + 20 * (len(lines) - 1) + 20))
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="985" height="{height}" viewBox="0 0 985 {height}" font-size="16px" '
           "font-family=\"ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace\">",
           f'<title>{escape(PROFILE["handle"])}: GitHub profile card</title>',
           '<style>text, tspan { white-space: pre; } '
           f'.key {{ fill: {theme["key"]}; }} .value {{ fill: {theme["value"]}; }} .dots {{ fill: {theme["dots"]}; }} '
           f'.add {{ fill: {theme["add"]}; }} .del {{ fill: {theme["del"]}; }}</style>',
           f'<rect width="985" height="{height}" fill="{theme["background"]}" rx="15"/>',
           f'<text x="15" y="{ART_TOP}" fill="{theme["text"]}" font-size="{ART_FONT}px" aria-hidden="true">']
    step = ART_WIDTH / max(len(line) for line in art)
    for row, text in enumerate(art):
        y = f'{ART_TOP + ART_LINE * (row + 1):.2f}'
        out.append(placed(text, 15, step).replace('<tspan ', f'<tspan y="{y}" ', 1))
    out.append('</text>')
    # Every character is placed CHAR pixels after the previous one: fonts differ in width (SF Mono in Safari is wider than Menlo or
    # Consolas), and with the browser's own spacing a line could run past the card's edge in one browser and fall short in another.
    for row, parts in enumerate(lines):
        if not parts:
            continue
        spans, column = '', 0
        for text, kind in parts:
            spans += placed(text, COLUMN + column * CHAR, CHAR, kind)
            column += len(text)
        out.append(f'<text y="{30 + 20 * row}" fill="{theme["text"]}">{spans}</text>')
    out.append('</svg>')
    return '\n'.join(out) + '\n'


def main():
    stats = collect() if '--sample' not in sys.argv else {'repos': 12, 'contributed': 14, 'stars': 1, 'followers': 5, 'commits': 321, 'added': 45678, 'deleted': 6789}
    for name, theme in THEMES.items():
        (ROOT / name).write_text(card(stats, theme), encoding='utf-8')
    if '--sample' not in sys.argv:            # the terminal card (terminal/card.py) reads these numbers instead of calling the API
        (ROOT / 'stats.json').write_text(json.dumps({**stats, 'updated': datetime.now(timezone.utc).isoformat(timespec='seconds')}) + '\n')
    print(json.dumps(stats))


if __name__ == '__main__':
    main()
