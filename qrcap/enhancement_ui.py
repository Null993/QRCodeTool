from __future__ import annotations

import html
from concurrent.futures import Future, ThreadPoolExecutor

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QTextOption
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QLineEdit,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .enhancement import EnhancementManager, EnhancementStatus
from .recognition import RecognitionService
from .resources import enhancement_root
from .theme import theme_colors
from .ui_components import Card, PageHeader, section_label


class ImportSignals(QObject):
    finished = Signal(object)


class EnhancementPage(QWidget):
    """Status, import and analysis UI for optional enhancement packages."""

    status_changed = Signal(object)
    directory_changed = Signal(str)

    def __init__(
        self,
        manager: EnhancementManager,
        recognition: RecognitionService,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("pageContent")
        self.manager = manager
        self.recognition = recognition
        self.import_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="qrcap-package-import",
        )
        self.import_signals = ImportSignals()
        self.import_signals.finished.connect(self._on_import_finished)
        self._build_ui()
        self.recognition.enhancement_verified.connect(
            self.on_enhancement_verified
        )
        self.refresh_status()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(PageHeader(
            "增强能力",
            "按需导入 QReader / PyTorch 增强包，提升复杂、破损及异形二维码的识别能力。",
        ))

        status_card = Card(compact=True)
        status_card.body.setContentsMargins(14, 12, 14, 12)
        status_card.body.setSpacing(10)
        status_card.setToolTip(
            "基础识别不依赖 QReader/PyTorch；组件不完整时会自动回退到基础识别。"
        )
        status_card.body.addWidget(section_label("当前识别能力与组件明细"))

        status_card.body.addWidget(section_label("增强包存储目录"))
        directory_row = QHBoxLayout()
        self.directory_input = QLineEdit(str(self.manager.root))
        self.directory_input.setReadOnly(True)
        self.directory_input.setToolTip(
            "增强包会安装到该目录下的 active 子目录"
        )
        directory_row.addWidget(self.directory_input, stretch=1)

        self.directory_button = QPushButton("选择目录")
        self.directory_button.clicked.connect(
            self.choose_install_directory
        )
        directory_row.addWidget(self.directory_button)

        self.default_directory_button = QPushButton("恢复默认")
        self.default_directory_button.clicked.connect(
            self.restore_default_directory
        )
        directory_row.addWidget(self.default_directory_button)
        status_card.body.addLayout(directory_row)
        self._update_directory_controls()

        self.status_label = QTextEdit()
        self.status_label.setObjectName("enhancementStatusDetails")
        self.status_label.setReadOnly(True)
        self.status_label.setMinimumHeight(92)
        self.status_label.setMaximumHeight(126)
        self.status_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self.status_label.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.status_label.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.status_label.setLineWrapMode(
            QTextEdit.LineWrapMode.WidgetWidth
        )
        text_option = self.status_label.document().defaultTextOption()
        text_option.setWrapMode(
            QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere
        )
        self.status_label.document().setDefaultTextOption(text_option)
        status_card.body.addWidget(self.status_label)

        buttons = QHBoxLayout()
        self.import_button = QPushButton("导入增强包")
        self.import_button.setProperty("primary", True)
        self.import_button.clicked.connect(self.import_package)
        buttons.addWidget(self.import_button)

        self.refresh_button = QPushButton("重新分析")
        self.refresh_button.clicked.connect(self.refresh_status)
        buttons.addWidget(self.refresh_button)
        buttons.addStretch(1)
        status_card.body.addLayout(buttons)
        layout.addWidget(status_card)

        analysis_card = Card(compact=True)
        analysis_card.body.setContentsMargins(14, 12, 14, 12)
        analysis_card.body.setSpacing(10)
        analysis_card.body.addWidget(section_label("导入结果分析"))
        self.analysis = QTextEdit()
        self.analysis.setObjectName("enhancementAnalysis")
        self.analysis.setReadOnly(True)
        self.analysis.setMinimumHeight(76)
        self.analysis.setPlaceholderText(
            "导入增强包后，这里会显示兼容性、文件数量、组件和错误分析。"
        )
        analysis_card.body.addWidget(self.analysis, stretch=1)
        layout.addWidget(analysis_card, stretch=1)

    def refresh_status(
        self,
        status: EnhancementStatus | None = None,
    ) -> None:
        status = status or self.manager.inspect()
        application = QApplication.instance()
        active_theme = (
            application.property("qrcapTheme")
            if application is not None
            else "light"
        )
        colors = theme_colors(str(active_theme or "light"))
        if not status.installed:
            summary = "当前为基础识别模式，未导入增强包。"
            summary_color = colors["muted"]
        elif status.can_load and status.runtime_verified:
            summary = (
                f"增强包可用：{status.package_name or '未命名'} "
                f"{status.package_version}"
            ).strip()
            summary_color = colors["success"]
        elif status.can_load:
            summary = "增强包结构完整，正在等待或执行运行时验证。"
            summary_color = colors["warning"]
        else:
            summary = "当前增强包不完整，模型识别已禁用，基础识别不受影响。"
            summary_color = colors["error"]

        rows = [
            (
                f'<div style="font-weight:600;color:{summary_color};'
                f'margin:4px 0 8px 0;">{html.escape(summary)}</div>'
            )
        ]
        for component in status.components:
            mark = "✅" if component.available else "❌"
            color = (
                colors["success"]
                if component.available
                else colors["error"]
            )
            rows.append(
                f'<div style="margin:2px 0;color:{color};">'
                f'{mark} <b>{html.escape(component.name)}</b>：'
                f'{html.escape(component.detail)}</div>'
            )

        verification_mark = "✅" if status.runtime_verified else "❌"
        verification_color = (
            colors["success"]
            if status.runtime_verified
            else colors["error"]
        )
        rows.append(
            f'<div style="margin:2px 0;color:{verification_color};">'
            f'{verification_mark} <b>运行时验证</b>：'
            f'{html.escape(status.verification_detail)}</div>'
        )
        rows.append(
            '<div style="margin-top:8px;">安装目录：'
            f'{html.escape(str(status.active_dir))}</div>'
        )
        self.status_label.setHtml(
            f'<div style="color:{colors["text"]};">'
            + "".join(rows)
            + "</div>"
        )
        self.status_changed.emit(status)

    def choose_install_directory(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "选择增强包存储目录",
            str(self.manager.root),
        )
        if directory:
            self._apply_install_root(directory)

    def restore_default_directory(self) -> None:
        self._apply_install_root(enhancement_root())

    def _apply_install_root(self, directory) -> None:
        target = self.manager.set_root(directory)
        self._update_directory_controls()
        is_default = target == enhancement_root()
        self.directory_changed.emit("" if is_default else str(target))

        status = self.manager.activate_runtime()
        self.refresh_status(status)
        if not status.can_load:
            self.analysis.setPlainText(
                "增强包存储目录已切换。\n"
                "新目录中尚无完整增强包，当前继续使用基础识别。"
            )
            return

        if self.recognition.qr_reader is not None:
            self.analysis.setPlainText(
                "增强包存储目录已切换。旧增强运行库已在当前进程加载，"
                "请重启程序后使用新目录中的增强包。"
            )
            QMessageBox.information(
                self,
                "增强包目录已切换",
                "目录设置已保存。由于增强模型已经加载，"
                "请重启程序以完整切换到新目录。",
            )
            return

        self.recognition.reload_enhancement()

    def _update_directory_controls(self) -> None:
        self.directory_input.setText(str(self.manager.root))
        self.default_directory_button.setEnabled(
            self.manager.root != enhancement_root()
        )

    def import_package(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "导入二维码增强包",
            filter="QRCodeTool 增强包 (*.zip);;ZIP 压缩包 (*.zip)",
        )
        if not filename:
            return

        self.import_button.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.directory_button.setEnabled(False)
        self.default_directory_button.setEnabled(False)
        self.analysis.setPlainText(
            "正在校验并导入增强包…\n"
            "大体积 PyTorch 增强包可能需要数分钟，基础识别仍可继续使用。"
        )
        future = self.import_executor.submit(
            self.manager.import_archive,
            filename,
        )
        future.add_done_callback(self._notify_import_finished)

    def _notify_import_finished(self, future: Future) -> None:
        try:
            result = future.result()
        except Exception as exc:
            result = exc
        self.import_signals.finished.emit(result)

    def _on_import_finished(self, result: object) -> None:
        self.import_button.setEnabled(True)
        self.refresh_button.setEnabled(True)
        self.directory_button.setEnabled(True)
        self._update_directory_controls()
        if isinstance(result, Exception):
            self.analysis.setPlainText(
                f"导入失败：{type(result).__name__}: {result}"
            )
            QMessageBox.warning(
                self,
                "增强包导入失败",
                "导入过程中发生未处理错误，当前增强包没有变化。",
            )
            return

        report = result
        self.analysis.setPlainText(report.to_text())
        status = self.manager.inspect()
        self.refresh_status(status)

        if not report.success:
            QMessageBox.warning(
                self,
                "增强包导入失败",
                "压缩包未安装，当前识别能力没有变化。\n\n"
                + "\n".join(report.messages[-3:]),
            )
            return

        self.recognition.reload_enhancement()
        if report.restart_required:
            QMessageBox.information(
                self,
                "增强包已导入",
                "增强包已安装。由于旧增强运行库已在本进程加载，"
                "请重启程序后使用新版本。",
            )

    def on_enhancement_verified(self, success: bool, detail: str) -> None:
        self.refresh_status()
        result = "✅ 运行时验证通过" if success else "❌ 运行时验证失败"
        self.analysis.append(f"\n{result}：{detail}")

    def shutdown(self) -> None:
        self.import_executor.shutdown(wait=False, cancel_futures=True)
