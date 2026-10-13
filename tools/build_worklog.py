"""Rebuild the History section of every worklog/<app>.md from git.

Each non-merge commit is put under one app: by the files it touches when they
belong to a single app's module (pumps.py, receivables.py, snowbirds/, ...),
otherwise by its subject, otherwise by which app's code its app.py diff
touches most. Only the text between the HISTORY markers is rewritten; the
hand-written part of each file above them is kept.

    python tools/build_worklog.py            # history of HEAD
    python tools/build_worklog.py origin/main

Needs the full history: in a shallow clone run `git fetch --unshallow` first.
"""
import collections
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKLOG = os.path.join(ROOT, 'worklog')
REPO_URL = 'https://github.com/SimonSEI/PO-Request-app'
START, END = '<!-- HISTORY:START -->', '<!-- HISTORY:END -->'

# key, title, files that belong only to this app, subject pattern.
# Subject patterns are tried in this order, so the narrow apps come first.
APPS = [
    ('workorders', 'Work Orders (archived)', ('archive/workorders/', 'workorders.py', 'tests/test_workorders.py'),
     r'work ?orders?\b'),
    ('timeoff', 'Time-Off Log (parked)', ('timeoff.py', 'TIMEOFF_README.md'),
     r'time-?off'),
    ('receivables', 'Receivables', ('receivables.py', 'receivables_page.py', 'RECEIVABLES_README.md',
                                    'tests/test_receivables.py'),
     r'receivable|retainage|\blien|nonpayment'),
    ('cashflow', 'Cash Flow & AR', (),
     r'cash ?flow|quickbooks|\bqbo\b|authenticator'),
    # The snowbird project started at the repo root before it moved into snowbirds/.
    ('snowbirds', 'Snowbirds', ('snowbirds/', 'app.R', 'R/', 'data/', 'output/', 'clients/', '.Rprofile',
                                'Dockerfile', '.dockerignore', 'run_watcher.bat', 'setup_run_me_first.R',
                                'setup_project_library.R', 'run_app.R'),
     r'snowbird|shiny|forecast|resend|^clients( service)?:|discount|quote in the queue|county on the season'),
    ('pumps', 'Pumps', ('pumps.py', 'pumps_page.py', 'pump_reports.py', 'pumps_assets/', 'PUMPS_README.md',
                        'PUMPS_OPENCLAW.md', 'tests/test_pumps.py'),
     r'pump|wettech|scada|diver|gulfshore|openclaw'),
    ('community', 'Community Maintenance', (),
     r'communit|verona|clock|\bzones?\b|address|house number|nozzle|pricing|billing export|submission|'
     r'\bdrafts?\b|line items?|custom tab'),
    ('installation', 'Installation', (),
     r'installation|\bcrews?\b|proposal|change order|\brfis?\b|daily log|site plan|labor calc|rate card|'
     r'cost import|contract value|job costing|install scheduling|sales app|vendor invoices tracker'),
    ('platform', 'Platform (login, admin, deploy, security)', ('Procfile', 'railway.json', 'nixpacks.toml',
                                                                'runtime.txt', 'requirements.txt', '.gitignore',
                                                                'RAILWAY_SETUP.md', 'reset_password.py', 'env.example'),
     r'office admin|admin panel|password|csrf|login|rate limit|railway|nixpacks|deploy|security|telegram|'
     r'^dashboard|gitignore|backup|session|concurrent users|persistent storage|data loss|full-width|'
     r'claude ai controls|settings page|spanish|language'),
    ('po', 'PO Requests', ('test_email.py',),
     r'.'),  # everything left over: the PO app is where the repo started
]
TITLES = {k: t for k, t, _, _ in APPS}

# Words in an app.py diff that point at one app, for commits whose subject says nothing.
DIFF_HINTS = {
    'community': r'community|verona|clock|house_number|nozzle',
    'installation': r'installation|install_proposal|crew|job_costing|install_schedul|rate_card',
    'cashflow': r'cashflow|cf_|qbo',
    'snowbirds': r'snowbird',
    'pumps': r'pump',
    'platform': r'office_admin|login|password|csrf|limiter|session\[',
    'po': r'po_request|invoice|tech_dashboard|office_dashboard|jobs\b',
}


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def owner_of(path):
    for key, _, paths, _ in APPS:
        if any(path == p or (p.endswith('/') and path.startswith(p)) for p in paths):
            return key
    return None


def by_files(files):
    """The app whose own files the commit changes most, or None when it only touches shared code.
    Platform files (requirements.txt, railway.json, ...) count only when nothing else is touched."""
    churn = collections.Counter()
    for path, lines in files:
        owner = owner_of(path)
        if owner:
            churn[owner] += lines + 1
    if len(churn) > 1:
        churn.pop('platform', None)
    if not churn or (set(churn) == {'platform'} and len(files) > sum(1 for f, _ in files if owner_of(f))):
        return None
    return churn.most_common(1)[0][0]


def by_subject(subject):
    for key, _, _, pattern in APPS[:-1]:
        if re.search(pattern, subject, re.I):
            return key
    return None


def by_diff(sha):
    diff = git('show', '-U0', '--format=', sha, '--', 'app.py')
    changed = '\n'.join(l for l in diff.splitlines() if l[:1] in '+-' and not l.startswith(('+++', '---')))
    scores = {k: len(re.findall(p, changed, re.I)) for k, p in DIFF_HINTS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] else 'po'


def commits(ref):
    out = git('log', ref, '--no-merges', '--reverse', '--date=short', '--format=@@@%h|%ad|%s', '--numstat')
    for block in out.split('@@@')[1:]:
        lines = [l for l in block.splitlines() if l.strip()]
        sha, date, subject = lines[0].split('|', 2)
        files = []
        for row in lines[1:]:
            added, deleted, path = row.split('\t', 2)
            lines_changed = 0 if added == '-' else int(added) + int(deleted)  # '-' = binary file
            files.append((path.split(' => ')[-1].rstrip('}'), lines_changed))
        yield sha, date, subject, files


def history_md(entries):
    lines = [START, '', '## History (generated from git - do not edit by hand)', '',
             f'{len(entries)} commits, {entries[0][1]} to {entries[-1][1]}. Newest month first.', '']
    months = collections.OrderedDict()
    for sha, date, subject in reversed(entries):
        months.setdefault(date[:7], []).append((sha, date, subject))
    for month, rows in months.items():
        lines.append(f'### {month}')
        lines.append('')
        for sha, date, subject in rows:
            lines.append(f'- {date} [`{sha}`]({REPO_URL}/commit/{sha}) {subject}')
        lines.append('')
    lines.append(END)
    return '\n'.join(lines) + '\n'


def main():
    ref = sys.argv[1] if len(sys.argv) > 1 else 'HEAD'
    if git('rev-parse', '--is-shallow-repository').strip() == 'true':
        sys.exit('Shallow clone: run `git fetch --unshallow` first, or the history will be cut short.')
    grouped = collections.defaultdict(list)
    for sha, date, subject, files in commits(ref):
        app = by_files(files) or by_subject(subject) or by_diff(sha)
        grouped[app].append((sha, date, subject))

    os.makedirs(WORKLOG, exist_ok=True)
    for key, title, _, _ in APPS:
        path = os.path.join(WORKLOG, f'{key}.md')
        entries = grouped.get(key, [])
        block = history_md(entries) if entries else f'{START}\n\nNo commits yet.\n\n{END}\n'
        if os.path.exists(path):
            text = open(path, encoding='utf-8').read()
            if START in text and END in text:
                text = text[:text.index(START)] + block + text[text.index(END) + len(END) + 1:]
            else:
                text = text.rstrip('\n') + '\n\n' + block
        else:
            text = f'# {title}\n\n(Describe what this app is and where it stands.)\n\n' + block
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        print(f'{key:13} {len(entries):4} commits')


if __name__ == '__main__':
    main()
