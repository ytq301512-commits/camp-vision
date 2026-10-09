# 阵营识别（Camp Vision）

这是一个 Windows 本地桌面工具：框选屏幕中的人物名称区域，使用 OCR 识别文字，再根据可编辑的人物库给人物标注阵营。识别和匹配均在本机完成。

本项目以 MIT License 发布，见 [LICENSE](LICENSE)。这是一个 Windows 本地工具，不提供联网服务，也不会上传屏幕截图。

识别链路参考了 [TFT-OCR-BOT](https://github.com/jfd02/TFT-OCR-BOT) 中“限定屏幕区域 → OCR 文字 → 游戏数据字典”的做法。本项目没有照搬该项目为 TFT/1920×1080 和英文界面定制的固定坐标、Tesseract 配置或游戏自动操作；改为运行时框选、RapidOCR，以及用户自定义人物/阵营数据。

## 运行

在 PowerShell 中执行：

```powershell
.\run.ps1
```

首次启动会创建 `.venv` 并安装 PySide6、RapidOCR、ONNX Runtime 和屏幕捕获依赖，可能需要几分钟。项目需要 Python 3.10～3.13；`run.ps1` 会优先使用 Codex 自带的 Python 3.12。

安装完成后，桌面上的“阵营识别”快捷方式会直接启动已安装的 `pythonw.exe`，不会弹出命令行窗口。若首次安装中断或环境损坏，请重新运行 `run.ps1`。

## 使用

1. 打开“人物库”，将人物、阵营和别名保存。别名适合填写简称和 OCR 容易误识别的写法。
2. 回到“实时识别”，点击“分辨率”选择/填写显示器实际像素分辨率（如 2560×1600），或选“自动”使用 Windows DPI；再点击“框选范围”，拖动框住完整卡面和底部名称。软件会按设定换算框选和截图坐标，框外内容不会读取。
3. 点击“开始识别”。命中的人物会在原文字附近显示彩色阵营标签。
4. 调试时可用“识别图片”导入截图，结果会显示在表格中，不会启动悬浮层。

软件现在采用“卡图识别 + OCR”双通道：卡图模板优先识别卡面，文字清晰时由 OCR 校验；当卡名被遮挡或 OCR 只读到部分文字时，会使用卡图结果补充识别。模板保存在 `assets/card_templates`，发布包中已一并带上。

实时识别页面提供“硬件加速”开关。OCR 使用可用的 CUDA 或 DirectML 后端；卡图特征匹配使用 OpenCL GPU。GPU 不可用时会回退到 CPU，状态栏会显示当前实际使用的后端。

识别间隔支持 100ms 起按 100ms 调整；“保存配置”开启时会记住识别范围、分辨率、间隔和 GPU 设置，关闭后这些设置不会在下次启动恢复。

## 桌面版启动

桌面发布包无需卡密、机器码或联网激活。解压后保持目录结构不变，双击 `CampVision.exe` 即可使用；首次启动可能需要几秒加载 OCR 模型。

项目中的 `src/camp_vision/license.py` 和 `tools/license_issue.py` 仅保留给旧版授权工具与历史测试使用，当前桌面版启动流程不会调用它们。

当多张牌靠得太近、人物名被遮挡时，匹配器会尝试使用 OCR 读到的首字（或首字加等级数字）做唯一候选匹配；如果同一首字对应多个人物，则会放弃该条结果，不会擅自标错阵营。

人物库也可导入 JSON 或 CSV。CSV 列为 `name,camp,aliases,color`，多个别名用英文逗号分隔。

## 人物库 JSON

```json
{
  "version": 1,
  "characters": [
    {
      "name": "人物名称",
      "camp": "所属阵营",
      "aliases": ["简称", "常见误识别写法"],
      "color": "#22c55e"
    }
  ]
}
```

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## 从源码运行

```powershell
git clone <仓库地址>
cd 自动识别阵营
.un.ps1
```

也可以直接安装为 Python 包：

```powershell
py -3.12 -m venv .venv
..venvScriptspython.exe -m pip install -r requirements.txt
..venvScriptspython.exe -m camp_vision.app
```

卡图模板的来源和再分发注意事项见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
