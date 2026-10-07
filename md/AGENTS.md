# Agent missions (Level 1 career agents in Rotonos)
- Offers live in `agent_offers.json` (entered from the user's screenshots; edit after each new screenshot). `next` ranks them by NET ISK/hr incl. travel.
- Checklist: `python scripts/agent_steps.py [next|list|done|skip|back|reset]`. It never starts timers.
- Name timed runs `Agent L1 step N <Agent> <what>`; `next` then shows "AGENT MISSIONS (measured)" and says DO AGENT MISSIONS FIRST when they beat trades by 1.2x.
- Timer: `start --activity NAME` ... `stop` (wait ~2 min after finishing so the wallet journal updates). `pause` / `resume` freeze it;
  `stop --add-min N` or `fixlast --add-min N` add minutes you worked while paused.
- Taxes seen: Industrialist and Explorer step 2+ taxed 11% (corp tax); Soldier of Fortune and step 1 payouts untaxed.
- Measured so far: ~0.95-1.0M ISK/hr for L1 agent steps vs ~147k ISK/hr for the best trade in Rotonos.
