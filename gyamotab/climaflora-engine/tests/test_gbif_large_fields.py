import importlib.util
import sys
import zipfile
from pathlib import Path


def load_builder():
    path = Path(__file__).parents[1] / ".github" / "tools" / "build_gbif_names_media_v1_7.py"
    spec = importlib.util.spec_from_file_location("gbif_builder_large_field", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_dwca_reader_accepts_fields_larger_than_python_csv_default(tmp_path: Path) -> None:
    builder = load_builder()
    archive = tmp_path / "large.zip"
    long_value = "x" * (512 * 1024)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("large.txt", f"1\t{long_value}\n")

    section = builder.Section(
        location="large.txt",
        id_index=0,
        coreid_index=None,
        fields={"payload": 1},
        delimiter="\t",
        quotechar='"',
        encoding="utf-8",
        headers=0,
    )
    with zipfile.ZipFile(archive) as zf:
        rows = list(builder.iter_rows(zf, section))

    assert len(rows) == 1
    assert rows[0][0] == "1"
    assert rows[0][1] == long_value
