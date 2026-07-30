"""Application palettes and Qt stylesheets."""

from __future__ import annotations

import ctypes
import sys

from PySide6.QtWidgets import QApplication


LIGHT_COLORS = {
    "background": "#F4F7FB",
    "surface": "#FFFFFF",
    "text": "#172033",
    "muted": "#667085",
    "link": "#1D4ED8",
    "success": "#18864B",
    "warning": "#B06B00",
    "error": "#C43232",
    "border": "#E5EAF2",
}

DARK_COLORS = {
    "background": "#0E1420",
    "surface": "#111926",
    "text": "#E7ECF4",
    "muted": "#98A5B8",
    "link": "#80B1FF",
    "success": "#4ADE80",
    "warning": "#FBBF24",
    "error": "#FCA5A5",
    "border": "#2B3545",
}


def theme_colors(theme: str) -> dict[str, str]:
    """Return semantic colors used by runtime-generated rich text."""
    return DARK_COLORS if theme == "dark" else LIGHT_COLORS


def _windows_apps_use_light_theme() -> int:
    import winreg

    key_path = (
        r"Software\Microsoft\Windows\CurrentVersion"
        r"\Themes\Personalize"
    )
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        key_path,
    ) as key:
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
    return int(value)


def detect_system_theme() -> str:
    """Read the Windows application theme, with a safe Qt fallback."""
    if sys.platform == "win32":
        try:
            return (
                "light"
                if _windows_apps_use_light_theme()
                else "dark"
            )
        except (OSError, TypeError, ValueError):
            pass

    application = QApplication.instance()
    if application is not None:
        try:
            scheme = application.styleHints().colorScheme()
            if getattr(scheme, "name", "") == "Dark":
                return "dark"
        except (AttributeError, TypeError):
            pass
    return "light"


LIGHT_STYLESHEET = """
QWidget {
    color: #172033;
    font-family: "Microsoft YaHei UI", "Segoe UI";
    font-size: 13px;
}
QWidget#appRoot {
    background: #F4F7FB;
}
QDialog, QMessageBox {
    background: #F4F7FB;
}
QMessageBox QLabel {
    color: #172033;
}
QStackedWidget#contentStack, QWidget#pageContent {
    background: #F4F7FB;
    border: none;
}
QFrame#sidebar {
    background: #FFFFFF;
    border-right: 1px solid #E5EAF2;
}
QLabel#brandMark {
    min-width: 42px;
    max-width: 42px;
    min-height: 42px;
    max-height: 42px;
    border-radius: 11px;
    background: #2563EB;
    color: #FFFFFF;
    font-size: 17px;
    font-weight: 700;
}
QLabel#brandTitle {
    color: #101828;
    font-size: 16px;
    font-weight: 700;
}
QLabel#brandVersion, QLabel#navCaption, QLabel#pageSubtitle,
QLabel#helperText, QLabel#mutedText {
    color: #667085;
}
QLabel#navCaption {
    font-size: 11px;
    font-weight: 600;
}
QListWidget#navigation {
    background: transparent;
    border: none;
    outline: none;
    padding: 0;
}
QListWidget#navigation::item {
    border: none;
    border-radius: 9px;
    color: #475467;
    min-height: 44px;
    padding: 0 12px;
    margin: 2px 0;
}
QListWidget#navigation::item:hover {
    background: #F2F4F7;
    color: #1D2939;
}
QListWidget#navigation::item:selected {
    background: #EAF1FF;
    color: #1D4ED8;
    font-weight: 600;
}
QFrame#sidebarStatus {
    background: #F8FAFC;
    border: 1px solid #E5EAF2;
    border-radius: 10px;
}
QLabel#statusDot {
    min-width: 9px;
    max-width: 9px;
    min-height: 9px;
    max-height: 9px;
    border-radius: 4px;
    background: #16A34A;
}
QLabel#statusDot[state="warning"] {
    background: #F59E0B;
}
QLabel#statusDot[state="error"] {
    background: #DC2626;
}
QLabel#statusTitle {
    color: #344054;
    font-size: 12px;
    font-weight: 600;
}
QLabel#statusDetail {
    color: #667085;
    font-size: 11px;
}
QLabel#pageTitle {
    color: #101828;
    font-size: 24px;
    font-weight: 700;
}
QLabel#pageSubtitle {
    font-size: 13px;
}
QLabel#sectionTitle {
    color: #1D2939;
    font-size: 15px;
    font-weight: 600;
}
QFrame#card {
    background: #FFFFFF;
    border: 1px solid #E5EAF2;
    border-radius: 13px;
}
QLineEdit, QTextEdit, QListWidget#historyList {
    background: #FFFFFF;
    color: #172033;
    placeholder-text-color: #667085;
    border: 1px solid #D7DEE9;
    border-radius: 9px;
    padding: 9px 11px;
    selection-background-color: #CFE0FF;
    selection-color: #172033;
}
QLineEdit:hover, QTextEdit:hover, QListWidget#historyList:hover {
    border-color: #B8C3D4;
}
QLineEdit:focus, QTextEdit:focus, QListWidget#historyList:focus {
    border: 1px solid #4F7FF0;
}
QLineEdit {
    min-height: 22px;
}
QTextEdit {
    padding: 11px;
}
QListWidget#historyList {
    padding: 6px;
    outline: none;
}
QListWidget#historyList::item {
    min-height: 42px;
    border-radius: 7px;
    padding: 5px 8px;
    margin: 2px;
}
QListWidget#historyList::item:hover {
    background: #F2F4F7;
}
QListWidget#historyList::item:selected {
    background: #EAF1FF;
    color: #1D4ED8;
}
QPushButton {
    min-height: 38px;
    padding: 0 16px;
    border-radius: 8px;
    border: 1px solid #D7DEE9;
    background: #FFFFFF;
    color: #344054;
    font-weight: 600;
}
QPushButton:hover {
    background: #F8FAFC;
    border-color: #B8C3D4;
}
QPushButton:pressed {
    background: #EFF2F6;
}
QPushButton:disabled {
    background: #F2F4F7;
    color: #98A2B3;
    border-color: #E5E7EB;
}
QPushButton[primary="true"] {
    background: #2563EB;
    border-color: #2563EB;
    color: #FFFFFF;
}
QPushButton[primary="true"]:hover {
    background: #1D4ED8;
    border-color: #1D4ED8;
}
QPushButton[danger="true"] {
    color: #C43232;
    border-color: #F0CACA;
    background: #FFF9F9;
}
QPushButton[danger="true"]:hover {
    background: #FFF0F0;
}
QPushButton#themeButton {
    text-align: left;
}
QLabel#qrPreview, QLabel#decodePreview {
    background: #F8FAFC;
    color: #98A2B3;
    border: 1px dashed #C7D0DE;
    border-radius: 10px;
}
QTextEdit#decodeResult {
    background: #F8FAFC;
}
QCheckBox {
    spacing: 8px;
}
QCheckBox::indicator {
    width: 17px;
    height: 17px;
}
QMenu {
    background: #FFFFFF;
    color: #172033;
    border: 1px solid #D7DEE9;
    border-radius: 8px;
    padding: 6px;
}
QMenu::item {
    padding: 7px 24px 7px 10px;
    border-radius: 5px;
}
QMenu::item:selected {
    background: #EAF1FF;
    color: #1D4ED8;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 3px;
}
QScrollBar::handle:vertical {
    background: #C8D0DC;
    min-height: 28px;
    border-radius: 4px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 3px;
}
QScrollBar::handle:horizontal {
    background: #C8D0DC;
    min-width: 28px;
    border-radius: 4px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}
QToolTip {
    color: #FFFFFF;
    background: #1D2939;
    border: none;
    padding: 5px;
}
"""


DARK_STYLESHEET = """
QWidget {
    color: #E7ECF4;
    font-family: "Microsoft YaHei UI", "Segoe UI";
    font-size: 13px;
}
QWidget#appRoot {
    background: #0E1420;
}
QDialog, QMessageBox {
    background: #0E1420;
}
QMessageBox QLabel {
    color: #E7ECF4;
}
QStackedWidget#contentStack, QWidget#pageContent {
    background: #0E1420;
    border: none;
}
QFrame#sidebar {
    background: #121A28;
    border-right: 1px solid #263143;
}
QLabel#brandMark {
    min-width: 42px;
    max-width: 42px;
    min-height: 42px;
    max-height: 42px;
    border-radius: 11px;
    background: #3B82F6;
    color: #FFFFFF;
    font-size: 17px;
    font-weight: 700;
}
QLabel#brandTitle {
    color: #F7F9FC;
    font-size: 16px;
    font-weight: 700;
}
QLabel#brandVersion, QLabel#navCaption, QLabel#pageSubtitle,
QLabel#helperText, QLabel#mutedText {
    color: #98A5B8;
}
QLabel#navCaption {
    font-size: 11px;
    font-weight: 600;
}
QListWidget#navigation {
    background: transparent;
    border: none;
    outline: none;
    padding: 0;
}
QListWidget#navigation::item {
    border: none;
    border-radius: 9px;
    color: #AEB9C9;
    min-height: 44px;
    padding: 0 12px;
    margin: 2px 0;
}
QListWidget#navigation::item:hover {
    background: #1A2535;
    color: #F4F7FB;
}
QListWidget#navigation::item:selected {
    background: #1C3152;
    color: #80B1FF;
    font-weight: 600;
}
QFrame#sidebarStatus {
    background: #172131;
    border: 1px solid #263143;
    border-radius: 10px;
}
QLabel#statusDot {
    min-width: 9px;
    max-width: 9px;
    min-height: 9px;
    max-height: 9px;
    border-radius: 4px;
    background: #22C55E;
}
QLabel#statusDot[state="warning"] {
    background: #FBBF24;
}
QLabel#statusDot[state="error"] {
    background: #F87171;
}
QLabel#statusTitle {
    color: #DEE5EF;
    font-size: 12px;
    font-weight: 600;
}
QLabel#statusDetail {
    color: #8F9CAF;
    font-size: 11px;
}
QLabel#pageTitle {
    color: #F7F9FC;
    font-size: 24px;
    font-weight: 700;
}
QLabel#pageSubtitle {
    font-size: 13px;
}
QLabel#sectionTitle {
    color: #F0F3F8;
    font-size: 15px;
    font-weight: 600;
}
QFrame#card {
    background: #151E2C;
    border: 1px solid #293548;
    border-radius: 13px;
}
QLineEdit, QTextEdit, QListWidget#historyList {
    background: #111926;
    color: #E7ECF4;
    placeholder-text-color: #98A5B8;
    border: 1px solid #354156;
    border-radius: 9px;
    padding: 9px 11px;
    selection-background-color: #294D80;
    selection-color: #FFFFFF;
}
QLineEdit:hover, QTextEdit:hover, QListWidget#historyList:hover {
    border-color: #52617A;
}
QLineEdit:focus, QTextEdit:focus, QListWidget#historyList:focus {
    border: 1px solid #6495ED;
}
QLineEdit {
    min-height: 22px;
}
QTextEdit {
    padding: 11px;
}
QListWidget#historyList {
    padding: 6px;
    outline: none;
}
QListWidget#historyList::item {
    min-height: 42px;
    border-radius: 7px;
    padding: 5px 8px;
    margin: 2px;
}
QListWidget#historyList::item:hover {
    background: #1C2737;
}
QListWidget#historyList::item:selected {
    background: #1C3152;
    color: #80B1FF;
}
QPushButton {
    min-height: 38px;
    padding: 0 16px;
    border-radius: 8px;
    border: 1px solid #354156;
    background: #1A2433;
    color: #DDE5F0;
    font-weight: 600;
}
QPushButton:hover {
    background: #222E40;
    border-color: #52617A;
}
QPushButton:pressed {
    background: #111926;
}
QPushButton:disabled {
    background: #171F2B;
    color: #657188;
    border-color: #2B3545;
}
QPushButton[primary="true"] {
    background: #3B82F6;
    border-color: #3B82F6;
    color: #FFFFFF;
}
QPushButton[primary="true"]:hover {
    background: #2563EB;
    border-color: #2563EB;
}
QPushButton[danger="true"] {
    color: #FCA5A5;
    border-color: #663B43;
    background: #281A20;
}
QPushButton[danger="true"]:hover {
    background: #352027;
}
QPushButton#themeButton {
    text-align: left;
}
QLabel#qrPreview, QLabel#decodePreview {
    background: #111926;
    color: #718096;
    border: 1px dashed #3B485C;
    border-radius: 10px;
}
QTextEdit#decodeResult {
    background: #111926;
}
QCheckBox {
    spacing: 8px;
}
QCheckBox::indicator {
    width: 17px;
    height: 17px;
}
QMenu {
    background: #172131;
    color: #E7ECF4;
    border: 1px solid #354156;
    border-radius: 8px;
    padding: 6px;
}
QMenu::item {
    padding: 7px 24px 7px 10px;
    border-radius: 5px;
}
QMenu::item:selected {
    background: #1C3152;
    color: #80B1FF;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 3px;
}
QScrollBar::handle:vertical {
    background: #46536A;
    min-height: 28px;
    border-radius: 4px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 3px;
}
QScrollBar::handle:horizontal {
    background: #46536A;
    min-width: 28px;
    border-radius: 4px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}
QToolTip {
    color: #FFFFFF;
    background: #293548;
    border: none;
    padding: 5px;
}
"""


def apply_theme(app: QApplication, theme: str) -> str:
    """Apply a supported theme and return its normalized name."""

    normalized = "dark" if theme == "dark" else "light"
    app.setProperty("qrcapTheme", normalized)
    app.setStyle("Fusion")
    app.setStyleSheet(
        DARK_STYLESHEET if normalized == "dark" else LIGHT_STYLESHEET
    )
    return normalized


def apply_native_titlebar_theme(widget, theme: str) -> None:
    """Keep the Windows native frame aligned with the application theme."""

    if sys.platform != "win32":
        return

    try:
        hwnd = int(widget.winId())
        dwmapi = ctypes.windll.dwmapi
        setter = dwmapi.DwmSetWindowAttribute
        setter.argtypes = (
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.c_uint,
        )
        setter.restype = ctypes.c_long

        dark = ctypes.c_int(1 if theme == "dark" else 0)
        for attribute in (20, 19):
            result = setter(
                hwnd,
                attribute,
                ctypes.byref(dark),
                ctypes.sizeof(dark),
            )
            if result == 0:
                break

        palette = theme_colors(theme)
        colors = (
            palette["background"],
            palette["text"],
            palette["border"],
        )
        for attribute, color in zip((35, 36, 34), colors):
            red = int(color[1:3], 16)
            green = int(color[3:5], 16)
            blue = int(color[5:7], 16)
            colorref = ctypes.c_uint(red | (green << 8) | (blue << 16))
            setter(
                hwnd,
                attribute,
                ctypes.byref(colorref),
                ctypes.sizeof(colorref),
            )
    except (AttributeError, OSError, TypeError, ValueError):
        return
