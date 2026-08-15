# -*- mode: python ; coding: utf-8 -*-

import sys


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6.QtDBus', 'PySide6.QtNetwork'],
    noarchive=False,
    optimize=0,
)

if sys.platform == 'darwin':
    unused_qt_frameworks = (
        'PySide6/Qt/lib/QtNetwork.framework/',
        'PySide6/Qt/lib/QtSvg.framework/',
    )
    unused_plugin_dirs = (
        'PySide6/Qt/plugins/generic/',
        'PySide6/Qt/plugins/iconengines/',
        'PySide6/Qt/plugins/imageformats/',
        'PySide6/Qt/plugins/networkinformation/',
        'PySide6/Qt/plugins/platforminputcontexts/',
        'PySide6/Qt/plugins/tls/',
    )
    a.binaries = [
        entry for entry in a.binaries
        if entry[0] not in ('QtNetwork', 'QtSvg')
        and not entry[0].startswith(unused_qt_frameworks + unused_plugin_dirs)
        and not (
            entry[0].startswith('PySide6/Qt/plugins/platforms/')
            and not entry[0].endswith('libqcocoa.dylib')
        )
    ]
    a.datas = [
        entry for entry in a.datas
        if entry[0] not in ('QtNetwork', 'QtSvg')
        and not entry[0].startswith(unused_qt_frameworks)
        and (
            not entry[0].startswith('PySide6/Qt/translations/')
            or entry[0].endswith(('_ko.qm',))
        )
    ]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PDFDesk',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PDFDesk',
)
app = BUNDLE(
    coll,
    name='PDFDesk.app',
    icon=None,
    bundle_identifier=None,
)
