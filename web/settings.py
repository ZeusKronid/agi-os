"""Paths shared by the Live ISO website and its VM runtime."""
import os
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1]
BUNDLED = (SOURCE_ROOT / 'installer').is_dir()
ENGINE = SOURCE_ROOT / 'installer' if BUNDLED else SOURCE_ROOT / 'archiso/airootfs/usr/local/share/agi-os/installer'
DATA_ROOT = Path(os.environ.get('AGIOS_DATA_DIR', Path.home() / '.local/share/agi-os'))
GUACAMOLE_JS = SOURCE_ROOT / 'web/static/guacamole.js' if BUNDLED else SOURCE_ROOT / '.local/guacamole.js'
# Newsreader, Geist and Geist Mono: installed system-wide in the ISO, taken from the profile in a checkout.
FONTS = Path('/usr/share/fonts/agios') if BUNDLED else SOURCE_ROOT / 'archiso/airootfs/usr/share/fonts/agios'
