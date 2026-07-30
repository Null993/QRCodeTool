# -*- mode: python ; coding: utf-8 -*-
"""Lean onedir build for the base application.

The optional QReader/PyTorch runtime is imported separately by the user and is
never bundled here. The filter also removes Qt and image-codec components that
are unrelated to this Widgets-only desktop application.
"""

from PyInstaller.utils.hooks import collect_dynamic_libs


datas = [("icon.ico", ".")]
binaries = collect_dynamic_libs("pyzbar")

qt_excludes = [
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtBluetooth",
    "PySide6.QtCharts",
    "PySide6.QtConcurrent",
    "PySide6.QtDataVisualization",
    "PySide6.QtDBus",
    "PySide6.QtDesigner",
    "PySide6.QtGraphs",
    "PySide6.QtHelp",
    "PySide6.QtHttpServer",
    "PySide6.QtLocation",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtNetwork",
    "PySide6.QtNetworkAuth",
    "PySide6.QtNfc",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtPositioning",
    "PySide6.QtPrintSupport",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtSensors",
    "PySide6.QtSerialBus",
    "PySide6.QtSerialPort",
    "PySide6.QtSpatialAudio",
    "PySide6.QtSql",
    "PySide6.QtStateMachine",
    "PySide6.QtSvg",
    "PySide6.QtSvgWidgets",
    "PySide6.QtTest",
    "PySide6.QtTextToSpeech",
    "PySide6.QtUiTools",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets",
    "PySide6.QtXml",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=["webbrowser", "zxingcpp"],
    hookspath=["pyinstaller_hooks"],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "qreader",
        "qrdet",
        "torch",
        "torchvision",
        "ultralytics",
        "matplotlib",
        "cv2",
        "numpy",
        "PIL",
        "pandas",
        "scipy",
        "tkinter",
        "numpy.random._examples",
        *qt_excludes,
    ],
    noarchive=False,
    optimize=2,
)


def keep_runtime_entry(entry):
    destination = entry[0].replace("\\", "/").lower()
    drop_fragments = (
        "translations/",
        "opengl32sw.dll",
        "opencv_videoio_ffmpeg",
        "cv2/data/",
        "cv2/qt/",
        "pyside6/plugins/networkinformation/",
        "pyside6/plugins/tls/",
        "pyside6/qt6network.dll",
        "pyside6/qt6opengl.dll",
        "pyside6/qt6pdf.dll",
        "pyside6/qt6qml.dll",
        "pyside6/qt6qmlmodels.dll",
        "pyside6/qt6quick.dll",
        "pyside6/qt6svg.dll",
        "pyside6/qt6virtualkeyboard.dll",
        "pyside6/qt6qmlmeta.dll",
        "pyside6/plugins/generic/",
        "pyside6/plugins/styles/",
        "pyside6/plugins/virtualkeyboard/",
    )
    if any(fragment in destination for fragment in drop_fragments):
        return False
    if "pyside6/plugins/imageformats/" in destination:
        return destination.endswith(("/qjpeg.dll", "/qico.dll"))
    if "pyside6/plugins/platforms/" in destination:
        return destination.endswith("/qwindows.dll")
    return True


a.binaries = [entry for entry in a.binaries if keep_runtime_entry(entry)]
a.datas = [entry for entry in a.datas if keep_runtime_entry(entry)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="QRCodeTool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=["icon.ico"],
    version="version_info.txt",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="QRCodeTool-v1.3-base",
)
