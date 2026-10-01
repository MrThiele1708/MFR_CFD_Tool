#!/usr/bin/env python3
import os

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "case/system/mapFieldsDict"

text = """FoamFile
{
    version 2.0;
    format ascii;
    class dictionary;
    object mapFieldsDict;
}

patchMap
(
);

cuttingPatches
(
);
"""

path.write_text(text, encoding="utf-8")
print("Created:", path)
