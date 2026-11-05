M05 / A05-drawings, B01 M1 only. Implementation is ready for ROOT's remote
verification. No extractor runtime, PDF regeneration, or pytest run occurred
locally. The native RESULT binds this handoff to the exact assigned branch tip.

The public boundary is
`load_drawings(corpus_root, generated_dir, *, dpi=144, ids=None) -> list[DrawingEvidence]`.
`corpus_root` is `development/inputs/project-meridian`. PNGs go to
`generated_dir/images/D-xxx-pN.png`; `page_image_path(id, page)` gives each relative
path. The caller persists returned contracts. Primary corner keys refer to page
1. Additional pages use keys such as `title-p2`, with their own page and box.
These are ordinary frozen DrawingField objects, not new payload types.

The extractor verifies distributed PDF bytes and page counts against the
manifest, deduplicates coincident words, retains source spelling and numeric
substrings, and transforms boxes by the PDF crop/rotation into the saved PNG
frame. PageGeometry records actual raster dimensions. Numbers have no inferred
engineering meanings or units. Missing and placeholder fields resolve to null;
overlap retains its original text and stays unsure. Notes never fill a title.
Scans have no OCR words/numbers or guessed values. Their null fields carry
regions measured from clean table borders/labels, scaled to the actual scan
page size, with the donor identified in the field note. Lack of a compatible
measured donor raises a clear error. Source values, callout interpretation and
reader execution are outside this slice.

Actual checks performed:

- `python -B smoke/A05-drawings/inspect_static.py --raw-artifacts <download>/harness-v2-pdf-42000021167/runs/pdf-regeneration`
  from `testing/`: AST syntax and frozen export-name checks passed. All 40
  manifest asset hashes match supplied bytes. See `static.json` for exact
  module/test hashes and raw-source observations. This does not execute the
  extractor or validate its runtime behavior.
- Downloaded [raw PDF run 42000021167](https://github.com/JasonPeng2019/proj-meridian/actions/runs/42000021167),
  revision `e9eb4f1b5126d15f0faacfa109f8453105dc4bef`: inspected positioned JSON
  for D-013/D-019/D-026, missing-title and multipage sources, and the D-026 PNG.
  Source hashes match this worktree's manifest. D-013 has coincident text;
  D-019 prints `Description`; D-026's `Sheet` and `WEIGHT` boxes intersect.
  D-021 has two text pages; D-003 has three raster-only pages. D-003/D-022
  measure 1182.4 by 834.4 points, whereas clean sheets measure about 1190.55
  by 841.89. The implementation measures and scales crop regions accordingly.
  This is source inspection and raw extraction capability, not this module's
  test result or a human review.
- `git diff --cached --check`: recorded separately in RESULT after staging.

ROOT action: integrate/publish this scoped tip on `harness-v2`, then dispatch
the focused suite with the existing locked `prep` and `test` extras. From
`testing/`, with caches/environments retained beneath `testing/`, run:

```text
uv run --project ../development --locked --extra prep --extra test python -m pytest tests/test_drawings.py -q -o cache_dir=cache/A05-drawings-pytest --basetemp=tmp/A05-drawings-pytest --junitxml=reports/verification/A05-drawings/pytest.xml
```

The six authored tests exercise the real D-013/D-019/D-026 cases, all six
documented missing titles, D-021/D-003 multipage navigation, scan crop data,
unchanged source bytes, and a synthetic cropped/rotated PDF whose numeric
highlight must contain actual rendered ink. Synthetic overlap has a different
drawing ID. Changed synthetic bytes and output into the source corpus fail
explicitly. Runtime assertions have not been reported passed. Download both
`testing/reports/verification/A05-drawings/` and `testing/runs/A05-drawings/`
for source review. The suite saves typed extraction records and page PNGs.

No package, config, contract, shared output, plan, source input, or other owner's
module was changed. PyMuPDF is already declared in the existing prep extra.
M3 callout facts and generated source crops are deferred.

Proposed asynchronous USER_TODO for ROOT to deduplicate: `DRAW-019-TITLE`.
For the planned M1 correction demonstration, ask Jason what corrected title
to record for D-019, using its title/notes and actual drawing in Review. The
printed title is `Description`; the note reads `1mm silicone pakning`. Current
state remains unsure/unreviewed, and no title is inferred from that note. The
evidence is `D-019/positioned-text.json` and `D-019/page-1.png` in the linked
remote artifact. This proposal does not block implementation or preparation.
