# Scoring implementation note

The registered protocol ranks tied systems by:

1. exact cases;
2. weakest 12-case block;
3. fewer harmful overrides;
4. fewer logical calls;
5. more correct terms;
6. canonical strategy hash.

The legacy generic scorer emitted a five-part `protocol_fitness_key` containing
exact cases, weakest block, negative harmful overrides, correct terms, and
format validity. It omitted logical call count before term accuracy.

This omission did not change any promoted search or validation finalist. The
contenders tied at the affected boundaries used the same number of calls. The
final pooled validation selector in `postprocessing/prepare_final.py` did
include fewer pooled calls before correct terms and selected the two finalists
correctly.

Historical score files remain unchanged. They are audit artifacts and should
not be silently rewritten. Any future ranking must use the complete registered
order above, or explicitly register a new order before calls.

The exploratory prompt races use their own documented plurality and subset
rules. Their post-hoc subset scores are never promoted as frozen performance.
