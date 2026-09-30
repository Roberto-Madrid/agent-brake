#!/usr/bin/env python3
"""Offline distribution checks; host validation and directory approval are separate."""
import ast
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

root = Path(__file__).resolve().parents[1]
portable = json.loads((root/'plugin.json').read_text())
claude = json.loads((root/'.claude-plugin/plugin.json').read_text())
assert portable['name'] == claude['name'] == 'token-police'
version = portable['version']
assert claude['version'] == version and re.fullmatch(r'\d+\.\d+\.\d+',version)
assert f'version = "{version}"' in (root/'pyproject.toml').read_text()
assert f'__version__ = "{version}"' in (root/'token_police/__init__.py').read_text()
extension = portable['extensions']['com.openai']
assert extension['hooks'] == './hooks/codex.json'
listing = extension['interface']
for field, maximum in (('displayName',30),('shortDescription',30),('developerName',80),('longDescription',4000)):
    assert isinstance(listing[field],str) and 0 < len(listing[field].strip()) <= maximum, field
assert listing['category'] == 'Productivity'
assert 1 <= len(listing['defaultPrompt']) <= 3
assert len(set(listing['defaultPrompt'])) == len(listing['defaultPrompt'])
assert all(0 < len(p) <= 128 and '\n' not in p for p in listing['defaultPrompt'])
for field in ('logo','composerIcon'):
    image = root/listing[field]
    assert image.resolve().is_relative_to(root) and image.is_file()
    assert image.stat().st_size <= 5*1024*1024
    svg = ET.parse(image).getroot()
    assert svg.attrib['width'] == svg.attrib['height']
for filename, host in (('hooks/hooks.json','claude'),('hooks/codex.json','codex')):
    config = json.loads((root/filename).read_text())
    assert {'SessionStart','PreCompact','PreToolUse','PostToolUse'} <= config['hooks'].keys()
    for event, groups in config['hooks'].items():
        assert event in ('SessionStart','PreCompact','PreToolUse','PostToolUse','PostToolUseFailure')
        for group in groups:
            for handler in group['hooks']:
                assert handler['type'] == 'command', 'Model-powered hooks are forbidden'
                assert f'--host {host}' in handler['command']
                assert '${CLAUDE_PLUGIN_ROOT}/scripts/launch.sh' in handler['command']
                assert handler['timeout'] <= 5
for filename in ('.agents/plugins/marketplace.json','.claude-plugin/marketplace.json'):
    catalog = json.loads((root/filename).read_text())
    assert catalog['name'] == 'token-police-private'
    for plugin in catalog['plugins']:
        source = plugin['source']
        path = source['path'] if isinstance(source,dict) else source
        assert path.startswith('./') and (root/path).resolve() == root
for file in root.rglob('*.json'):
    if '.git' not in file.parts and 'dist' not in file.parts:
        json.loads(file.read_text(encoding='utf-8'))
skill = (root/'skills/token-police/SKILL.md').read_text()
assert skill.startswith('---\nname: token-police\n')
assert 'description:' in skill.split('---')[1] and 'TODO' not in skill
assert len(skill.split()) < 350, 'Skill context budget exceeded'
for link in re.findall(r'`(\.\./\.\./[^` ]+)`',skill):
    assert (root/'skills/token-police'/link).exists(), link
for file in (root/'token_police').glob('*.py'):
    tree = ast.parse(file.read_text())
    for node in ast.walk(tree):
        names = [a.name for a in node.names] if isinstance(node,ast.Import) else [node.module or ''] if isinstance(node,ast.ImportFrom) else []
        assert not any(n.split('.')[0] in {'openai','anthropic','requests','httpx','urllib','socket'} for n in names), file
print(json.dumps({'package_invariants':'passed','version':version,'skill_words':len(skill.split()),
                  'official_host_validation':'see docs/validation.md','public_listing':'not_requested'}))
