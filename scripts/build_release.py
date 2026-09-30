#!/usr/bin/env python3
"""Reproducible, private distribution archives. Does not publish anything."""
import argparse
import hashlib
import json
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--output-dir', default=str(root/'dist'))
args = parser.parse_args()
output = Path(args.output_dir).resolve()
output.mkdir(parents=True, exist_ok=True)
version = json.loads((root/'plugin.json').read_text())['version']
allowed_dirs = {'token_police','scripts','skills','hooks','assets','docs','examples','tests',
                '.agents','.claude-plugin'}
allowed_files = {'plugin.json','pyproject.toml','README.md','LICENSE','SECURITY.md','CHANGELOG.md','CONTRIBUTING.md','AGENTS.md'}
files = [p for p in root.rglob('*') if p.is_file() and not p.is_symlink() and
         '__pycache__' not in p.parts and p.suffix not in ('.pyc','.pyo') and
         (p.relative_to(root).parts[0] in allowed_dirs or p.relative_to(root).as_posix() in allowed_files)]
checksums = []
for host in ('openai','anthropic'):
    target = output/f'token-police-{host}-{version}.zip'
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for path in sorted(files):
            relative = path.relative_to(root).as_posix()
            if relative.endswith('/marketplace.json'):
                continue
            if host == 'openai' and relative.startswith('.claude-plugin/'):
                continue
            entry = zipfile.ZipInfo(relative, (1980,1,1,0,0,0))
            entry.create_system = 3
            entry.external_attr = (0o100755 if path.suffix == '.sh' else 0o100644) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            data = path.read_bytes().replace(b'\r\n',b'\n')
            archive.writestr(entry,data)
    checksums.append(hashlib.sha256(target.read_bytes()).hexdigest()+'  '+target.name)
(output/'SHA256SUMS').write_text('\n'.join(checksums)+'\n',encoding='utf-8')
print(json.dumps({'version':version,'artifacts':checksums,'published':False}))
