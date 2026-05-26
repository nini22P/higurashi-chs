xcopy /y /i raw\main build\exefs\

bin\nx2elf.exe build\exefs\main
python shin-tools\patch-tool.py -b build\exefs\main.elf -c build\exefs-mapped.csv
bin\elf2nso.exe build\exefs\main.elf build\exefs\main

del build\exefs\main.elf