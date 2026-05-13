# higurashi-hou-chs

[中文文档](README_zh.md)

## Feature

- Support extracting, translating, and packaging game text for Higurashi Hou (version 2.0.2)
- Use csv files for translation, easy to edit and manage
- Batch auto-translation support

## Quick start

### How to translate

1. Create a folder named `translate_cn` and place the translation files in the format `ep*.csv`, requiring at least an original column (`original`) and a translation column (`translation`).

2. In the terminal, run `extract.py`, `auto_translate.py` in sequence. 

3. Replace `higurashi-hou.csv` with the generated `higurashi-hou-translated.csv` file, then refer to [How to pack](#how-to-pack).

### How to pack

1. Create a `raw` folder and place the game files for version 2.0.2 inside it, including `data.rom`, `patch.rom`, and `append.rom`.

2. Run `python pack.py` in the terminal. On Windows you can also double-click `pack.bat`.

## Credits

- [DCNick3 / shin-translation-tools](https://github.com/DCNick3/shin-translation-tools)