from pathlib import Path
import os
import sys

base=Path(__file__).resolve().parent
os.chdir(base)
sys.path.insert(0,str(base))
from painel import main
main()
