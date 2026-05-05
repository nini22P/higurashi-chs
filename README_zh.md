# higurashi-hou-chs

[English](README.md)

## 功能

- 支持提取、翻译和打包寒蝉鸣泣之时 奉（Higurashi Hou，版本 2.0.2）的游戏文本
- 使用 csv 文件进行翻译，易于编辑和管理
- 支持批量自动翻译

## 快速开始

### 如何翻译

1. 创建一个名为 `translate_cn` 的文件夹，将翻译文件以 `ep*.csv` 的格式放入，要求至少有原文列（`original`）和翻译列（`translation`）。

2. 在终端依次运行 `extract.py`、`auto_translate.py` 和 `import.py`。在 Windows 上也可以双击 `translate.bat`。

3. 将生成的 `higurashi-hou-translated.csv` 文件替换掉 `higurashi-hou.csv`，之后参考如何打包。

### 如何打包

1. 创建一个 `raw` 文件夹，并将 2.0.2 版本的游戏文件放入其中，包括 `data.rom`、`patch.rom` 和 `append.rom`。

2. 在终端中运行 `python pack.py`。在 Windows 上，也可以双击 `pack.bat`。

## 致谢

- [DCNick3 / shin-translation-tools](https://github.com/DCNick3/shin-translation-tools)