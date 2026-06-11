#!/bin/bash

python shin-tools/pic-tool.py unpack -i raw/hou/data/picture -o assets/pic-hou-orig
python shin-tools/pic-tool.py unpack -i raw/hou/append/picture -o assets/pic-hou-orig
python shin-tools/pic-tool.py unpack -i raw/hou/patch/picture -o assets/pic-hou-orig
python shin-tools/pic-tool.py unpack -i raw/sui/data/picture -o assets/pic-sui-orig
