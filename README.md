# PISA project

Course project (Data Science Project, M2). Student-level PISA data for the 2018, 2022 and 2025 cycles.

## Setup

```
uv sync
```

## Data

The data are not in the repository (`data/` is git-ignored; the OECD terms of use for the 2025
public-use files forbid passing them on).

1. Download the SPSS archives into `data/raw/<year>/`:
   - 2018: `SPSS_STU_QQQ.zip`, `SPSS_SCH_QQQ.zip` from https://webfs.oecd.org/pisa2018/
   - 2022: `STU_QQQ_SPSS.zip`, `SCH_QQQ_SPSS.zip` from https://webfs.oecd.org/pisa2022/
   - 2025: `CY09_MS_STU_PUF.zip`, `CY09_MS_SCH_PUF.zip`, `CY09_MS_TCH_PUF.zip`; the links are given
     after filling in the OECD form reached from
     https://www.oecd.org/en/data/datasets/pisa-2025-database.html
2. Convert them to Parquet:

```
uv run python scripts/convert_to_parquet.py
```

This writes `data/parquet/<year>/{stu,sch,tch}.parquet` and, next to each file, a
`.labels.json` with the variable labels and value labels of the SPSS file. SPSS missing codes
become nulls.
