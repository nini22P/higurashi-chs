@echo off
chcp 65001 >nul
echo === 1/3: 提取脚本 ===
python extract.py
if %errorlevel% neq 0 exit /b %errorlevel%

echo.
echo === 2/3: 自动翻译匹配 ===
python auto_translate.py
if %errorlevel% neq 0 exit /b %errorlevel%

echo.
echo === 3/3: 导入翻译回 CSV ===
python import.py
if %errorlevel% neq 0 exit /b %errorlevel%

echo.
echo === 全部完成 ===
