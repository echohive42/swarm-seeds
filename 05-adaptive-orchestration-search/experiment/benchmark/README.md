# RuleWeave-5 adaptive-director benchmark

This fresh Experiment 05 benchmark contains 336 exact next-five sequence cases:
72 search, 72 validation, and 192 hidden final. Every registered 24-case panel
contains each of the 24 family and difficulty cells once. Every model request
receives one public block of at most 12 cases.

Search uses three consecutive block pairs, one per adaptive batch. Validation
uses three pairs. The hidden final uses eight pairs. Search answer files open
only after all calls in their batch are terminal. Validation and final answers
remain sealed until their registered release gates.

The generator rejects internal duplicates and exact visible-prefix, canonical
program, or next-five-target overlap with Experiments 02, 03, and 04.
