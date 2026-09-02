# Scripts

Utilities for local development/testing.

## `script/test.sh`
Quick runner for `measure_finger.py`.

### Usage
```bash
./script/test.sh
./script/test.sh input/my_image.jpg
./script/test.sh --no-debug
./script/test.sh --skip-card-detection
./script/test.sh --help
```

### Behavior
- Uses first image in `input/` when no image is passed.
- Creates `.venv` and installs deps if missing.
- Writes JSON to `output/test_result.json`.
- Result PNG is auto-generated as `output/test_result.png` by the main tool.
- `--debug` in this script toggles intermediate debug folders (default: enabled).

## `script/build.sh`
Reserved for packaging/build automation (currently empty).
