import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from measure_finger import save_output


class CliOutputTests(unittest.TestCase):
    def test_save_output_normalizes_numpy_scalars_and_arrays(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "result.json"
            save_output(
                {"scalar": np.float32(1.25), "array": np.array([1, 2], dtype=np.int32)},
                str(path),
            )
            self.assertEqual(json.loads(path.read_text()), {"scalar": 1.25, "array": [1, 2]})


if __name__ == "__main__":
    unittest.main()

