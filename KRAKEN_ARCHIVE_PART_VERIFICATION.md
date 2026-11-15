# Kraken OHLCVT full archive: checksum verification and reassembly

Kraken publishes five approximately 2 GB parts for the full OHLCVT archive.
The official page provides a SHA-256 file for each part and a checksum for
the reassembled ZIP. The current published combined ZIP SHA-256 is:

`bc273e9027470b07d790a7fa4df9bb43f0dfc527c20c6ecae48402e123e7b1c7`

Official source:
https://support.kraken.com/articles/360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data

Official part checksums:
https://assets.kraken.com/marketing/institutions/OHLCVT_Full_PARTS_SHA256SUMS.txt

## Workflow

1. Download all five files `Kraken_OHLCVT_Full.zip.part00` through `part04`
   from Kraken's official page.
2. Download the official `OHLCVT_Full_PARTS_SHA256SUMS.txt` file.
3. Keep the five parts and checksum file in one folder.
4. Run:

```bash
python kraken_archive_parts.py /path/to/parts /path/to/OHLCVT_Full_PARTS_SHA256SUMS.txt /path/to/Kraken_OHLCVT_Full.zip
```

The utility verifies every part before writing the combined ZIP, streams data
in 1 MiB chunks, verifies the final ZIP checksum, and only then atomically
renames the temporary output into place. If a part or final checksum fails,
no final output ZIP is left behind.

## Important

- This tool does not download anything; it works with files already downloaded.
- The complete source is roughly 10 GB plus the reassembled ZIP, so plan for
  sufficient free disk space before assembling.
- Checksums prove byte-for-byte integrity against Kraken's published checksum
  list; they do not alone prove that a specific CSV is the intended market.
- After reassembly, run `kraken_archive_inspector.py` to locate exact market
  members, then validate selected CSVs with `kraken_ohlcvt.py`.
- Do not commit the archive, CSVs, API credentials, or simulator state to Git.
