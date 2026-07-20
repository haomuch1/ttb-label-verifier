# Test fixtures — real COLAs from TTB's Public COLA Registry

Drop the files here as follows (any filename is fine within each folder;
keep one folder per COLA):

```
tests/fixtures/
  blank-form-5100-31-2023-04.pdf   # blank 04/2023 revision of Form 5100.31
  barenjager/                      # rev 07/2012 — five affixed label images
  carlo-giacosa/                   # rev 6/2006 — brand name at Item 5, no Source of Product field
  lenz-moser/                      # warning all-caps + hyphenated (ALCOHOLIC BEV-/ERAGES)
```

Why these three earn their place:

- **Bärenjäger** — form says Alcohol Content `35`, both labels say
  `39% ALC / VOL`: a genuine 4-point form-to-label discrepancy on an
  approved COLA. Expected app result: **NEEDS REVIEW** with the ABV
  cross-check flagged. Also exercises combined-set checking (mandatory
  info scattered across images 1–3; images 4–5 carry no regulated text).
- **Carlo Giacosa** — older form revision with shifted item numbers;
  guards against extracting by item number.
- **Lenz Moser** — warning printed in all capitals and hyphenated across
  a line break; guards the normalize-but-preserve-case balance.

Hand-transcribed versions of these scenarios live in
`tests/test_real_cola_scenarios.py` as the fast regression net; the images
here feed end-to-end extraction tests once the vision call lands.
