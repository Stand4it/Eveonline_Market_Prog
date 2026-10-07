# Decisions log (append only; newest last)
- 2026-10-07: Loot counts in ISK/hr (value at best market net of round-trip travel time at 6M ISK/hr; trip hours added).
- 2026-10-07: Character is auto-picked by who is online; per-character DB/profile/tokens.
- 2026-10-07: Agent-missions work was found only on the user's PC; saved to branch agent-missions-local and merged. Lesson: ask for `git status` early.
- 2026-10-07: Notes moved into md/; `python -m eve_profit docs --check` shows where notes and code disagree; CLAUDE.md + SessionStart hook load START_HERE on every session.
- 2026-10-07: per-PC facts (timer, runs) moved to git-ignored md/LOCAL_STATE.md so md/STATE.md is identical on every machine (no conflicts on pull).
- 2026-10-07: Arabeton step 3 done (196,030 ISK, 28 min). Estimates for first-time missions must use ~2x the guessed minutes; time bonus falls with time.
- 2026-10-07: md/COMMANDS.txt (Notepad) and md/COMMANDS.docx (Word) generated from the code with every option and an example per command.
