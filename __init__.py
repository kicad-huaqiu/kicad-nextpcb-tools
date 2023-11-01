import sys
import os


PLUGIN_ROOT =os.path.dirname(os.path.abspath(__file__))
if PLUGIN_ROOT not in sys.path:
        sys.path.append(PLUGIN_ROOT)
from .plugin import NextPcbBomTool
NextPcbBomTool().register()

