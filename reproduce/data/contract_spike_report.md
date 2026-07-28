# OpenDataLoader 2.5.0 Contract Probe

Run date: 2026-07-24

Fixture: `contract_spike_test.pdf` (4 pages; page 3 is intentionally blank).

| Requested page | SDK `number of pages` | Element pages | Result |
| --- | --- | --- | --- |
| 1 | 4 | 1 | success |
| 2 | 4 | 2 | success |
| 3 | 4 | none | explicit blank |
| 4 | 4 | 4 | success |

Each single-page invocation emitted exactly one JSON and one Markdown artifact.
The blank-page JSON was valid with an empty `kids` array, and its Markdown was
empty. Therefore coverage is based on a dedicated `pages=<n>` invocation plus
contained, hashed artifacts, never on a missing element in a batch result.

The fixture also confirmed the recursive element model and real list spelling:
containers use `list items`; children use `type: "list item"`. The remaining
contract corpus still needs approved table, image, formula, malformed, and
encrypted fixtures before staging promotion.
