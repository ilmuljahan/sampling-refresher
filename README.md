# Sampling Refresher

A browsable reference built from my own survey-sampling study notes
(Modules 0-10, plus a syllabus), originally written as Word/RTF documents.

Rendered with Quarto and published to GitHub Pages:
**https://ilmuljahan.github.io/sampling-refresher**

The modules run from foundations and vocabulary through simple random,
systematic, stratified, cluster, and multistage/PPS designs, then weighting,
design-based variance estimation, sample size and allocation, nonprobability
sampling, and power.

## Regenerating the pages

The `.qmd` files and everything in `figures/` are generated from the original
illustrated RTF notes, which live outside this repo and are not tracked here.

```bash
python _tools/rtf2qmd.py
```

The converter reads the RTF sources, classifies each paragraph by its formatting
signature (heading, list item, figure caption, boxed aside, table cell), extracts
the 56 embedded PNG figures, and writes one `.qmd` per module. Point `SRC` at the
folder holding the RTFs if it moves.

## Building the site

```bash
quarto preview
```

```bash
quarto render
```
