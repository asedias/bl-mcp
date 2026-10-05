summary: Universal rules for every task. They come with every recipe.

1. Call `status` first, then `scene_tree`. The scene is often not empty.
2. Units are metres. Z is up. The front of a model faces -Y. Left and right parts end in `_L` and `_R`: `mirror` swaps them.
3. Decide numbers before geometry: sizes, ratios, positions. Write them as `assert_spec` checks. Store them with `save_spec`. Call `run_spec` after every change.
4. Build one part at a time. Name every part.
5. Do not guess coordinates. Place parts with `attach`, `move_to_contact`, `ground`, `set_dimensions`, `transform_objects`.
6. After every step: `measure`, then look. `render_sheet` gives the overview, `render_view` a close-up.
7. Take a `checkpoint` before a risky step. Keep a change only if its number grows. If not, `rollback`. It returns the whole scene, not one part.
8. An eye is not a metric. Compare with the reference through `compare_view`. Trust a number over a picture.
9. A side comparison cannot see a one-sided defect. Call `check_symmetry` after every shaping step on a symmetric part.
10. Read the whole answer of a tool. A `warning`, an achieved value or a count tells what went wrong. A tool that refuses changed nothing.
11. Long tools run as background jobs. When the answer is a job id, ask `job_status`. Do not edit the object while the job runs.
12. Use `run_python` only when no tool does the job. Read its report of changed objects.
