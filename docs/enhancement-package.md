# QRCodeTool 可选增强包说明

QRCodeTool 的紧凑基础程序只包含 ZXing 和 ZBar。OpenCV、NumPy、Pillow、QReader、QRDet、PyTorch、Ultralytics、模型权重及其依赖通过独立 ZIP 增强包导入。

这种设计有三个目的：

- 没有增强包时，生成、基础识别、截图、历史记录、热键和托盘功能全部正常；
- 只有部分组件时，界面明确显示缺失项，程序自动停用模型路径；
- 完整增强包通过后台导入和模型预热后，为困难二维码提供兜底识别。

## 压缩包结构

`manifest.json` 必须位于 ZIP 根目录。

```text
QRCodeTool-enhancement-qreader.zip
├── manifest.json
├── models/
│   ├── qrdet-s.pt
│   └── current_release.txt             # 可选，避免第三方库检查更新
└── runtime/
    ├── dlls/                         # 可选的额外 DLL 目录
    └── site-packages/
        ├── qreader/
        ├── qrdet/
        ├── torch/
        │   └── lib/
        ├── torchvision/
        ├── ultralytics/
        ├── *.dist-info/
        └── 其他传递依赖
```

程序判定完整增强包时检查以下组件：

- QReader
- QRDet
- PyTorch
- TorchVision
- Ultralytics
- `models/qrdet-s.pt`

其他传递依赖会在运行时预热阶段验证。结构完整但无法导入的增强包不会导致程序退出，模型路径会停用，并在界面显示失败原因。

## manifest.json

示例：

```json
{
  "schema_version": 1,
  "package_id": "qrcap-qreader-pytorch",
  "name": "QReader/PyTorch 增强识别包",
  "version": "1.0.0",
  "platform": "windows",
  "architecture": "amd64",
  "python": "3.11",
  "model": "qrdet-s.pt"
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `schema_version` | 当前必须为 `1` |
| `package_id` | 稳定的增强包标识 |
| `name` | 界面显示名称 |
| `version` | 增强包版本 |
| `platform` | `windows` 或 `any` |
| `architecture` | `amd64`、`arm64` 或 `any` |
| `python` | 编译扩展对应的 Python 主次版本，例如 `3.11` |

带有 PyTorch 等二进制扩展的包不应使用 `platform=any` 或 `python=any`。

## 构建完整增强包

在包含 QReader/PyTorch 的构建环境中执行：

```powershell
pip install -r requirements-enhancement-build.txt
python tools/build_enhancement_pack.py `
  --model model/qrdet-s.pt `
  --version 1.0.0 `
  --output dist/QRCodeTool-enhancement-qreader.zip
```

构建工具会：

1. 从 QReader、QRDet、PyTorch、TorchVision、Ultralytics 和 Quadrilateral Fitter 开始；
2. 根据已安装发行版元数据递归收集运行时依赖；
3. 排除基础程序已自带的 PyZBar、PySide6、ZXing 等组件，同时把 NumPy、OpenCV 和 Pillow 收入增强包；
4. 复制 `site-packages` 内的 Python 文件、二进制扩展、DLL 和发行版元数据；
5. 加入模型和清单后生成支持 ZIP64 的压缩包。

构建环境的 Python 主次版本、操作系统和 CPU 架构必须与目标基础程序一致。

## 导入流程

用户在“增强包”页签点击“导入增强包”后，程序按以下顺序处理：

1. 检查 ZIP 格式、文件数量和解压后体积；
2. 拒绝绝对路径、`..` 路径穿越、重复路径和符号链接；
3. 读取并验证清单、平台、架构和 Python ABI；
4. 解压到同一用户数据目录中的临时位置；
5. 分析每个必需组件；
6. 验证通过后原子替换当前增强包；
7. 后台导入运行库并执行一次空白图模型预热；
8. 在界面显示结构分析和运行时验证结果。

ZIP 校验、解压和结果分析在独立导入线程中执行。即使完整增强包解压后接近 1 GiB，也不会阻塞主界面或基础识别线程。

默认存储根目录为 `QRCodeTool.exe` 所在目录，增强包实际安装到其
`active` 子目录。用户也可以在“增强能力”页面选择其他目录，设置会保存
到 `config.json`。

```text
<QRCodeTool.exe 所在目录>\active
```

测试或便携环境可以通过 `QRCAP_ENHANCEMENT_DIR` 环境变量覆盖根目录。

## 部分增强包的行为

部分增强包会被保留并展示分析结果，但不会启用模型识别。

| 当前状态 | 基础识别 | 模型识别 | 界面 |
| --- | --- | --- | --- |
| 未导入 | 可用 | 禁用 | 缺失项显示红叉 |
| 仅模型 | 可用 | 禁用 | 模型绿勾、运行库红叉 |
| 仅运行库 | 可用 | 禁用 | 运行库绿勾、模型红叉 |
| 结构完整但导入失败 | 可用 | 禁用 | 结构绿勾、运行时验证红叉 |
| 完整且验证通过 | 可用 | 可用 | 全部绿勾 |

如果旧版 PyTorch/QReader 已经在当前进程中加载，再导入新版本后需要重启程序，避免在一个进程内卸载和替换原生运行库。

## 基础程序打包

基础程序的 PyInstaller 配置明确排除：

```text
qreader
qrdet
torch
torchvision
ultralytics
opencv-python
numpy
PIL
```

同时不再把 `qrdet-s.pt` 加入基础包。由于 PyInstaller 无法自动分析外置包对 Python 标准库的动态依赖，`pyinstaller_hooks/hook-qrcap.recognition.py` 会保留模型预热过程中实际使用的标准库模块，但不会收录任何增强包本体。

发布前应检查基础包中不存在上述模块和模型，再分别测试无包、部分包和完整包场景。
