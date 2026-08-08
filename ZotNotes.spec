# -*- mode: python ; coding: utf-8 -*-
# 单文件 exe 打包配置：产物为单个 ZotNotes.exe（自解压运行），
# 静态资源 theme.json / icon.ico 内置进 exe（运行时经 config.resource_path 回退读取）。
# config.json / template.md 不内置：首启时在 exe 同目录自动生成/创建，保证用户可编辑。
from PyInstaller.utils.hooks import collect_all

datas = [('theme.json', '.'), ('icon.ico', '.')]
binaries = []
hiddenimports = []
for pkg in ('customtkinter', 'pdfplumber', 'pdfminer', 'pymupdf'):
    tmp = collect_all(pkg)
    datas += tmp[0]
    binaries += tmp[1]
    hiddenimports += tmp[2]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ZotNotes',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.ico'],
)
