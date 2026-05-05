# higurashi-hou-chs

## Language

- [English](#english)
- [中文](#中文)


### English

#### how to translate

1. Create a folder named `translate_cn` and place the translation files in the format `ep*.csv`, requiring at least an original column (`original`) and a translation column (`translation`).

2. In the terminal, run `extract.py`, `auto_translate.py`, and `import.py` in sequence. On Windows, you can also double-click `translate.bat`.

3. After replacing `higurashi-hou.csv` with the generated `higurashi-hou-translated.csv` file, refer to How to pack to pack

#### How to pack

1. Create a `raw` folder and place the game files for version 2.0.2 inside it, including `data.rom`, `patch.rom`, and `append.rom`.


2. Run `python pack.py` in the terminal. On Windows you can also double-click `pack.bat`.

### 中文

// Your Chinese content here


#### 如何翻译

1. 创建一个名为 `translate_cn` 的文件夹，将翻译文件以 `ep*.csv`的格式放入，要求至少有原文列（ `original` ）和翻译列（ `translation` ）。

2. 在重点依次运行 `extract.py`、`auto_translate.py` 和 `import.py`。在windows上也可以双击 `translate.bat`。

3. 将生成的 `higurashi-hou-translated.csv` 文件替换掉 `higurashi-hou.csv` 之后参考 How to pack 进行打包。

#### 如何打包

1. 创建一个 `raw` 文件夹，并将 2.0.2 版本的游戏文件放入其中，包括 `data.rom`、`patch.rom` 和 `append.rom。`

2. 在终端中运行 python `pack.py`。在 Windows 上，也可以双击 `pack.bat`。


## Credits

- [DCNick3 / shin-translation-tools](https://github.com/DCNick3/shin-translation-tools)
