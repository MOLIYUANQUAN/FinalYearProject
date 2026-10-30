# Friday — working rules

This is Zeep's personal agent (FYP). Read `docs/plan.md` (direction) and `docs/engineering-log.md` (decisions) first.

## Product judgement
- Before building anything, ask: how would Steve Jobs design this? Would he make the user configure, learn, or take an extra step? Can it get simpler by removing something?
- If a feature needs a setup page, a token, or instructions to be usable, it probably should not exist. Cut it, and spend the effort on the path that already exists.
- Friday is Zeep's workbench, not a generic assistant: every change should reduce something he has to manage himself.

## Engineering
- Branches: `develop` is day-to-day (pushing it runs tests, then deploys to Fly); `main` is for milestones only.
- Commits: author `MOLIYUANQUAN`, no co-author lines, nothing that mentions an AI tool.
- Tests: `python -m unittest discover -s tests -t .` (offline, scripted fake model, no keys). Keep them green before pushing.
- Times, counts, dates and when to interrupt him are computed on the server, not by the model.
- Anything outward or destructive goes through `needs_approval`; only his own to-dos and calendar events run directly with an undo.
