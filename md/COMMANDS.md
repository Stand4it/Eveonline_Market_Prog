# COMMANDS (auto-generated; also md/COMMANDS.txt for Notepad and md/COMMANDS.docx for Word)

```
EVE PROFIT - EVERY COMMAND AND ITS OPTIONS
============================================
Run each as:  python -m eve_profit <command> [options]   (in PowerShell, from the repo folder)

OPTIONS THAT WORK WITH EVERY COMMAND:
   --db           database file (default E:\EveProfit\eve_profit.db)
   --profile      profile file (default profile.json)
   --char         separate character: own login, profile and database (e.g. --char fresh)
   --sync         refresh your character data (assets, wallet, location) first
   --client-id    else env EVE_CLIENT_ID, else client_id.txt

INIT  -  create the database
   example: python -m eve_profit init

MOCK  -  load an offline demo market
   example: python -m eve_profit mock

SDE  -  import game data from a file
   --sde-file     sde: import this local sqlite/.bz2 instead of downloading
   --sde-url      sde: download from this URL
   example: python -m eve_profit sde

SCAN  -  rank everything you can do now (add --live to download prices)
   --budget       scan --live: stop downloading new regions after this many minutes (default 6; 0 = no limit)
   --live         use real ESI market data
   --away         unattended mode: long safe autopilot hauls only
   --max-age      --live: skip regions downloaded less than this many minutes ago
   --regions      comma list of region ids (default: auto from your system)
   --max-pages    limit pages per region (testing)
   --top          how many rows to show
   example: python -m eve_profit scan --live

PLAN  -  same as scan, no download
   --top          how many rows to show
   example: python -m eve_profit plan

WATCH  -  keep re-scanning
   --live         use real ESI market data
   --interval     watch seconds (ESI caches 5 min)
   --away         unattended mode: long safe autopilot hauls only
   example: python -m eve_profit watch

PROFILE  -  set system/cargo in the profile
   --system       profile: set current system name
   --cargo        profile: set cargo m3
   example: python -m eve_profit profile

LOGIN  -  log a character in (once per character)
   --char         separate character: own login, profile and database (e.g. --char fresh)
   --client-id    else env EVE_CLIENT_ID, else client_id.txt
   example: python -m eve_profit login

SYNC  -  read skills, wallet, assets, location from the game
   --char         separate character: own login, profile and database (e.g. --char fresh)
   example: python -m eve_profit sync

LOG  -  enter a timed run by hand
   --activity     name of the activity (use the same name each time)
   --isk          ISK amount
   --hours        hours to plan / training hours to show
   example: python -m eve_profit log --activity "Level 2 security mission" --isk 8000000 --hours 1

GO  -  send the route of a ranked task to the game client
   --pick         go: which ranked opportunity
   --send         go: really set in-game waypoints
   --away         unattended mode: long safe autopilot hauls only
   --top          how many rows to show
   example: python -m eve_profit go --pick 1 --send

UNIVERSE  -  load the map and items
   --force        universe: reload even if already loaded
   --sde-file     sde: import this local sqlite/.bz2 instead of downloading
   --sde-url      sde: download from this URL
   --depth        esimap: jumps around your system (default 3x radius)
   example: python -m eve_profit universe

ESIMAP  -  build a map from ESI around you
   --depth        esimap: jumps around your system (default 3x radius)
   example: python -m eve_profit esimap

FLEET  -  list parked ships
   example: python -m eve_profit fleet

SKILLS  -  ISK/hr-measured skill advice + training plan
   --hours        hours to plan / training hours to show
   example: python -m eve_profit skills --hours 72

DIAG  -  check the game data
   example: python -m eve_profit diag

EXPLAIN  -  why an item ranks where it does
   --pick         go: which ranked opportunity
   example: python -m eve_profit explain

CHECK  -  re-check live prices of a ranked task
   --pick         go: which ranked opportunity
   example: python -m eve_profit check

STOCK  -  value of everything you own
   --top          how many rows to show
   example: python -m eve_profit stock

ALONG  -  sell on the way to a destination
   --to           along: destination system name
   example: python -m eve_profit along

FIT  -  what is fitted to your ship
   example: python -m eve_profit fit

ZKILL  -  refresh the hauler-loss map
   example: python -m eve_profit zkill

NEXT  -  ONE next step (agent offers, sell/list, best trade)
   --sync         refresh your character data (assets, wallet, location) first
   --all          next: print everything (offers, skills, trades), not just the one step
   example: python -m eve_profit next

KEEP  -  build or sell your materials
   --to           along: destination system name
   example: python -m eve_profit keep

BPBUY  -  buy a blueprint to use your stock?
   --to           along: destination system name
   example: python -m eve_profit bpbuy

UPDATE  -  has a game patch changed the data?
   example: python -m eve_profit update

BESTPRICE  -  best buyers for one item anywhere
   --item         bestprice: item name or type id
   --qty          bestprice: quantity (default: what you hold here, else 1)
   example: python -m eve_profit bestprice --item "Zydrine" --qty 25000

SELLPLAN  -  sell/list/carry/detour/haul per stack
   --to           along: destination system name
   --world        sellplan: also check the N biggest stacks in every region
   example: python -m eve_profit sellplan --world 5

DAY  -  chain the best tasks for N hours
   --hours        hours to plan / training hours to show
   --cash         day: extra ISK you expect to have (e.g. from selling stock)
   --no-stock     day: leave out selling/listing the stock in your hangar
   example: python -m eve_profit day --hours 8

NOW  -  sync + scan + next step + price check
   --fast         now: skip the market re-scan (sync + next only)
   example: python -m eve_profit now --fast

CHARS  -  compare your characters
   example: python -m eve_profit chars

COMBATFIT  -  set real DPS/EHP/tank for combat
   --dps          combatfit: damage per second from Pyfa
   --ehp          combatfit: effective HP from Pyfa
   --tank         combatfit: sustained repair per second from Pyfa
   --value        combatfit: ship + fit value in ISK (what you lose if it dies)
   --ship         combatfit: hull name (default: the ship you are in)
   example: python -m eve_profit combatfit --ship "Vexor" --dps 450 --ehp 60000 --tank 200 --value 30000000

JOURNEY  -  plan a whole trip with pickups and trades
   --to           along: destination system name
   --live         use real ESI market data
   --quick        journey --live: refresh only the items you own along the route (seconds, not minutes)
   --detour       journey: how many jumps off the route to look for goods and buyers
   --max-age      --live: skip regions downloaded less than this many minutes ago
   example: python -m eve_profit journey --to Jita --live --quick

COMPARE  -  list here or make the trip?
   --to           along: destination system name
   --detour       journey: how many jumps off the route to look for goods and buyers
   example: python -m eve_profit compare --to Jita

START  -  start timing an activity
   --activity     name of the activity (use the same name each time)
   --no-loot      start/stop: do not value the items you picked up
   example: python -m eve_profit start --activity "Agent L1 step 4 Arabeton"

STOP  -  stop timing, read payouts and loot, log it
   --isk          ISK amount
   --paused       stop: minutes you were away from the activity (not counted)
   --minutes      stop: minutes you really worked (use after falling asleep or leaving); replaces the clock time
   --add-min      stop/fixlast: minutes of work to ADD (e.g. worked while the timer was paused)
   --no-loot      start/stop: do not value the items you picked up
   example: python -m eve_profit stop --add-min 5

TRAINPLAN  -  what to train now/next
   --hours        hours to plan / training hours to show
   example: python -m eve_profit trainplan --hours 24

ACTIVITIES  -  all timed runs
   example: python -m eve_profit activities

STATUS  -  where data is stored, row counts
   example: python -m eve_profit status

PAUSE  -  freeze the running timer
   example: python -m eve_profit pause

RESUME  -  unfreeze it
   example: python -m eve_profit resume

DOCS  -  refresh md/STATE.md and md/COMMANDS.md; --check shows doc/code drift
   --check        docs: show where the notes and the code disagree
   --quiet        docs: write the files, print nothing
   example: python -m eve_profit docs --check

FIXLAST  -  correct the last timed run (--add-min N, --isk N)
   --add-min      stop/fixlast: minutes of work to ADD (e.g. worked while the timer was paused)
   --isk          ISK amount
   --activity     name of the activity (use the same name each time)
   --delete       fixlast: delete that timed run (e.g. a timer started by mistake)
   example: python -m eve_profit fixlast --activity "step 2 Soldier" --isk 180000

AGENTS  -  agents we know: open offers, your runs with them, agents near you by level, standings
   example: python -m eve_profit agents

BUY  -  where to BUY an item cheapest near you (for agent jobs: acquire these goods)
   --item         bestprice: item name or type id
   --qty          bestprice: quantity (default: what you hold here, else 1)
   --radius       buy: how many jumps around you to look for sellers
   example: python -m eve_profit buy --item "Cap Booster 25" --qty 20

CAREERS  -  ISK/hr per career path from your timed runs; which to try next
   example: python -m eve_profit careers

MODELS  -  the map of every activity: modeled, unmodeled, locked
   example: python -m eve_profit models

Scripts: python scripts/agent_steps.py [next|list|done|skip|back|reset]  - Level 1 agent checklist.
```
