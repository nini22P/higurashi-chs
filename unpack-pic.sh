#!/bin/bash

python shin-tools/pic-tool.py unpack -i raw/hou/data/picture -o build/pic-hou-orig
python shin-tools/pic-tool.py unpack -i raw/hou/append/picture -o build/pic-hou-orig
python shin-tools/pic-tool.py unpack -i raw/hou/patch/picture -o build/pic-hou-orig
python shin-tools/pic-tool.py unpack -i raw/sui/data/picture -o build/pic-sui-orig
