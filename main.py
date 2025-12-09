import sys
import os
import json
import io
from io import BytesIO
from datetime import datetime
import webbrowser
import re
import cv2
import numpy as np
import qrcode
import warnings
warnings.filterwarnings("ignore", message="Double decoding failed")

# ---------- 常量 ----------
HISTORY_FILE = "history.json"
CONFIG_FILE = "config.json"
MODEL_FILE = "model/qrdet-s.pt"  # 你的本地模型相对路径（相对于 main.py 或打包后的 _MEIPASS）

def resource_path(relative_path):
    """获取打包后资源的正确路径"""
    if hasattr(sys, '_MEIPASS'):
        return str(os.path.join(sys._MEIPASS, relative_path))
    return str(os.path.join(os.path.abspath("."), relative_path))

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

# ---------------------------
# Monkey patch requests -> 当请求 qrdet-s.pt 时直接返回本地文件流（模拟下载成功）
# ---------------------------
try:
    import requests
    import requests.sessions
    from requests.models import Response as RequestsResponse

    # 本地模型路径（优先使用 resource_path，兼容打包）
    LOCAL_MODEL_PATH = resource_path(MODEL_FILE)

    _orig_requests_get = requests.get
    _orig_session_request = requests.sessions.Session.request

    def _build_response_from_file(path: str, url: str) -> RequestsResponse:
        """用本地文件内容构建一个 requests.Response，模拟远程下载流式返回。"""
        data_size = os.path.getsize(path)
        with open(path, "rb") as f:
            data = f.read()

        resp = RequestsResponse()
        resp.status_code = 200
        resp._content = data  # .content 属性
        resp.headers["Content-Length"] = str(data_size)
        resp.url = url

        # raw 需要类文件对象（requests/urllib3 可能直接读取 raw.read()）
        resp.raw = io.BytesIO(data)

        # 提供 iter_content 方法（requests 有时直接调用它）
        def iter_content(chunk_size=8192):
            for i in range(0, len(data), chunk_size):
                yield data[i:i + chunk_size]
        resp.iter_content = iter_content

        return resp

    def _fake_get(url, *args, **kwargs):
        # 精准匹配 qrdet 模型文件名，必要时你可以把匹配放宽/放严
        if isinstance(url, str) and "qrdet-s.pt" in url:
            if os.path.exists(LOCAL_MODEL_PATH):
                print(f"[patch] serving local model for {url} -> {LOCAL_MODEL_PATH}")
                return _build_response_from_file(LOCAL_MODEL_PATH, url)
            else:
                # 如果本地模型不存在，打印提示并回退到真实请求（若你希望强制失败也可改成抛错）
                print(f"[patch] local model not found at {LOCAL_MODEL_PATH}, falling back to real request")
                return _orig_requests_get(url, *args, **kwargs)
        # 非模型请求：正常转发
        return _orig_requests_get(url, *args, **kwargs)

    def _fake_session_request(self, method, url, *args, **kwargs):
        if method and method.upper() == "GET" and isinstance(url, str) and "qrdet-s.pt" in url:
            return _fake_get(url, *args, **kwargs)
        return _orig_session_request(self, method, url, *args, **kwargs)

    # 应用 monkey patch（在导入 qreader/qrdet 之前执行）
    requests.get = _fake_get
    requests.sessions.Session.request = _fake_session_request

    print("[patch] requests monkey-patch installed for qrdet-s.pt")
except Exception as e:
    # 如果 patch 失败，继续运行但打印错误（不阻塞程序）
    print("[patch] failed to install requests patch:", e)

# 现在安全导入 QReader（在上面的 patch 生效后）
from qreader import QReader

# ---------------------------
# GUI 相关导入
# ---------------------------
from PySide6.QtWidgets import (
    QApplication, QWidget, QTabWidget, QVBoxLayout, QLabel, QPushButton,
    QTextEdit, QFileDialog, QLineEdit, QSystemTrayIcon, QStyle, QMenu,
    QListWidget, QListWidgetItem, QMessageBox, QHBoxLayout, QCheckBox, QSizePolicy
)
from PySide6.QtGui import (
    QPixmap, QAction, QGuiApplication, QPainter, QPen, QColor, QImage, QIcon
)
from PySide6.QtCore import Qt, QRect, QPoint, QTimer, Signal

# ================================
#       截图框选窗口（高 DPI 修复）
# ================================
class CaptureScreen(QWidget):
    def __init__(self, callback, cancel_callback=None):
        super().__init__()
        self.callback = callback
        self.cancel_callback = cancel_callback

        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)   # ⭐ 置顶
        self.setWindowState(Qt.WindowState.WindowFullScreen)
        self.setCursor(Qt.CursorShape.CrossCursor)

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
        if e.button() == Qt.MouseButton.LeftButton:
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
        if e.button() == Qt.MouseButton.LeftButton:
            self.selecting = False
            try:
                self.end = e.position().toPoint()
            except Exception:
                self.end = e.pos()

            rect = QRect(self.start, self.end).normalized()
            if rect.width() > 5 and rect.height() > 5:
                # 使用从抓取到的 pixmap 获取的 devicePixelRatio（更稳健）
                pix_dpr = getattr(self.full_pix, "devicePixelRatio", lambda: 1)()
                if not pix_dpr:
                    pix_dpr = 1.0

                # 将逻辑坐标转换为物理像素坐标再裁剪
                real_rect = QRect(
                    int(rect.x() * pix_dpr),
                    int(rect.y() * pix_dpr),
                    int(rect.width() * pix_dpr),
                    int(rect.height() * pix_dpr),
                )

                # 避免越界（clip 到原始 pixmap 的物理尺寸）
                phys_w = int(self.full_pix.width() * pix_dpr)
                phys_h = int(self.full_pix.height() * pix_dpr)
                full_phys_rect = QRect(0, 0, phys_w, phys_h)
                real_rect = real_rect.intersected(full_phys_rect)

                cropped = self.full_pix.copy(real_rect)

                # 确保 cropped 的 devicePixelRatio 被正确设置（与原始 pixmap 一致）
                try:
                    cropped.setDevicePixelRatio(pix_dpr)
                except Exception:
                    # 某些 Qt 版本/平台可能不支持，忽略失败
                    pass

                # self.callback(cropped)
                # 在 CaptureScreen.mouseReleaseEvent 中把 self.callback(cropped) 改为：
                QTimer.singleShot(0, lambda pix=cropped: self.callback(pix))

            self.close()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            if self.cancel_callback:
                self.cancel_callback()  # 通知主窗口恢复
            self.close()

# ================================
#           主程序
# ================================
class QRApp(QWidget):
    hotkey_triggered = Signal()

    def __init__(self):
        super().__init__()

        self.chk_all = None
        self.hotkey_handle = None
        self.setWindowTitle("二维码工具 v1.1  By Null993")
        self.resize(700, 520)
        self.config = self.load_config()

        self.detector = cv2.QRCodeDetector()
        self.history = self.load_history()

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.tabs.addTab(self.page_generate(), "生成二维码")
        self.tabs.addTab(self.page_decode(), "解析二维码")
        self.tabs.addTab(self.page_history(), "历史记录")
        self.tabs.addTab(self.page_hotkey(), "热键设置")

        self.hotkey_triggered.connect(self.start_capture)

        self.start_hotkey_listener()
        base_dir = os.path.dirname(os.path.abspath(__file__))

        # Ensure model folder exists (helpful for first-run)
        model_folder = os.path.join(base_dir, "model")
        os.makedirs(model_folder, exist_ok=True)

        # 检查本地模型是否存在（用户需要把 qrdet-s.pt 放在 model/ 目录）
        model_full = resource_path(MODEL_FILE)
        if not os.path.exists(model_full):
            QMessageBox.critical(
                None,
                "缺少模型文件",
                f"未找到本地模型：{model_full}\n\n请把 qrdet-s.pt 放到此路径，或修改 MODEL_FILE 常量。",
            )
            raise FileNotFoundError(f"Missing model file: {model_full}")

        # 重要：通过 QReader 的构造（weights_folder）指向固定目录（作为双保险）
        self.qr_reader = QReader(
            model_size="s",
            weights_folder=os.path.join(base_dir, "model")
        )

        self.init_tray()

    def load_config(self):
        if not os.path.exists(CONFIG_FILE):
            return {"hotkey": "", "detect_all_plus": False}
        try:
            return json.load(open(CONFIG_FILE, "r", encoding="utf8"))
        except:
            return {"hotkey": "", "detect_all_plus": False}

    def save_config(self):
        json.dump(self.config, open(CONFIG_FILE, "w", encoding="utf8"),
                  ensure_ascii=False, indent=2)

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
        """根据 decode_preview 大小自动缩放预览图片（处理 DPI 与布局时序）"""
        if not hasattr(self, "_orig_decode_pixmap"):
            return

        pix = self._orig_decode_pixmap
        label = self.decode_preview

        # 如果 label 还没 layout 好（size 为 0），稍后重试
        if label.width() == 0 or label.height() == 0:
            QTimer.singleShot(100, self.update_decode_preview)
            return

        # 如果 pixmap 有 devicePixelRatio（高 DPI），把它规范化为 DPR = 1 的 QPixmap 再缩放
        # 这样 scaled() 的目标尺寸就是“逻辑像素”一致的。
        dpr = getattr(pix, "devicePixelRatio", lambda: 1)()
        if not dpr:
            dpr = 1.0

        if dpr != 1.0:
            # 把 pixmap 转为 QImage（物理像素），然后从 image 重建一个 DPR=1 的 pixmap
            img = pix.toImage()
            # 确保 image 的 devicePixelRatio 为 1，再从 image 创建 pixmap
            try:
                img.setDevicePixelRatio(1.0)
            except Exception:
                pass
            disp_pix = QPixmap.fromImage(img)
        else:
            disp_pix = pix

        # 使用 label 的当前逻辑尺寸进行等比缩放并设置
        scaled = disp_pix.scaled(label.width(), label.height(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        label.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_decode_preview()

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
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        # 使用 itemChanged 信号处理勾选，避免与点击事件冲突
        self.list.itemChanged.connect(self.on_item_changed)

        # 双击打开链接（只在双击时打开，避免勾选时触发）
        self.list.itemDoubleClicked.connect(self.on_history_double_click)

        # 右键菜单
        self.list.customContextMenuRequested.connect(self.on_history_right_click)

        v.addWidget(self.list)

        self.refresh_history()
        return w

    def page_hotkey(self):
        w = QWidget()
        v = QVBoxLayout(w)


        # 第一行：提示文字
        lab = QLabel("按下你希望用于『截屏识别』的快捷键（如 F1、Ctrl+Shift+S）")
        # lab.setSizePolicy(
        #     QSizePolicy.Policy.Minimum,
        #     QSizePolicy.Policy.Minimum
        # )
        v.addWidget(lab, stretch=0)

        # 第二行：按钮 + 输入框
        h = QHBoxLayout()
        self.hotkey_input = QLineEdit()
        self.hotkey_input.setPlaceholderText("按键将自动记录")
        h.addWidget(self.hotkey_input)

        save_btn = QPushButton("保存快捷键")
        save_btn.clicked.connect(self.save_hotkey)
        h.addWidget(save_btn)

        v.addLayout(h, stretch=0)
        v.addStretch(1)  # stretch=1，吸收所有剩余空间

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
        v = QVBoxLayout(w)

        self.input_text = QTextEdit()
        self.input_text.setPlaceholderText("输入内容")
        v.addWidget(self.input_text)

        btn = QPushButton("生成二维码")
        btn.clicked.connect(self.generate_qr)
        v.addWidget(btn)

        self.qr_label = QLabel("二维码预览")
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.qr_label)

        save = QPushButton("保存二维码")
        save.clicked.connect(self.save_qr)
        v.addWidget(save)

        return w

    def generate_qr(self):
        text = self.input_text.toPlainText().strip()
        if not text:
            return

        qr = qrcode.main.QRCode(box_size=8, border=2)
        qr.add_data(text)
        qr.make()
        img = qr.make_image()

        buf = BytesIO()
        img.save(buf)
        self.qr_data = buf.getvalue()

        pix = QPixmap()
        pix.loadFromData(self.qr_data)
        self.qr_label.setPixmap(pix.scaled(300, 300, Qt.AspectRatioMode.KeepAspectRatio))

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
        # detect_all_plus 开关
        self.chk_detect_plus = QCheckBox("启用增强识别（可识别异形、特殊二维码）")
        v.addWidget(self.chk_detect_plus)

        btn = QPushButton("选择图片解析")
        btn.clicked.connect(self.open_decode)
        v.addWidget(btn)


        self.chk_detect_plus.setChecked(self.config.get("detect_all_plus", False))
        self.chk_detect_plus.stateChanged.connect(self.on_detect_plus_changed)


        cap_btn = QPushButton("截屏识别")
        cap_btn.clicked.connect(self.start_capture)
        v.addWidget(cap_btn)

        # 图片预览区域
        self.decode_preview = QLabel("图片预览")
        self.decode_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.decode_preview.setScaledContents(False)
        self.decode_preview.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )
        self.decode_preview.setMinimumSize(200, 200)
        v.addWidget(self.decode_preview, stretch=1)  # 占据剩余空间

        # 文本结果显示区域
        self.decode_text = QTextEdit()
        self.decode_text.setReadOnly(True)
        self.decode_text.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred  # Preferred: 根据内容确定合适大小
        )
        self.decode_text.setMaximumHeight(300)  # 设置最大高度限制
        self.decode_text.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        self.decode_text.mousePressEvent = self.open_link_if_needed

        # 监听文本变化
        self.decode_text.textChanged.connect(self.update_decode_text_size)

        # 初始设置合适的高度
        self.decode_text.setFixedHeight(int(self.decode_text.document().size().height() + 20))

        v.addWidget(self.decode_text)

        return w

    def on_detect_plus_changed(self):
        self.config["detect_all_plus"] = self.chk_detect_plus.isChecked()
        self.save_config()

    def update_decode_text_size(self):
        """根据文本内容更新decode_text的大小"""
        # 获取文档的理想高度
        doc_height = self.decode_text.document().size().height()

        # 加上一些边距（大约20像素）
        needed_height = doc_height + 20

        # 限制最小和最大高度
        min_height = 30
        max_height = 300

        if needed_height < min_height:
            needed_height = min_height
        elif needed_height > max_height:
            needed_height = max_height

        # 设置固定高度
        self.decode_text.setFixedHeight(needed_height)

        # 强制更新布局，确保图片预览区域能重新计算可用空间
        self.decode_text.updateGeometry()
        if self.decode_preview.parent():
            self.decode_preview.parent().updateGeometry()

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
        fn, _ = QFileDialog.getOpenFileName(self, "选择图片", filter="Images (*.png *.jpg *.jpeg)")
        if not fn:
            return

        pix = QPixmap(fn)
        self._orig_decode_pixmap = pix
        self.update_decode_preview()
        self.decode_file(fn)

    def decode_file(self, fn):
        img = cv2.imdecode(np.fromfile(fn, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return None

        # 尝试多二维码识别
        return self.detect_all_selector(img,"解析图片",self.config["detect_all_plus"])

    # ==========================
    #         截屏识别
    # ==========================
    def start_capture(self):
        # ⭐ 切换到“解析二维码”页签
        self.tabs.setCurrentIndex(1)

        self.hide()
        self.cap = CaptureScreen(self.on_capture, self.on_capture_cancel)
        self.cap.show()

    def on_capture_cancel(self):
        self.show()

    # ---------- on_capture：把 singleShot(0) 改成短延迟，保证窗口恢复并布局完成 ----------
    def on_capture(self, pixmap):
        self.show()
        self._orig_decode_pixmap = pixmap
        # 延迟一点再更新预览，避免窗口刚 show 导致 decode_preview size = 0（或布局未完成）
        QTimer.singleShot(100, self.update_decode_preview)

        img = self.qpixmap_to_cv(pixmap)

        # 多二维码识别
        res = self.detect_all_selector(img, "截屏识别",self.config["detect_all_plus"])


    def detect_all_selector(self, img,source, enablePlus):
        if enablePlus:
            return self.detect_all_plus(img,source)
        else:
            return self.detect_all(img,source)

    def detect_all(self, img, source):
        ok, texts, pts, _ = self.detector.detectAndDecodeMulti(img)

        if ok and texts:
            texts = [t for t in texts if t]

            if texts:
                # 生成 HTML 卡片风格
                html = "".join([
                    f"""
                        <div style="
                            margin-bottom: 12px;
                            padding: 10px 0; /* 仅保留垂直内边距，移除水平内边距以实现更“透明”的效果 */
                            background: transparent; /* ✨ 关键：设置背景为透明 */
                            color: inherit; /* ✨ 关键：字体颜色继承父元素或系统主题 */
                            font-size: 14px;
                            word-wrap: break-word;
                            border-bottom: 1px solid #eeeeee; 
                        ">
                            <a href="{t}" style="
                                color: inherit; /* ✨ 关键：链接颜色也继承父元素或系统主题 */
                                text-decoration: none;
                            ">{t}</a>
                        </div>
                        """
                    for t in texts
                ])

                self.decode_text.setHtml(html)

                for t in texts:
                    self.add_history(source, t)

                return texts

        self.decode_text.setHtml(
            '<div style="color:#bbbbbb;">未识别出二维码</div>'
        )
        return None

    def detect_all_plus(self, img, source):

        result = self.qr_reader.detect_and_decode(image=img, is_bgr=True)

        # detect_and_decode 返回的是 tuple[str|None, ...]
        if not result:
            self.decode_text.setHtml(
                '<div style="color:#bbbbbb;">未识别出二维码</div>'
            )
            return None

        texts = [t.strip() for t in result if t]

        if not texts:
            self.decode_text.setHtml(
                '<div style="color:#bbbbbb;">未识别出二维码</div>'
            )
            return None

        # 生成 HTML 卡片风格
        html = "".join([
            f"""
                <div style="
                    margin-bottom: 12px;
                    padding: 10px 0; /* 仅保留垂直内边距，移除水平内边距以实现更“透明”的效果 */
                    background: transparent; /* ✨ 关键：设置背景为透明 */
                    color: inherit; /* ✨ 关键：字体颜色继承父元素或系统主题 */
                    font-size: 14px;
                    word-wrap: break-word;
                    border-bottom: 1px solid #eeeeee; 
                ">
                    <a href="{t}" style="
                        color: inherit; /* ✨ 关键：链接颜色也继承父元素或系统主题 */
                        text-decoration: none;
                    ">{t}</a>
                </div>
                """
            for t in texts
        ])

        self.decode_text.setHtml(html)

        for t in texts:
            self.add_history(source, t)

        return texts

    def show_decode_text(self, text, src):

        self.decode_text.setText(text)

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
            tray_icon = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
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

        # 5) 设置双击托盘打开界面
        self.tray.activated.connect(self.on_tray_activated)

        # 6) 显示托盘图标
        self.tray.show()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_main_window()


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
            QSystemTrayIcon.MessageIcon.Information,
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
