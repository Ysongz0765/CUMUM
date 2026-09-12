import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from microgrid.time_utils import *
def test_0000_plus_1_parse(): assert parse_time_label('0:00+1')==(0,0,1)
def test_144_slots(): assert len(canonical_grid('2025-01-01'))==144
def test_power_to_energy(): assert power_to_energy(6)==1
