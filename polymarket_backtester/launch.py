"""Prepare the bundled historical study and launch the local, read-only dashboard."""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import venv
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
STUDY = ROOT / 'data' / '2026-09-19_2026-10-19_Etc-GMT+8'


def prepare_data():
    archive = ROOT / 'dataset.zip'
    expected = (ROOT / 'dataset.sha256').read_text().strip()
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        raise RuntimeError('The data download is damaged. Download a fresh GitHub ZIP.')
    if (STUDY / 'audit.json').exists():
        print('Using the already-unpacked study. Existing research files will be preserved.', flush=True)
        return
    print('Unpacking the real historical data. This only happens on first launch.', flush=True)
    with ZipFile(archive) as bundle:
        for member in bundle.infolist():
            destination = (ROOT / member.filename).resolve()
            if not member.filename.startswith('data/') or not destination.is_relative_to(ROOT / 'data'):
                raise RuntimeError('Unexpected path inside the data archive.')
        bad = bundle.testzip()
        if bad:
            raise RuntimeError(f'Damaged dataset member: {bad}')
        bundle.extractall(ROOT)


def main():
    parser = argparse.ArgumentParser(description='Open the Bitcoin research dashboard; no wallet or trades.')
    parser.add_argument('--prepare-only', action='store_true', help='Verify and unpack the included data without installing or starting anything.')
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        raise RuntimeError('Please install Python 3.11 or newer from python.org, then run this launcher again.')
    prepare_data()
    if args.prepare_only:
        print('Data preparation complete.', flush=True)
        return
    environment = ROOT / '.venv'
    python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not python.exists():
        print('Creating a Python environment for this app.', flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)
    print('Checking Python packages. The first launch may take several minutes.', flush=True)
    subprocess.run([str(python), '-m', 'pip', 'install', '--disable-pip-version-check',
                    '-r', str(ROOT / 'requirements.lock')], cwd=ROOT, check=True)
    print('Starting the dashboard. Keep this window open; press Ctrl+C to stop.', flush=True)
    subprocess.run([str(python), '-m', 'streamlit', 'run', str(ROOT / 'app.py'),
                    '--browser.gatherUsageStats=false'], cwd=ROOT, check=True)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f'Could not start the dashboard: {exc}', file=sys.stderr)
        raise SystemExit(1)
