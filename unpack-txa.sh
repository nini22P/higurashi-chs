#!/bin/bash

python shin-tools/txa-tool.py unpack -i raw/hou/data -o build/txa-hou-orig
python shin-tools/txa-tool.py unpack -i raw/hou/patch -o build/txa-hou-orig
python shin-tools/txa-tool.py unpack -i raw/sui/data -o build/txa-sui-orig