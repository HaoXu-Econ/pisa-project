"""Convert the PISA public-use SPSS files to Parquet.

Input  : data/raw/<year>/  (the .zip archives downloaded from the OECD, or already extracted .sav files)
Output : data/parquet/<year>/<kind>.parquet       one row per student / school / teacher
         data/parquet/<year>/<kind>.labels.json   variable labels and value labels from the SPSS file

<kind> is "stu" (student questionnaire, includes the plausible values), "sch" (school questionnaire)
or "tch" (teacher questionnaire). Other files (cognitive items, timing) are left untouched.

SPSS user-defined missing codes (e.g. 95-99 "Not applicable", "No response") become nulls.
Numeric variables are stored as float64 and character variables as strings, so that every
chunk of a file has the same schema.

Usage: uv run python scripts/convert_to_parquet.py [--force]
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pyreadstat

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "parquet"
CHUNK_ROWS = 50_000


def kind_of(filename: str) -> str | None:
    """Map a PISA file name to stu / sch / tch, or None for files we do not convert."""
    name = filename.upper()
    if not name.endswith(".SAV"):
        return None
    if re.search(r"STU_QQQ|_STU_PUF|_MS_STU\.", name):
        return "stu"
    if re.search(r"SCH_QQQ|_SCH_PUF|_MS_SCH\.", name):
        return "sch"
    if re.search(r"TCH_QQQ|_TCH_PUF|_MS_TCH\.", name):
        return "tch"
    return None


def external_unzip(archive: Path, member: str, dest_dir: Path) -> None:
    """Extract one member with a system tool. Needed for the OECD archives that use Deflate64,
    a compression method Python's zipfile module cannot read."""
    windows_tar = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tar.exe"
    if shutil.which("unzip"):
        command = ["unzip", "-o", "-j", "-q", str(archive), member, "-d", str(dest_dir)]
    elif shutil.which("7z"):
        command = ["7z", "e", "-y", f"-o{dest_dir}", str(archive), member]
    elif windows_tar.exists():  # bsdtar, shipped with Windows 10 and later; keeps the member's folders
        command = [str(windows_tar), "-xf", str(archive), "-C", str(dest_dir), member]
    else:
        raise RuntimeError(f"{archive.name} uses Deflate64: install unzip or 7-Zip, or extract it by hand")
    subprocess.run(command, check=True)


def extract_archives(year_dir: Path) -> None:
    """Extract the .sav members of every zip in the folder, unless already extracted."""
    for archive in sorted(year_dir.glob("*.zip")):
        with zipfile.ZipFile(archive) as zf:
            for member in zf.infolist():
                if not member.filename.upper().endswith(".SAV"):
                    continue
                target = year_dir / Path(member.filename).name
                already = [p for p in year_dir.rglob("*") if p.name.upper() == target.name.upper()]
                if already and already[0].stat().st_size == member.file_size:
                    continue
                print(f"  extracting {member.filename} from {archive.name}")
                try:
                    with zf.open(member) as src, open(target, "wb") as dst:
                        while block := src.read(1 << 24):
                            dst.write(block)
                except NotImplementedError:
                    target.unlink(missing_ok=True)
                    external_unzip(archive, member.filename, year_dir)


def convert(sav: Path, out_parquet: Path) -> int:
    _, meta = pyreadstat.read_sav(str(sav), metadataonly=True)
    types = meta.readstat_variable_types
    schema = pa.schema(
        [(col, pa.string() if types[col] == "string" else pa.float64()) for col in meta.column_names]
    )
    out_parquet.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_parquet.with_suffix(".parquet.tmp")
    rows = 0
    with pq.ParquetWriter(tmp, schema, compression="zstd") as writer:
        for chunk, _ in pyreadstat.read_file_in_chunks(pyreadstat.read_sav, str(sav), chunksize=CHUNK_ROWS):
            arrays = [
                pa.array(chunk[field.name], type=field.type, from_pandas=True) for field in schema
            ]
            writer.write_table(pa.Table.from_arrays(arrays, schema=schema))
            rows += len(chunk)
            print(f"    {rows:,} / {meta.number_rows:,} rows", end="\r")
    print()
    if rows != meta.number_rows:
        tmp.unlink()
        raise RuntimeError(f"{sav.name}: wrote {rows} rows, the file declares {meta.number_rows}")
    tmp.replace(out_parquet)

    labels = {
        "source_file": sav.name,
        "rows": rows,
        "columns": {
            col: {
                "label": meta.column_names_to_labels.get(col),
                "type": types[col],
                "values": {str(k): v for k, v in meta.variable_value_labels.get(col, {}).items()},
            }
            for col in meta.column_names
        },
    }
    out_parquet.with_suffix(".labels.json").write_text(
        json.dumps(labels, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="convert again even if the Parquet file exists")
    args = parser.parse_args()

    for year_dir in sorted(p for p in RAW.iterdir() if p.is_dir()):
        print(f"{year_dir.name}")
        extract_archives(year_dir)
        for sav in sorted(p for p in year_dir.rglob("*") if p.is_file() and kind_of(p.name)):
            out = OUT / year_dir.name / f"{kind_of(sav.name)}.parquet"
            if out.exists() and not args.force:
                print(f"  {out.relative_to(ROOT)} exists, skipped")
                continue
            print(f"  {sav.name} -> {out.relative_to(ROOT)}")
            rows = convert(sav, out)
            print(f"  done: {rows:,} rows, {out.stat().st_size / 1e6:.0f} MB")


if __name__ == "__main__":
    main()
