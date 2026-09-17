from pathlib import Path
root = Path(__file__).resolve().parents[2]
source = root / '.local/guacamole-client-1.6.0/guacamole-common-js/src/main/webapp'
files = [source / 'common/license.js', *sorted((source / 'modules').glob('*.js'))]
assert len(files) > 10, 'Guacamole source is incomplete'
(root / '.local/guacamole.js').write_text('\n'.join(path.read_text() for path in files))
