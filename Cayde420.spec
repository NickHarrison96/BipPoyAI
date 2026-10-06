# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # litellm's source pulls in an enormous optional ML stack that this app
    # never touches at runtime. litellm/llms/petals does `from transformers
    # import`, transformers pulls torch, and a buried litellm
    # proxy/guardrails/.../guardrail_benchmarks/test_eval.py does `import
    # pytest`. PyInstaller follows that textually, so it bundles torch,
    # transformers, scipy, pandas, IPython and pytest into a onefile exe that
    # only ever needs PySide6, requests, psutil, pynvml, ollama and mcp.
    #
    # Verified by `import main` then inspecting sys.modules: none of these
    # load at runtime. numpy is deliberately NOT excluded — litellm imports it
    # lazily on paths we cannot exercise without a live model, and a frozen
    # ImportError there would fail only when someone starts chatting.
    excludes=[
        'torch',
        'transformers',
        'scipy',
        'pandas',
        'IPython',
        'pytest',
    ],
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
    name='Cayde420',
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
)
