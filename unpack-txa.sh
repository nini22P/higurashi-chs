#!/bin/bash

python shin-tools/txa-tool.py unpack -i raw/hou/data -o assets/txa-hou-orig
python shin-tools/txa-tool.py unpack -i raw/hou/patch -o assets/txa-hou-orig
python shin-tools/txa-tool.py unpack -i raw/sui/data -o assets/txa-sui-orig