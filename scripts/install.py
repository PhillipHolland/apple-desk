#!/usr/bin/env python3
"""Install only owned command links; refuse to replace unrelated programs."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
NAMES = ['apple-desk'] + ['grok-' + surface for surface in (
    'mail', 'calendar', 'desk', 'reminders', 'notes', 'contacts', 'messages',
    'shortcuts', 'icloud', 'spotlight', 'focus', 'safari')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bin-dir', action='append', help='Link directory (repeatable; default ~/bin and ~/.local/bin)')
    args = parser.parse_args()
    destinations = [Path(p).expanduser().absolute() for p in args.bin_dir] if args.bin_dir else [Path.home() / '.local/bin', Path.home() / 'bin']
    helper = ROOT / 'native/dist/apple-desk-calendar'
    if not helper.is_file():
        parser.error('native helper is missing; run scripts/install.sh without --skip-build')
    links = [(ROOT / 'cli' / name / 'bin' / name, folder / name) for folder in destinations for name in NAMES]
    for source, target in links:
        if not source.is_file():
            parser.error('missing command: ' + str(source))
        if (target.exists() or target.is_symlink()) and not (target.is_symlink() and target.resolve() == source.resolve()):
            parser.error('refusing to replace an unrelated command: ' + str(target))
    installed = []
    for source, target in links:
        target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        if not target.is_symlink():
            target.symlink_to(source)
        installed.append(str(target))
    print(json.dumps({'ok': True, 'version': '0.2.0', 'commands': installed,
                      'permissionsRequested': False, 'indexesBuilt': False,
                      'next': ['apple-desk doctor', 'apple-desk permissions request --mail',
                               'apple-desk permissions request --calendar']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
