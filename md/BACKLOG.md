# Backlog (in order)
1. Merge the user's new agent offers/missions into agent_offers.json from screenshots; re-rank.
2. Career-agent activities in the planner; scale measured L1 results to higher levels by ship and skill points.
3. Training suggestions that improve the model (explore/exploit); auto hangar snapshot for loot value.
4. Ship shopping advisor; patient buy orders for away time; reprocess-or-sell; character contracts; reactions/T2/PI.
5. Unverified on live data: journey, compare, home-station read, trainplan.
- Keep-list: do not advise selling/listing items a ship or mission you plan needs (e.g. 2 x Miner I for the Venture: instant sale 2,897 vs rebuy ~13,900 each). Compare sell price vs rebuy price before any SELL/LIST step.
- Gear reserve: show 'cost to replace your current fit' and warn when wallet < that; spares for combat ships (auto_keep_fitted covers fitted modules only).
- Persist worldwide price results (bestprice / now step 4) in a world_prices table (type, system, net each, jumps, ts) so next/haul can use them for rare stacks nobody near buys. Entropic Rose Metallic - Limited x2: Lustrevik 925k each (25 jumps, ~21 min), Jita 576k (18), Perimeter 481k (17), Botane 371k (6), Dodixie 370k (7); C-J6MT/Ney have no safe route.
- Industry jobs: add scope esi-industry.read_character_jobs.v1 (needs re-login) so sync sees running jobs and 'Manufacturing jobs 0/1' without screenshots; then next can say 'job finishes in N min'.
