import sys
import os
import json
from io import BytesIO
from datetime import datetime
import webbrowser
import re
import cv2
import numpy as np
import qrcode

from PySide6.QtWidgets import (
    QApplication, QWidget, QTabWidget, QVBoxLayout, QLabel, QPushButton,
    QTextEdit, QFileDialog, QLineEdit, QSystemTrayIcon, QStyle, QMenu,
    QListWidget, QListWidgetItem, QMessageBox, QHBoxLayout, QCheckBox
)
from PySide6.QtGui import (
    QPixmap, QAction, QGuiApplication, QPainter, QPen, QColor, QImage, QIcon, QCursor
)
from PySide6.QtCore import Qt, QRect, QPoint

# ---------- 常量 ----------
HISTORY_FILE = "history.json"

# ---------- 正则：识别文本中的第一个 URL（支持不带 scheme 的裸域名 / www） ----------
_url_re = re.compile(
    r"""(?xi)
    (
      (?:https?://[^\s'"]+) |                     # 带 http(s) 的完整 URL
      (?:www\.[^\s'"]+) |                         # 以 www. 开头的
      (?:[a-z0-9\-.]+\.(?:com|net|org|io|gov|cn|xyz|top|info|biz|site|tech|me)(?:/[^\s'"]*)?) # 裸域名+常见TLD（带可选路径）
    )
    """
)
def resource_path(relative_path):
    """获取打包后资源的正确路径"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

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


# ================================
#       截图框选窗口（高 DPI 修复）
# ================================
class CaptureScreen(QWidget):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback

        self.setWindowFlag(Qt.FramelessWindowHint)
        self.setWindowState(Qt.WindowFullScreen)
        self.setCursor(Qt.CrossCursor)

        screen = QGuiApplication.primaryScreen()
        self.dpr = screen.devicePixelRatio()

        self.full_pix = screen.grabWindow(0)

        self.start = QPoint()
        self.end = QPoint()
        self.selecting = False

    def paintEvent(self, event):
        p = QPainter(self)
        p.drawPixmap(0, 0, self.full_pix)

        if self.selecting:
            rect = QRect(self.start, self.end).normalized()
            p.setPen(QPen(QColor(0, 180, 255), 3))
            p.drawRect(rect)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            # Qt 6: e.position(); Qt 5: e.pos()
            try:
                p = e.position().toPoint()
            except Exception:
                p = e.pos()
            self.start = p
            self.end = p
            self.selecting = True
            self.update()

    def mouseMoveEvent(self, e):
        if self.selecting:
            try:
                self.end = e.position().toPoint()
            except Exception:
                self.end = e.pos()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.selecting = False
            try:
                self.end = e.position().toPoint()
            except Exception:
                self.end = e.pos()

            rect = QRect(self.start, self.end).normalized()
            if rect.width() > 5 and rect.height() > 5:
                real_rect = QRect(
                    int(rect.x() * self.dpr),
                    int(rect.y() * self.dpr),
                    int(rect.width() * self.dpr),
                    int(rect.height() * self.dpr)
                )

                cropped = self.full_pix.copy(real_rect)
                self.callback(cropped)

            self.close()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()


# ================================
#           主程序
# ================================
class QRApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("二维码工具  By Null993")
        self.resize(700, 520)

        self.detector = cv2.QRCodeDetector()
        self.history = self.load_history()

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.tabs.addTab(self.page_generate(), "生成二维码")
        self.tabs.addTab(self.page_decode(), "解析二维码")
        self.tabs.addTab(self.page_history(), "历史记录")

        self.init_tray()

    # ==========================
    #        历史记录
    # ==========================
    def load_history(self):
        """加载历史记录，兼容新旧格式"""
        if os.path.exists(HISTORY_FILE):
            try:
                history = json.load(open(HISTORY_FILE, "r", encoding="utf8"))
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
        json.dump(self.history, open(HISTORY_FILE, "w", encoding="utf8"),
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
        v = QVBoxLayout(w)

        # 顶部按钮
        h = QHBoxLayout()
        self.chk_all = QCheckBox("全选")
        # 允许显示部分选中状态（程序可以显示 PartiallyChecked）
        self.chk_all.setTristate(True)
        # 使用 clicked(bool) —— 只在用户点击时触发（区分程序性修改）
        self.chk_all.clicked.connect(self.toggle_all)
        h.addWidget(self.chk_all)

        btn_del = QPushButton("删除选中")
        btn_del.clicked.connect(self.delete_selected)
        h.addWidget(btn_del)

        v.addLayout(h)

        self.list = QListWidget()
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)

        # 使用 itemChanged 信号处理勾选，避免与点击事件冲突
        self.list.itemChanged.connect(self.on_item_changed)

        # 双击打开链接（只在双击时打开，避免勾选时触发）
        self.list.itemDoubleClicked.connect(self.on_history_double_click)

        # 右键菜单
        self.list.customContextMenuRequested.connect(self.on_history_right_click)

        v.addWidget(self.list)

        self.refresh_history()
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
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)

            # 保存原始数据到自定义数据角色
            item.setData(Qt.UserRole, h)

            self.list.addItem(item)

        # 恢复信号
        self.list.blockSignals(False)

        # 更新全选复选框状态
        self.update_select_all_checkbox()

    def on_item_changed(self, item):
        """处理项目状态变化（勾选/取消勾选）"""
        # 更新全选复选框状态
        self.update_select_all_checkbox()

    def update_select_all_checkbox(self):
        """程序性更新 chk_all 的显示（不会被当成用户点击）"""
        count = self.list.count()
        if count == 0:
            self.chk_all.blockSignals(True)
            self.chk_all.setCheckState(Qt.Unchecked)
            self.chk_all.blockSignals(False)
            self.chk_all.setEnabled(False)
            return

        self.chk_all.setEnabled(True)

        checked_count = 0
        for i in range(count):
            if self.list.item(i).checkState() == Qt.Checked:
                checked_count += 1

        # 程序性设置 chk_all 的显示时阻断信号，避免触发 toggle_all
        self.chk_all.blockSignals(True)

        if checked_count == 0:
            self.chk_all.setCheckState(Qt.Unchecked)
        elif checked_count == count:
            self.chk_all.setCheckState(Qt.Checked)
        else:
            self.chk_all.setCheckState(Qt.PartiallyChecked)

        self.chk_all.blockSignals(False)

    def toggle_all(self, checked):
        """只在用户点击全选复选框时调用（checked 为用户点击后的状态）"""
        # 1) 阻断 list 的 itemChanged 信号，避免每次 item.setCheckState 触发 update_select_all_checkbox
        self.list.blockSignals(True)
        try:
            for i in range(self.list.count()):
                item = self.list.item(i)
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        finally:
            self.list.blockSignals(False)

        # 2) 明确把 chk_all 设置为用户想要的状态，临时阻断其信号以避免重复触发
        self.chk_all.blockSignals(True)
        self.chk_all.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self.chk_all.blockSignals(False)
    def delete_selected(self):
        """删除选中的记录"""
        items_to_delete = []

        # 收集要删除的项目
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.checkState() == Qt.Checked:
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
        data = item.data(Qt.UserRole)
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
        data = item.data(Qt.UserRole)
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
                    QSystemTrayIcon.Information,
                    1500
                )

    # ==========================
    #        生成二维码
    # ==========================
    def page_generate(self):
        w = QWidget()
        v = QVBoxLayout(w)

        self.input_text = QTextEdit()
        self.input_text.setPlaceholderText("输入内容")
        v.addWidget(self.input_text)

        btn = QPushButton("生成二维码")
        btn.clicked.connect(self.generate_qr)
        v.addWidget(btn)

        self.qr_label = QLabel("二维码预览")
        self.qr_label.setAlignment(Qt.AlignCenter)
        v.addWidget(self.qr_label)

        save = QPushButton("保存二维码")
        save.clicked.connect(self.save_qr)
        v.addWidget(save)

        return w

    def generate_qr(self):
        text = self.input_text.toPlainText().strip()
        if not text:
            return

        qr = qrcode.QRCode(box_size=8, border=2)
        qr.add_data(text)
        qr.make()
        img = qr.make_image()

        buf = BytesIO()
        img.save(buf, format="PNG")
        self.qr_data = buf.getvalue()

        pix = QPixmap()
        pix.loadFromData(self.qr_data)
        self.qr_label.setPixmap(pix.scaled(300, 300, Qt.KeepAspectRatio))

        # 修改：使用新格式添加历史记录
        self.add_history("生成", text)

    def save_qr(self):
        if not hasattr(self, "qr_data"):
            return
        fn, _ = QFileDialog.getSaveFileName(self, "保存二维码", filter="PNG (*.png)")
        if fn:
            open(fn, "wb").write(self.qr_data)

    # ==========================
    #        解析二维码
    # ==========================
    def page_decode(self):
        w = QWidget()
        v = QVBoxLayout(w)

        btn = QPushButton("选择图片解析")
        btn.clicked.connect(self.open_decode)
        v.addWidget(btn)

        cap_btn = QPushButton("截屏识别")
        cap_btn.clicked.connect(self.start_capture)
        v.addWidget(cap_btn)

        self.decode_preview = QLabel("图片预览")
        self.decode_preview.setAlignment(Qt.AlignCenter)
        v.addWidget(self.decode_preview)

        self.decode_text = QLineEdit()
        self.decode_text.setReadOnly(True)
        self.decode_text.setStyleSheet("color:blue; text-decoration: underline;")
        self.decode_text.mousePressEvent = self.open_link_if_needed
        v.addWidget(self.decode_text)

        return w

    # 点击可打开 URL
    def open_link_if_needed(self, e):
        text = self.decode_text.text()
        if text.startswith("http://") or text.startswith("https://"):
            webbrowser.open(text)
        else:
            QApplication.clipboard().setText(text)

    def open_decode(self):
        fn, _ = QFileDialog.getOpenFileName(self, "选择图片", filter="Images (*.png *.jpg *.jpeg)")
        if not fn:
            return

        pix = QPixmap(fn)
        self.decode_preview.setPixmap(pix.scaled(300, 260, Qt.KeepAspectRatio))

        text = self.decode_file(fn)
        if text:
            self.show_decode_text(text, src="解析图片")
        else:
            self.decode_text.setText("未识别到二维码")

    def decode_file(self, fn):
        img = cv2.imdecode(np.fromfile(fn, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return None
        text, pts, _ = self.detector.detectAndDecode(img)
        return text or None

    # ==========================
    #         截屏识别
    # ==========================
    def start_capture(self):
        self.hide()
        self.cap = CaptureScreen(self.on_capture)
        self.cap.show()

    def on_capture(self, pixmap):
        self.show()
        self.decode_preview.setPixmap(pixmap.scaled(300, 260, Qt.KeepAspectRatio))

        img = self.qpixmap_to_cv(pixmap)
        text, _, _ = self.detector.detectAndDecode(img)

        if text:
            self.show_decode_text(text, src="截屏识别")
        else:
            self.decode_text.setText("未识别到二维码")

    def show_decode_text(self, text, src):
        self.decode_text.setText(text)

        # 修改：使用新格式添加历史记录
        self.add_history(src, text)

        if text.startswith("http"):
            self.decode_text.setStyleSheet("color:blue; text-decoration: underline;")
        else:
            self.decode_text.setStyleSheet("")

    def qpixmap_to_cv(self, pix):
        qimg = pix.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
        w, h = qimg.width(), qimg.height()
        ptr = qimg.bits()
        arr = np.frombuffer(ptr, dtype=np.uint8).reshape((h, w, 4))
        return cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)

    # ==========================
    #        系统托盘（稳健版）
    # ==========================
    def init_tray(self):
        # 1) 尝试加载实际文件 ico（如果有）
        here = os.path.dirname(__file__)
        ico_path = os.path.join(here, resource_path("icon.ico"))
        if os.path.exists(ico_path):
            tray_icon = QIcon(ico_path)
        else:
            # 兜底：使用 style() 但包装进 QIcon
            tray_icon = QApplication.style().standardIcon(QStyle.SP_ComputerIcon)
            if isinstance(tray_icon, QIcon):
                pass
            else:
                tray_icon = QIcon(tray_icon)

        # 2) 创建 tray 并保存为实例属性（防止被回收）
        self.tray = QSystemTrayIcon(tray_icon, parent=self)
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

        # 5) 兼容性处理：部分 Windows 环境右键不弹出菜单，监听 activated 并手动弹出菜单
        def on_tray_activated(reason):
            if reason == QSystemTrayIcon.Context:
                pos = QCursor.pos()
                self.tray_menu.exec(pos)
            elif reason == QSystemTrayIcon.Trigger:
                self.show()

        self._on_tray_activated = on_tray_activated
        self.tray.activated.connect(self._on_tray_activated)

        # 6) 显示托盘图标
        self.tray.show()

    def show_main_window(self):
        self.show()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def force_quit(self):
        self._force_quit = True
        self.tray.hide()
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
            QSystemTrayIcon.Information,
            2000
        )


# ================================
#             启动
# ================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(resource_path("icon.ico")))
    w = QRApp()
    w.show()
    sys.exit(app.exec())