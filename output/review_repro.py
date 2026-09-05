"""Run the regression checks for the three review findings."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.test_regressions import RegressionTests

if __name__ == "__main__":
    unittest.main(verbosity=2)
