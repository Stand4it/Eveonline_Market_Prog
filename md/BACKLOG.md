# Backlog (in order)
1. Merge the user's new agent offers/missions into agent_offers.json from screenshots; re-rank.
2. Career-agent activities in the planner; scale measured L1 results to higher levels by ship and skill points.
3. Training suggestions that improve the model (explore/exploit); auto hangar snapshot for loot value.
4. Ship shopping advisor; patient buy orders for away time; reprocess-or-sell; character contracts; reactions/T2/PI.
5. Unverified on live data: journey, compare, home-station read, trainplan.
- Keep-list: do not advise selling/listing items a ship or mission you plan needs (e.g. 2 x Miner I for the Venture: instant sale 2,897 vs rebuy ~13,900 each). Compare sell price vs rebuy price before any SELL/LIST step.
- Gear reserve: show 'cost to replace your current fit' and warn when wallet < that; spares for combat ships (auto_keep_fitted covers fitted modules only).
- Persist worldwide price results (bestprice / now step 4) in a world_prices table (type, system, net each, jumps, ts) so next/haul can use them for rare stacks nobody near buys. Entropic Rose Metallic - Limited x2: Lustrevik 925k each (25 jumps, ~21 min), Jita 576k (18), Perimeter 481k (17), Botane 371k (6), Dodixie 370k (7); C-J6MT/Ney have no safe route.
- Industry jobs: sync already reads the running jobs (mfg_slots shows 0/1); still to do: keep the job rows (finish time) so next can say 'job finishes in N min'.
- tripplus: rank ALL candidates with route extras included (not just show them on the winner); long-term value (standing, unlocks, skills) per candidate in progress_values.json.
- Regional listing tax: learn it per region instead of one Profile.listing_tax. Exordium charges 5% of the order value on LISTING ("Exordium Market Tax"; not in the ESI journal). Next time at a hub (Jita etc.) screenshot the sell window fee lines / watch the wallet after one small listing, then store {region: listing_tax} (data file) and use the current region's value in the list-vs-sell-now maths. Home station does NOT change market fees (only clone respawn).
- Home station: user's is Mettle IV - AIR Laboratories (4 jumps from Rotonos, set 2026-10-10). Low priority: when living/trading at a hub, offer to move it there (respawn convenience only).
- (BUILT 2026-10-11, add more ores from screenshots) Reprocess-or-sell (found 2026-10-11): Scordite 0-Grade sells raw at 4.66 in Rotonos but refines into Tritanium + Pyerite (Pyerite buyers ~15 in Ligare, 1 jump; none in Rotonos). Needs: refining yield + station fee from the in-game Reprocess window (screenshot), minerals sold at the best bid in reach, compare ISK/min vs selling raw; data file reprocess.json (ore -> minerals per 100 units) so any ore/item can be modeled.
- When the user sends screenshots from the UPDATE THE MODEL step: update bonus_programs.json (AIR goals, progress, time limits), agent_offers.json, and note every new field/time limit in DECISIONS.
- THREADS gaps: rank 1-jump-off-route detours (agent here/near, trade) against the haul; derive progress value from the unlock graph; persistent goals with progress.
- Value AIR career points: milestone SP rewards (50k/75k/100k/125k) at ~1,667 ISK/SP; need points-per-milestone (hover the diamonds) then add career_points to agent offer value in next.
- Freelance Veldspar mining job (5 ISK/unit, cap 1M, expires 2026-10-28): keep ranked every step; accept it when mining wins or ore buy prices drop (then 'done --goal "job veldspar"').
- Virtual buyers: let accepted/available freelance DELIVERY jobs (e.g. any scordite 9.00 ISK/item at Botane/Manarq/Hek) compete with buy orders in sellplan/reprocess; needs the job cap/budget and an accept state.
