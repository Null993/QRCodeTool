"""Main Qt window and application entry point."""

import sys
import os
import json
import html
from datetime import datetime
import webbrowser
import re
import warnings

from .capture import CaptureScreen
from .enhancement import EnhancementManager
from .enhancement_ui import EnhancementPage
from .recognition import RecognitionService
from .resources import resource_path
from .theme import (
    apply_native_titlebar_theme,
    apply_theme,
    detect_system_tray_theme,
    detect_system_theme,
    theme_colors,
)
from .ui_components import (
    Card,
    PageHeader,
    StablePixmapLabel,
    ThemedCheckBox,
    ThemedCheckItemDelegate,
    helper_label,
    navigation_icon,
    section_label,
    themed_tray_icon,
)

warnings.filterwarnings("ignore", message="Double decoding failed")

# ---------- 常量 ----------
HISTORY_FILE = "history.json"
CONFIG_FILE = "config.json"
SUPPORTED_IMAGE_SUFFIXES = frozenset({
    ".bmp",
    ".jpeg",
    ".jpg",
    ".png",
})


def notify_shell_executable_updated() -> None:
    """Ask Windows Explorer to discard a stale icon for this executable."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    try:
        import ctypes

        shell_change_update_item = 0x00002000
        shell_notify_path_w = 0x0005
        shell_notify_flush = 0x1000
        ctypes.windll.shell32.SHChangeNotify(
            shell_change_update_item,
            shell_notify_path_w | shell_notify_flush,
            str(sys.executable),
            None,
        )
    except (AttributeError, OSError):
        pass


# ---------- 正则：识别文本中的第一个 URL（支持不带 scheme 的裸域名 / www） ----------
_url_re = re.compile(
    r"""(?xi)
    (
      https?://[^\s'"]+ |                     # 带 http(s) 的完整 URL
      www\.[^\s'"]+ |                         # 以 www. 开头的
      [a-z0-9\-.]+\.(?:com|net|org|io|gov|cn|xyz|top|info|biz|site|tech|me)(?:/[^\s'"]*)? # 裸域名+常见TLD（带可选路径）
    )
    """
)
def extract_first_url(text: str) -> str | None:
    """从文本中提取第一个 URL，若无则返回 None。
       若提取到裸域名或以 www. 开头的，会补上 http:// 以便 webbrowser.open 使用。"""
    m = _url_re.search(text)
    if not m:
        return None
    url = m.group(1)
    if not re.match(r"^https?://", url, re.I):
        url = "http://" + url
    return url


def image_path_from_mime_data(mime_data) -> str | None:
    """Return the first supported local image path in a drop payload."""
    if mime_data is None or not mime_data.hasUrls():
        return None
    for url in mime_data.urls():
        if not url.isLocalFile():
            continue
        path = url.toLocalFile()
        if (
            os.path.isfile(path)
            and os.path.splitext(path)[1].lower()
            in SUPPORTED_IMAGE_SUFFIXES
        ):
            return path
    return None


def render_decode_message_html(
    message: str,
    theme: str,
    tone: str = "muted",
) -> str:
    """Render a theme-aware recognition status or error message."""
    colors = theme_colors(theme)
    color = colors[tone if tone in colors else "text"]
    return (
        f'<div style="color:{color};">'
        f'{html.escape(message)}</div>'
    )


def render_decode_results_html(texts, theme: str) -> str:
    """Render decoded values with explicit colors for Qt rich text."""
    colors = theme_colors(theme)
    cards = []
    for text in texts:
        safe_text = html.escape(text).replace("\n", "<br>")
        url = extract_first_url(text)
        content = safe_text
        if url:
            content = (
                f'<a href="{html.escape(url, quote=True)}" '
                f'style="color:{colors["link"]};'
                f'text-decoration:none;">{safe_text}</a>'
            )
        cards.append(
            '<div style="margin-bottom:12px;padding:10px 0;'
            f'background:transparent;color:{colors["text"]};'
            'font-size:14px;word-wrap:break-word;'
            f'border-bottom:1px solid {colors["border"]};">'
            f'{content}</div>'
        )
    return "".join(cards)


def window_display_mode(widget) -> str:
    """Capture the visible window mode before temporarily hiding it."""
    if widget.isFullScreen():
        return "fullscreen"
    if widget.isMaximized():
        return "maximized"
    return "normal"


def restore_window_display_mode(widget, mode: str) -> None:
    """Show a window in its previously captured display mode."""
    if mode == "fullscreen":
        widget.showFullScreen()
    elif mode == "maximized":
        widget.showMaximized()
    else:
        widget.showNormal()


def resolve_initial_theme(config: dict) -> str:
    """Use an explicit preference or fall back to the Windows theme."""
    saved_theme = config.get("theme")
    if saved_theme in ("light", "dark"):
        return saved_theme
    return detect_system_theme()


# ---------------------------
# GUI 相关导入
# ---------------------------
from PySide6.QtWidgets import (
    QApplication, QWidget, QStackedWidget, QVBoxLayout, QLabel, QPushButton,
    QTextEdit, QFileDialog, QLineEdit, QSystemTrayIcon, QMenu,
    QListWidget, QListWidgetItem, QMessageBox, QHBoxLayout,
    QSizePolicy, QFrame
)
from PySide6.QtGui import QImage, QPainter, QPixmap, QAction
from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal

# ================================
#           主程序
# ================================
class QRApp(QWidget):
    hotkey_triggered = Signal()

    def __init__(self):
        super().__init__()

        self.chk_all = None
        self.hotkey_handle = None
        self.setAcceptDrops(True)
        self.setObjectName("appRoot")
        self.setWindowTitle("QRCodeTool · 二维码工具 v1.3")
        self.setMinimumSize(820, 560)
        self.resize(1080, 720)
        self.config = self.load_config()
        self.theme = apply_theme(
            QApplication.instance(),
            resolve_initial_theme(self.config),
        )
        self.update_system_icons()
        QApplication.instance().installEventFilter(self)

        self.cap = None
        self._capture_pending = False
        self._capture_window_mode = "normal"
        self._decode_busy = False
        self._decode_request_id = 0
        self._decode_render_state = None
        configured_enhancement_root = self.config.get("enhancement_dir")
        self.enhancement_manager = EnhancementManager(
            configured_enhancement_root or None
        )
        self.recognition = RecognitionService(
            self.enhancement_manager,
            parent=self,
        )
        self.recognition.progress.connect(self.on_decode_progress)
        self.recognition.finished.connect(self.on_decode_finished)
        self.history = self.load_history()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(230)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(18, 22, 18, 18)
        sidebar_layout.setSpacing(14)

        brand = QHBoxLayout()
        brand.setSpacing(11)
        brand_mark = QLabel("QR")
        brand_mark.setObjectName("brandMark")
        brand_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand.addWidget(brand_mark)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(1)
        brand_title = QLabel("QRCodeTool")
        brand_title.setObjectName("brandTitle")
        brand_text.addWidget(brand_title)
        brand_version = QLabel("v1.3 · Null993")
        brand_version.setObjectName("brandVersion")
        brand_text.addWidget(brand_version)
        brand.addLayout(brand_text)
        brand.addStretch(1)
        sidebar_layout.addLayout(brand)

        nav_caption = QLabel("功能")
        nav_caption.setObjectName("navCaption")
        sidebar_layout.addWidget(nav_caption)

        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation")
        self.navigation.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.navigation.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.navigation.setSpacing(2)
        self.navigation.setUniformItemSizes(True)
        for icon_name, label in (
            ("generate", "生成二维码"),
            ("scan", "识别二维码"),
            ("history", "历史记录"),
            ("hotkey", "快捷键设置"),
            ("enhancement", "增强能力"),
        ):
            item = QListWidgetItem(navigation_icon(icon_name), label)
            item.setSizeHint(QSize(0, 44))
            self.navigation.addItem(item)
        navigation_height = (
            self.navigation.count()
            * (44 + 2 * self.navigation.spacing())
        )
        self.navigation.setFixedHeight(navigation_height)
        sidebar_layout.addWidget(self.navigation)
        sidebar_layout.addStretch(1)

        status_frame = QFrame()
        status_frame.setObjectName("sidebarStatus")
        status_layout = QVBoxLayout(status_frame)
        status_layout.setContentsMargins(12, 10, 12, 10)
        status_layout.setSpacing(4)
        status_head = QHBoxLayout()
        status_head.setSpacing(7)
        self.sidebar_status_dot = QLabel()
        self.sidebar_status_dot.setObjectName("statusDot")
        status_head.addWidget(self.sidebar_status_dot)
        self.sidebar_status_title = QLabel()
        self.sidebar_status_title.setObjectName("statusTitle")
        status_head.addWidget(self.sidebar_status_title, stretch=1)
        status_layout.addLayout(status_head)
        self.sidebar_status_detail = QLabel()
        self.sidebar_status_detail.setObjectName("statusDetail")
        self.sidebar_status_detail.setWordWrap(True)
        status_layout.addWidget(self.sidebar_status_detail)
        sidebar_layout.addWidget(status_frame)

        self.theme_button = QPushButton()
        self.theme_button.setObjectName("themeButton")
        self.theme_button.clicked.connect(self.toggle_theme)
        sidebar_layout.addWidget(self.theme_button)
        layout.addWidget(sidebar)

        self.tabs = QStackedWidget()
        self.tabs.setObjectName("contentStack")
        self.tabs.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Ignored,
        )
        self.tabs.setMinimumSize(0, 0)
        layout.addWidget(self.tabs, stretch=1)

        self.tabs.addWidget(self.page_generate())
        self.tabs.addWidget(self.page_decode())
        self.tabs.addWidget(self.page_history())
        self.tabs.addWidget(self.page_hotkey())
        self.enhancement_page = EnhancementPage(
            self.enhancement_manager,
            self.recognition,
        )
        self.tabs.addWidget(self.enhancement_page)
        self.enhancement_page.status_changed.connect(
            self.update_enhancement_summary
        )
        self.enhancement_page.directory_changed.connect(
            self.save_enhancement_directory
        )
        self.navigation.currentRowChanged.connect(self.tabs.setCurrentIndex)
        self.tabs.currentChanged.connect(self.on_page_changed)
        self.navigation.setCurrentRow(0)
        self.update_theme_button()
        self.update_enhancement_summary(self.enhancement_manager.inspect())
        layout.activate()
        self.enhancement_page.prewarm_layout()
        QTimer.singleShot(0, self.update_native_titlebar)
        QTimer.singleShot(0, notify_shell_executable_updated)

        self.hotkey_triggered.connect(self.start_capture)

        self.start_hotkey_listener()
        self.init_tray()
        QTimer.singleShot(1200, self.recognition.start_background_preload)
        self._model_preload_idle_timer = QTimer(self)
        self._model_preload_idle_timer.setSingleShot(True)
        self._model_preload_idle_timer.setInterval(5000)
        self._model_preload_idle_timer.timeout.connect(
            self.recognition.start_optional_model_preload
        )
        self._model_preload_idle_timer.start()

    def load_config(self):
        if not os.path.exists(CONFIG_FILE):
            return {"hotkey": ""}
        try:
            config = json.load(open(CONFIG_FILE, "r", encoding="utf8"))
            config.pop("detect_all_plus", None)
            config.setdefault("hotkey", "")
            return config
        except:
            return {"hotkey": ""}

    def save_config(self):
        self.config.pop("detect_all_plus", None)
        json.dump(self.config, open(CONFIG_FILE, "w", encoding="utf8"),
                  ensure_ascii=False, indent=2)

    def toggle_theme(self):
        self.theme = "dark" if self.theme == "light" else "light"
        self.config["theme"] = self.theme
        self.save_config()
        apply_theme(QApplication.instance(), self.theme)
        self.update_theme_button()
        self.enhancement_page.refresh_status()
        self.refresh_decode_theme()
        self.update_native_titlebar()
        self.update_system_icons()
        QTimer.singleShot(0, self.update_native_titlebar)

    def update_theme_button(self):
        if self.theme == "dark":
            self.theme_button.setText("切换到浅色模式")
        else:
            self.theme_button.setText("切换到深色模式")

    def update_native_titlebar(self):
        apply_native_titlebar_theme(self, self.theme)

    def save_enhancement_directory(self, directory: str):
        if directory:
            self.config["enhancement_dir"] = directory
        else:
            self.config.pop("enhancement_dir", None)
        self.save_config()

    def update_enhancement_summary(self, status):
        if status.can_load and status.runtime_verified:
            title = "增强识别已就绪"
            detail = "复杂码与异形码增强已启用"
            state = "ready"
        elif status.installed and status.can_load:
            title = "增强包待验证"
            detail = "基础识别当前可正常使用"
            state = "warning"
        elif status.installed:
            title = "增强包不完整"
            detail = "已自动回退到基础识别"
            state = "error"
        else:
            title = "基础识别可用"
            detail = "可按需导入增强能力"
            state = "ready"

        self.sidebar_status_title.setText(title)
        self.sidebar_status_detail.setText(detail)
        self.sidebar_status_dot.setProperty("state", state)
        self.sidebar_status_dot.style().unpolish(self.sidebar_status_dot)
        self.sidebar_status_dot.style().polish(self.sidebar_status_dot)

    def start_hotkey_listener(self):
        import keyboard

        # 注销旧热键
        if hasattr(self, "hotkey_handle") and self.hotkey_handle:
            try:
                keyboard.remove_hotkey(self.hotkey_handle)
                print("Old hotkey removed")
            except:
                pass
            self.hotkey_handle = None

        hk = self.hotkey or self.config.get("hotkey", "")
        if not hk:
            return

        try:

            # 改为在回调中 emit 一个 Qt 信号，信号会在 GUI 线程触发 start_capture
            self.hotkey_handle = keyboard.add_hotkey(hk, lambda: self.hotkey_triggered.emit())
            print("Hotkey registered:", hk)
        except Exception as e:
            print("Hotkey registration failed:", e)

    def save_hotkey(self):
        hk = self.hotkey_input.text().strip()
        if hk == "":
            QMessageBox.warning(self, "错误", "快捷键不能为空")
            return
        self.config["hotkey"] = hk
        # json.dump({"hotkey": hk}, open(resource_path(CONFIG_FILE), "w", encoding="utf8"))
        self.save_config()
        self.hotkey = hk
        self.start_hotkey_listener()
        QMessageBox.information(self, "成功", f"已保存快捷键：{hk}")

    def update_decode_preview(self):
        """按预览控件的物理像素缩放，避免高 DPI 下二次放大造成模糊。"""
        if not hasattr(self, "_orig_decode_pixmap"):
            return

        pix = self._orig_decode_pixmap
        label = self.decode_preview

        # 如果 label 还没 layout 好（size 为 0），稍后重试
        if label.width() == 0 or label.height() == 0:
            QTimer.singleShot(100, self.update_decode_preview)
            return

        image = pix.toImage()
        image.setDevicePixelRatio(1.0)
        source_pix = QPixmap.fromImage(image)

        screen = label.screen() or self.screen()
        display_dpr = screen.devicePixelRatio() if screen else 1.0
        max_width = max(1, round(label.width() * display_dpr))
        max_height = max(1, round(label.height() * display_dpr))
        # 预览只允许缩小，不把截图放大到超过原始物理像素。
        # 小范围框选会以像素等比例大小居中显示，从根源上避免插值模糊。
        scale = min(
            max_width / source_pix.width(),
            max_height / source_pix.height(),
            1.0
        )
        target_width = max(1, round(source_pix.width() * scale))
        target_height = max(1, round(source_pix.height() * scale))
        scaled = source_pix.scaled(
            target_width,
            target_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        scaled.setDevicePixelRatio(display_dpr)
        label.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_qr_preview()
        self.update_decode_preview()

    def on_page_changed(self, index: int):
        if index == 1 and hasattr(self, "decode_text"):
            QTimer.singleShot(0, self.update_decode_text_size)
            QTimer.singleShot(0, self.update_decode_preview)

    def showEvent(self, event):
        super().showEvent(event)
        self.update_native_titlebar()

    def eventFilter(self, watched, event):
        event_type = event.type()
        if (
            hasattr(self, "_model_preload_idle_timer")
            and not self.recognition.optional_model_preload_started
            and event_type in (
                QEvent.Type.KeyPress,
                QEvent.Type.MouseButtonPress,
                QEvent.Type.TouchBegin,
                QEvent.Type.Wheel,
            )
        ):
            self._model_preload_idle_timer.start()

        if (
            isinstance(watched, QWidget)
            and (watched is self or self.isAncestorOf(watched))
            and event_type in (
                QEvent.Type.DragEnter,
                QEvent.Type.DragMove,
                QEvent.Type.Drop,
            )
        ):
            image_path = image_path_from_mime_data(event.mimeData())
            if image_path and not self._decode_busy:
                event.acceptProposedAction()
                if event_type == QEvent.Type.Drop:
                    self.open_decode_path(image_path)
                return True

        if (
            isinstance(watched, QMessageBox)
            and event_type in (
                QEvent.Type.Polish,
                QEvent.Type.Show,
            )
            and hasattr(self, "_system_icon")
        ):
            watched.setWindowIcon(self._system_icon)
        return super().eventFilter(watched, event)

    # ==========================
    #        历史记录
    # ==========================
    def load_history(self):
        """加载历史记录，兼容新旧格式"""
        if os.path.exists(resource_path(HISTORY_FILE)):
            try:
                history = json.load(open(resource_path(HISTORY_FILE), "r", encoding="utf8"))
                # 兼容旧格式：将旧格式转换为新格式
                converted_history = []
                for item in history:
                    if isinstance(item, dict) and "source" in item and "content" in item:
                        # 已经是新格式
                        converted_history.append(item)
                    else:
                        # 旧格式，尝试转换
                        if isinstance(item, dict) and "text" in item:
                            text = item["text"]
                            time = item.get("time", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                            # 解析旧格式文本
                            if "截屏识别：" in text:
                                source = "截屏识别"
                                content = text.replace("截屏识别：", "")
                            elif "解析图片：" in text:
                                source = "解析图片"
                                content = text.replace("解析图片：", "")
                            elif "生成：" in text:
                                source = "生成"
                                content = text.replace("生成：", "")
                            else:
                                source = "未知"
                                content = text
                            converted_history.append({
                                "source": source,
                                "content": content,
                                "time": time
                            })
                return converted_history
            except:
                return []
        return []

    def save_history(self):
        json.dump(self.history, open(resource_path(HISTORY_FILE), "w", encoding="utf8"),
                  ensure_ascii=False, indent=2)

    def add_history(self, source, content):
        """添加历史记录，分开存储来源和内容"""
        self.history.append({
            "source": source,
            "content": content,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        self.save_history()
        self.refresh_history()

    def page_history(self):
        w = QWidget()
        w.setObjectName("pageContent")
        v = QVBoxLayout(w)
        v.setContentsMargins(30, 28, 30, 30)
        v.setSpacing(22)
        v.addWidget(PageHeader(
            "历史记录",
            "查看生成和识别过的内容；右击直接复制，双击可打开链接或复制普通文本。",
        ))

        card = Card()
        h = QHBoxLayout()
        self.chk_all = ThemedCheckBox("全选")
        # 允许显示部分选中状态（程序可以显示 PartiallyChecked）
        self.chk_all.setTristate(True)
        # 使用 clicked(bool) —— 只在用户点击时触发（区分程序性修改）
        self.chk_all.clicked.connect(self.toggle_all)
        h.addWidget(self.chk_all)
        self.history_count_label = QLabel()
        self.history_count_label.setObjectName("mutedText")
        h.addWidget(self.history_count_label)
        h.addStretch(1)

        btn_del = QPushButton("删除选中")
        btn_del.setProperty("danger", True)
        btn_del.clicked.connect(self.delete_selected)
        h.addWidget(btn_del)

        card.body.addLayout(h)

        self.list = QListWidget()
        self.list.setObjectName("historyList")
        self.list.setItemDelegate(ThemedCheckItemDelegate(self.list))
        self.list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        # 使用 itemChanged 信号处理勾选，避免与点击事件冲突
        self.list.itemChanged.connect(self.on_item_changed)

        # 双击打开链接（只在双击时打开，避免勾选时触发）
        self.list.itemDoubleClicked.connect(self.on_history_double_click)

        # 右键菜单
        self.list.customContextMenuRequested.connect(self.on_history_right_click)

        card.body.addWidget(self.list, stretch=1)
        v.addWidget(card, stretch=1)

        self.refresh_history()
        return w

    def page_hotkey(self):
        w = QWidget()
        w.setObjectName("pageContent")
        v = QVBoxLayout(w)
        v.setContentsMargins(30, 28, 30, 30)
        v.setSpacing(22)
        v.addWidget(PageHeader(
            "快捷键设置",
            "设置一个全局快捷键，在任何窗口中都能快速进入截屏识别。",
        ))

        card = Card()
        card.setMaximumWidth(680)
        card.body.addWidget(section_label("截屏识别快捷键"))
        card.body.addWidget(helper_label(
            "点击下方输入框后直接按下组合键，例如 F1 或 Ctrl + Shift + S。"
        ))
        h = QHBoxLayout()
        h.setSpacing(12)
        self.hotkey_input = QLineEdit()
        self.hotkey_input.setPlaceholderText("按下希望使用的快捷键")
        h.addWidget(self.hotkey_input)

        save_btn = QPushButton("保存快捷键")
        save_btn.setProperty("primary", True)
        save_btn.clicked.connect(self.save_hotkey)
        h.addWidget(save_btn)

        card.body.addLayout(h)
        tip = helper_label(
            "提示：程序最小化到系统托盘后快捷键仍然有效。若与其他软件冲突，"
            "请更换组合键。"
        )
        card.body.addWidget(tip)
        v.addWidget(card)
        v.addStretch(1)

        # 读取已保存热键
        self.hotkey = self.config.get("hotkey", "")
        if self.hotkey:
            self.hotkey_input.setText(self.hotkey)

        # 监听键盘记录快捷键（只记录组合，不实际触发）
        self.hotkey_input.keyPressEvent = self.record_hotkey

        return w

    def refresh_history(self):
        if not hasattr(self, "list"):
            return
        self.list.clear()

        # 暂停 itemChanged 信号，避免刷新时触发
        self.list.blockSignals(True)

        for h in reversed(self.history):
            # 显示格式：时间 - [来源] 内容
            display_text = f"{h['time']} - [{h['source']}] {h['content']}"
            item = QListWidgetItem(display_text)

            # 设置可勾选
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)

            # 保存原始数据到自定义数据角色
            item.setData(Qt.ItemDataRole.UserRole, h)

            self.list.addItem(item)

        # 恢复信号
        self.list.blockSignals(False)

        # 更新全选复选框状态
        self.update_select_all_checkbox()
        if hasattr(self, "history_count_label"):
            self.history_count_label.setText(f"共 {len(self.history)} 条")

    def on_item_changed(self, item):
        """处理项目状态变化（勾选/取消勾选）"""
        # 更新全选复选框状态
        self.update_select_all_checkbox()

    def record_hotkey(self, e):
        keys = []

        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            keys.append("ctrl")
        if e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            keys.append("shift")
        if e.modifiers() & Qt.KeyboardModifier.AltModifier:
            keys.append("alt")

        key = e.key()

        # 处理 F1-F12
        if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F35:
            keys.append(f"f{key - Qt.Key.Key_F1 + 1}")
        else:
            key_name = e.text().lower()
            if key_name:
                keys.append(key_name)

        self.hotkey_input.setText("+".join(keys))

    def update_select_all_checkbox(self):
        """程序性更新 chk_all 的显示（不会被当成用户点击）"""
        count = self.list.count()
        if count == 0:
            self.chk_all.blockSignals(True)
            self.chk_all.setCheckState(Qt.CheckState.Unchecked)
            self.chk_all.blockSignals(False)
            self.chk_all.setEnabled(False)
            return

        self.chk_all.setEnabled(True)

        checked_count = 0
        for i in range(count):
            if self.list.item(i).checkState() == Qt.CheckState.Checked:
                checked_count += 1

        # 程序性设置 chk_all 的显示时阻断信号，避免触发 toggle_all
        self.chk_all.blockSignals(True)

        if checked_count == 0:
            self.chk_all.setCheckState(Qt.CheckState.Unchecked)
        elif checked_count == count:
            self.chk_all.setCheckState(Qt.CheckState.Checked)
        else:
            self.chk_all.setCheckState(Qt.CheckState.PartiallyChecked)

        self.chk_all.blockSignals(False)

    # noinspection PyUnreachableCode
    def toggle_all(self, checked):
        """只在用户点击全选复选框时调用（checked 为用户点击后的状态）"""
        # 1) 阻断 list 的 itemChanged 信号，避免每次 item.setCheckState 触发 update_select_all_checkbox
        self.list.blockSignals(True)
        try:
            for i in range(self.list.count()):
                item = self.list.item(i)
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        finally:
            self.list.blockSignals(False)

        # 2) 明确把 chk_all 设置为用户想要的状态，临时阻断其信号以避免重复触发

        self.chk_all.blockSignals(True)
        self.chk_all.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.chk_all.blockSignals(False)


    def delete_selected(self):
        """删除选中的记录"""
        items_to_delete = []

        # 收集要删除的项目
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                # 获取对应的历史记录索引（因为显示是倒序的）
                history_index = len(self.history) - 1 - i
                items_to_delete.append(history_index)

        if not items_to_delete:
            QMessageBox.information(self, "提示", "没有选中任何记录")
            return

        # 从后往前删除，避免索引变化
        items_to_delete.sort(reverse=True)
        for idx in items_to_delete:
            if 0 <= idx < len(self.history):
                del self.history[idx]

        self.save_history()
        self.refresh_history()

    # 双击历史项：如果包含 URL -> 打开
    def on_history_double_click(self, item: QListWidgetItem):
        """双击项目时打开链接"""
        data = item.data(Qt.ItemDataRole.UserRole)
        if data and "content" in data:
            content = data["content"]
            url = extract_first_url(content)
            if url:
                webbrowser.open(url)
            else:
                # 如果不是URL，复制到剪贴板
                QApplication.clipboard().setText(content)
                QMessageBox.information(self, "已复制", "内容已复制到剪贴板")

    # 右键点击历史项：复制内容（不含前缀）
    def on_history_right_click(self, pos):
        """右键菜单：复制内容"""
        item = self.list.itemAt(pos)
        if not item:
            return

        # 从自定义数据中获取原始内容
        data = item.data(Qt.ItemDataRole.UserRole)
        if data and "content" in data:
            content = data["content"]
            QApplication.clipboard().setText(content)

            # 显示简短提示
            if len(content) > 30:
                display_content = content[:27] + "..."
            else:
                display_content = content

            # 使用系统托盘显示消息（避免打断用户操作）
            if hasattr(self, 'tray'):
                self.tray.showMessage(
                    "已复制",
                    f"内容已复制到剪贴板：\n{display_content}",
                    QSystemTrayIcon.MessageIcon.Information,
                    1500
                )

    # ==========================
    #        生成二维码
    # ==========================
    def page_generate(self):
        w = QWidget()
        w.setObjectName("pageContent")
        v = QVBoxLayout(w)
        v.setContentsMargins(30, 28, 30, 30)
        v.setSpacing(22)
        v.addWidget(PageHeader(
            "生成二维码",
            "输入文本、链接或其他内容，即时生成清晰的二维码图片。",
        ))

        columns = QHBoxLayout()
        columns.setSpacing(18)
        input_card = Card()
        input_card.body.addWidget(section_label("二维码内容"))
        input_card.body.addWidget(helper_label(
            "支持网址、文本、联系方式等内容。"
        ))
        self.input_text = QTextEdit()
        self.input_text.setPlaceholderText("在这里输入需要编码的内容…")
        self.input_text.setMinimumHeight(160)
        input_card.body.addWidget(self.input_text, stretch=1)

        btn = QPushButton("生成二维码")
        btn.setProperty("primary", True)
        btn.clicked.connect(self.generate_qr)
        input_card.body.addWidget(btn)
        columns.addWidget(input_card, stretch=1)

        preview_card = Card()
        preview_card.body.addWidget(section_label("实时预览"))
        self.qr_label = StablePixmapLabel(
            "输入内容并点击“生成二维码”",
            preferred_size=QSize(180, 180),
        )
        self.qr_label.setObjectName("qrPreview")
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_card.body.addWidget(self.qr_label, stretch=1)

        self.save_qr_btn = QPushButton("保存为 PNG")
        self.save_qr_btn.setEnabled(False)
        self.save_qr_btn.clicked.connect(self.save_qr)
        preview_card.body.addWidget(self.save_qr_btn)
        columns.addWidget(preview_card, stretch=1)

        v.addLayout(columns, stretch=1)
        return w

    def generate_qr(self):
        text = self.input_text.toPlainText().strip()
        if not text:
            return

        import qrcode

        qr = qrcode.main.QRCode(box_size=8, border=2)
        qr.add_data(text)
        qr.make()
        matrix = qr.get_matrix()
        module_size = 8
        image_size = len(matrix) * module_size
        self.qr_image = QImage(
            image_size,
            image_size,
            QImage.Format.Format_RGB32,
        )
        self.qr_image.fill(Qt.GlobalColor.white)
        painter = QPainter(self.qr_image)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(Qt.GlobalColor.black)
        for row_index, row in enumerate(matrix):
            for column_index, enabled in enumerate(row):
                if enabled:
                    painter.drawRect(
                        column_index * module_size,
                        row_index * module_size,
                        module_size,
                        module_size,
                    )
        painter.end()

        self.update_qr_preview()
        self.save_qr_btn.setEnabled(True)

        # 修改：使用新格式添加历史记录
        self.add_history("生成", text)

    def save_qr(self):
        if not hasattr(self, "qr_image"):
            return
        fn, _ = QFileDialog.getSaveFileName(self, "保存二维码", filter="PNG (*.png)")
        if fn:
            self.qr_image.save(fn, "PNG")

    def update_qr_preview(self):
        if not hasattr(self, "qr_image") or not hasattr(self, "qr_label"):
            return
        if self.qr_label.width() <= 0 or self.qr_label.height() <= 0:
            return
        pixmap = QPixmap.fromImage(self.qr_image)
        self.qr_label.setPixmap(
            pixmap.scaled(
                self.qr_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
        )

    # ==========================
    #        解析二维码
    # ==========================
    def page_decode(self):
        w = QWidget()
        w.setObjectName("pageContent")
        v = QVBoxLayout(w)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(12)
        v.addWidget(PageHeader(
            "识别二维码",
            "从图片或任意显示器截取区域，程序会自动选择合适的识别方式。",
        ))

        actions_card = Card(compact=True)
        actions = QHBoxLayout()
        actions.setSpacing(12)
        self.decode_file_btn = QPushButton("选择图片解析")
        self.decode_file_btn.clicked.connect(self.open_decode)
        actions.addWidget(self.decode_file_btn)

        self.capture_btn = QPushButton("截屏识别")
        self.capture_btn.setProperty("primary", True)
        self.capture_btn.clicked.connect(self.start_capture)
        actions.addWidget(self.capture_btn)
        actions.addStretch(1)
        actions_card.body.addLayout(actions)
        v.addWidget(actions_card)

        preview_card = Card(compact=True)
        preview_head = QHBoxLayout()
        preview_head.addWidget(section_label("图片预览"))
        preview_head.addStretch(1)
        preview_card.body.addLayout(preview_head)
        self.decode_preview = StablePixmapLabel(
            "选择图片、拖入图片或截取屏幕区域后，将在这里显示预览",
            preferred_size=QSize(200, 90),
        )
        self.decode_preview.setObjectName("decodePreview")
        self.decode_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.decode_preview.setScaledContents(False)
        preview_card.body.addWidget(self.decode_preview, stretch=1)
        v.addWidget(preview_card, stretch=1)

        result_card = Card(compact=True)
        result_head = QHBoxLayout()
        result_head.addWidget(section_label("识别结果"))
        result_head.addStretch(1)
        result_head.addWidget(helper_label("点击链接可打开，点击文本可复制"))
        result_card.body.addLayout(result_head)
        self.decode_text = QTextEdit()
        self.decode_text.setObjectName("decodeResult")
        self.decode_text.setReadOnly(True)
        self.decode_text.setPlaceholderText("识别结果将在这里显示")
        self.decode_text.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        self.decode_text.setMinimumHeight(64)
        self.decode_text.setMaximumHeight(240)
        self.decode_text.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.decode_text.setLineWrapMode(
            QTextEdit.LineWrapMode.WidgetWidth
        )
        self.decode_text.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        self.decode_text.mousePressEvent = self.open_link_if_needed

        # 监听文本变化
        self.decode_text.textChanged.connect(self.update_decode_text_size)

        result_card.body.addWidget(self.decode_text)
        v.addWidget(result_card)

        return w

    def update_decode_text_size(self):
        """根据文本内容更新decode_text的大小"""
        # 获取文档的理想高度
        doc_height = self.decode_text.document().size().height()

        # 加上一些边距（大约20像素）
        needed_height = doc_height + 20

        # 内容较少时保持紧凑；内容较多时由文本框内部滚动。
        preferred_height = max(64, min(240, int(needed_height)))
        self.decode_text.setMaximumHeight(preferred_height)

        # 强制更新布局，确保图片预览区域能重新计算可用空间
        self.decode_text.updateGeometry()
        if self.decode_preview.parent():
            self.decode_preview.parent().updateGeometry()

    def show_decode_message(self, message: str, tone: str = "muted"):
        self._decode_render_state = ("message", message, tone)
        self.decode_text.setHtml(
            render_decode_message_html(message, self.theme, tone)
        )
        QTimer.singleShot(0, self.update_decode_text_size)

    def show_decode_results(self, texts):
        values = tuple(texts)
        self._decode_render_state = ("results", values)
        self.decode_text.setHtml(
            render_decode_results_html(values, self.theme)
        )
        QTimer.singleShot(0, self.update_decode_text_size)

    def refresh_decode_theme(self):
        if not hasattr(self, "decode_text") or not self._decode_render_state:
            return

        kind, *payload = self._decode_render_state
        if kind == "message":
            self.decode_text.setHtml(
                render_decode_message_html(
                    payload[0],
                    self.theme,
                    payload[1],
                )
            )
        elif kind == "results":
            self.decode_text.setHtml(
                render_decode_results_html(payload[0], self.theme)
            )
        elif kind == "plain":
            self.decode_text.setPlainText(payload[0])
        QTimer.singleShot(0, self.update_decode_text_size)

    # 点击可打开 URL
    def open_link_if_needed(self, e):
        try:
            pos = e.position().toPoint()
        except Exception:
            pos = e.pos()
        cursor = self.decode_text.cursorForPosition(pos)

        fmt = cursor.charFormat()
        href = fmt.anchorHref()

        if href:
            # 如果点中 HTML 链接（<a href="...">）
            webbrowser.open(href)
            return

        # 没点到链接，则复制文字
        cursor.select(cursor.SelectionType.WordUnderCursor)
        text = cursor.selectedText().strip()
        QApplication.clipboard().setText(text)

    def open_decode(self):
        if self._decode_busy:
            return

        fn, _ = QFileDialog.getOpenFileName(self, "选择图片", filter="Images (*.png *.jpg *.jpeg)")
        if not fn:
            return

        self.open_decode_path(fn)

    def open_decode_path(self, filename: str) -> bool:
        """Load an image selected from a dialog or dropped on the window."""
        if self._decode_busy:
            return False

        pix = QPixmap(filename)
        if pix.isNull():
            QMessageBox.warning(
                self,
                "无法读取图片",
                "该文件不是受支持的图片，或文件内容已经损坏。",
            )
            return False

        self.navigation.setCurrentRow(1)
        self._orig_decode_pixmap = pix
        self.update_decode_preview()
        self.start_decode(pix.toImage(), "解析图片")
        return True

    # ==========================
    #         截屏识别
    # ==========================
    def start_capture(self):
        if self._decode_busy or self._capture_pending or self.cap is not None:
            return

        self._capture_window_mode = window_display_mode(self)
        # 切换到“识别二维码”页面，并同步左侧导航状态。
        self.navigation.setCurrentRow(1)
        self._capture_pending = True
        self.hide()
        QApplication.processEvents()

        # 给 Windows 合成器留出隐藏主窗口的时间，防止截图中残留本程序窗口。
        QTimer.singleShot(150, self._show_capture_overlay)

    def _show_capture_overlay(self):
        try:
            self.cap = CaptureScreen(self.on_capture, self.on_capture_cancel)
            self.cap.show()
            self.cap.raise_()
            self.cap.activateWindow()
        except Exception:
            self._capture_pending = False
            self.restore_after_capture()
            raise
        self._capture_pending = False

    def on_capture_cancel(self):
        self._capture_pending = False
        self.cap = None
        self.restore_after_capture()

    # ---------- on_capture：把 singleShot(0) 改成短延迟，保证窗口恢复并布局完成 ----------
    def on_capture(self, pixmap):
        self.cap = None
        self._orig_decode_pixmap = pixmap
        decode_image = pixmap.toImage()
        # 主窗口仍隐藏时先完成预览缩放和状态布局，再一次性恢复，避免白屏。
        self.update_decode_preview()
        self.show_decode_message("正在识别二维码…")
        self.restore_after_capture()
        # 让恢复后的窗口先获得一次绘制机会，再把任务放入后台执行器。
        QTimer.singleShot(
            30,
            lambda image=decode_image: self.start_decode(image, "截屏识别")
        )


    def start_decode(self, image, source):
        """启动固定的自动识别流水线，所有耗时操作均在后台线程执行。"""
        if self._decode_busy:
            return

        self._decode_busy = True
        status = (
            "正在完成识别引擎预加载…"
            if self.recognition.preload_running
            else "正在快速识别…"
        )
        self.show_decode_message(status)
        self.decode_file_btn.setEnabled(False)
        self.capture_btn.setEnabled(False)
        if hasattr(self, "cap_act"):
            self.cap_act.setEnabled(False)

        self._decode_request_id = self.recognition.submit(image, source)

    def on_decode_progress(self, request_id, message):
        if request_id == self._decode_request_id:
            self.show_decode_message(message)

    def on_decode_finished(self, request_id, texts, source, error):
        self.recognition.discard_request(request_id)
        if request_id != self._decode_request_id:
            return

        self._decode_busy = False
        self.decode_file_btn.setEnabled(True)
        self.capture_btn.setEnabled(True)
        if hasattr(self, "cap_act"):
            self.cap_act.setEnabled(True)

        if error:
            self.show_decode_message(f"识别失败：{error}", "error")
            return

        texts = self.recognition.unique_texts(texts or ())
        if not texts:
            self.show_decode_message(
                "未识别出二维码或受支持的条码"
            )
            return

        self.show_decode_results(texts)

        for text in texts:
            self.add_history(source, text)

    def show_decode_text(self, text, src):
        self._decode_render_state = ("plain", text)
        self.decode_text.setPlainText(text)

    # ==========================
    #        系统托盘（稳健版）
    # ==========================
    def init_tray(self):
        self.tray = QSystemTrayIcon(parent=self)
        self.update_system_icons()
        self.tray.setToolTip("二维码工具（右键）")

        # 3) 创建菜单并保存为实例属性（防止 GC）
        self.tray_menu = QMenu(parent=self)

        self.show_act = QAction("显示主窗口", parent=self)
        # self.show_act.triggered.connect(self.show)
        self.show_act.triggered.connect(self.show_main_window)

        self.tray_menu.addAction(self.show_act)

        self.cap_act = QAction("截屏识别", parent=self)
        self.cap_act.triggered.connect(self.start_capture)
        self.tray_menu.addAction(self.cap_act)

        self.quit_act = QAction("退出", parent=self)
        # self.quit_act.triggered.connect(QApplication.quit)

        self.quit_act.triggered.connect(self.force_quit)
        self.tray_menu.addAction(self.quit_act)


        # 4) 设置托盘上下文菜单
        self.tray.setContextMenu(self.tray_menu)

        # 5) 设置双击托盘打开界面
        self.tray.activated.connect(self.on_tray_activated)

        # 6) 显示托盘图标
        self.tray.show()

        style_hints = QApplication.instance().styleHints()
        try:
            style_hints.colorSchemeChanged.connect(
                self.on_system_color_scheme_changed
            )
        except AttributeError:
            pass

    def update_system_icons(self):
        icon_theme = detect_system_tray_theme(self.theme)
        if getattr(self, "_system_icon_theme", None) != icon_theme:
            self._system_icon_theme = icon_theme
            self._system_icon = themed_tray_icon(icon_theme)

        application = QApplication.instance()
        application.setWindowIcon(self._system_icon)
        self.setWindowIcon(self._system_icon)

        if hasattr(self, "tray"):
            self.tray.setIcon(self._system_icon)
        for widget in application.topLevelWidgets():
            if isinstance(widget, QMessageBox):
                widget.setWindowIcon(self._system_icon)

    def on_system_color_scheme_changed(self, _scheme):
        # Windows 切换系统主题后，注册表值与 Qt 通知可能存在短暂时序差。
        QTimer.singleShot(100, self.update_system_icons)

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_main_window()


    def show_main_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def restore_after_capture(self):
        mode = self._capture_window_mode
        self._capture_window_mode = "normal"
        restore_window_display_mode(self, mode)
        self.raise_()
        self.activateWindow()

    def force_quit(self):
        self._force_quit = True
        self.tray.hide()
        self.enhancement_page.shutdown()
        self.recognition.shutdown()
        QApplication.quit()

    def closeEvent(self, e):
        if getattr(self, "_force_quit", False):
            e.accept()
            return

        e.ignore()
        self.hide()
        self.tray.showMessage(
            "二维码工具",
            "程序已最小化到系统托盘",
            QSystemTrayIcon.MessageIcon.Information,
            2000
        )

def run() -> int:
    app = QApplication(sys.argv)
    window = QRApp()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
