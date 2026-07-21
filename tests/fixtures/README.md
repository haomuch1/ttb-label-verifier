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

- **Bärenjäger** — five affixed images with mandatory info scattered
  across them (brand on image 1, ABV/net contents on image 2, the warning
  on image 3; images 4–5 carry no regulated text). Form and labels both
  read 35% ALC/VOL. Exercises combined-set checking — the app must treat
  all five images as one set, since no single image carries everything.
- **Carlo Giacosa** — older form revision with shifted item numbers;
  guards against extracting by item number.
- **Lenz Moser** — warning printed in all capitals and hyphenated across
  a line break; guards the normalize-but-preserve-case balance.

Hand-transcribed versions of these scenarios live in
`tests/test_real_cola_scenarios.py` as the fast regression net; the images
here feed end-to-end extraction tests once the vision call lands.
