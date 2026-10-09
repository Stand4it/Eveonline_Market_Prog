"""`docs`: keep the md/ folder in step with the code, and show where the notes think we are versus where the code is.
Writes md/STATE.md (live facts) and md/COMMANDS.md (every command), and `docs --check` prints the differences."""
import glob
import json
import os
import re
import subprocess
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MD = os.path.join(ROOT, "md")

COMMAND_HELP = {
    "init": "create the database", "mock": "load an offline demo market", "sde": "import game data from a file",
    "scan": "rank everything you can do now (add --live to download prices)", "plan": "same as scan, no download",
    "watch": "keep re-scanning", "profile": "set system/cargo in the profile", "login": "log a character in (once per character)",
    "sync": "read skills, wallet, assets, location from the game", "log": "enter a timed run by hand",
    "go": "send the route of a ranked task to the game client", "universe": "load the map and items",
    "esimap": "build a map from ESI around you", "fleet": "list parked ships", "skills": "ISK/hr-measured skill advice + training plan",
    "diag": "check the game data", "explain": "why an item ranks where it does", "check": "re-check live prices of a ranked task",
    "stock": "value of everything you own", "along": "sell on the way to a destination", "fit": "what is fitted to your ship",
    "zkill": "refresh the hauler-loss map", "next": "ONE next step (agent offers, sell/list, best trade)", "keep": "build or sell your materials",
    "bpbuy": "buy a blueprint to use your stock?", "update": "has a game patch changed the data?", "bestprice": "best buyers for one item anywhere",
    "sellplan": "sell/list/carry/detour/haul per stack", "day": "chain the best tasks for N hours", "now": "sync + scan + next step + price check",
    "chars": "compare your characters", "combatfit": "set real DPS/EHP/tank for combat", "journey": "plan a whole trip with pickups and trades",
    "compare": "list here or make the trip?", "start": "start timing an activity", "stop": "stop timing, read payouts and loot, log it",
    "pause": "freeze the running timer", "resume": "unfreeze it", "trainplan": "what to train now/next", "activities": "all timed runs",
    "status": "where data is stored, row counts", "docs": "refresh md/STATE.md and md/COMMANDS.md; --check shows doc/code drift",
    "fixlast": "correct the last timed run (--add-min N, --isk N)",
    "buy": "where to BUY an item cheapest near you (for agent jobs: acquire these goods)",
    "agents": "agents we know: open offers, your runs with them, agents near you by level, standings",
}


CMD_OPTS = {
    "scan": ["--live", "--away", "--max-age", "--regions", "--max-pages", "--top"], "plan": ["--top"], "watch": ["--live", "--interval", "--away"],
    "profile": ["--system", "--cargo"], "login": ["--char", "--client-id"], "sync": ["--char"], "log": ["--activity", "--isk", "--hours"],
    "go": ["--pick", "--send", "--away", "--top"], "universe": ["--force", "--sde-file", "--sde-url", "--depth"], "esimap": ["--depth"],
    "sde": ["--sde-file", "--sde-url"], "skills": ["--hours"], "explain": ["--pick"], "check": ["--pick"], "stock": ["--top"], "along": ["--to"],
    "next": ["--sync", "--all"], "keep": ["--to"], "bpbuy": ["--to"], "bestprice": ["--item", "--qty"], "sellplan": ["--to", "--world"],
    "day": ["--hours", "--cash", "--no-stock"], "now": ["--fast"], "combatfit": ["--dps", "--ehp", "--tank", "--value", "--ship"],
    "journey": ["--to", "--live", "--quick", "--detour", "--max-age"], "compare": ["--to", "--detour"], "start": ["--activity", "--no-loot"],
    "stop": ["--isk", "--paused", "--minutes", "--add-min", "--no-loot"], "trainplan": ["--hours"], "docs": ["--check", "--quiet"], "fixlast": ["--add-min", "--isk", "--activity", "--delete"], "buy": ["--item", "--qty", "--radius"],
}
EXAMPLES = {
    "now": "python -m eve_profit now --fast", "next": "python -m eve_profit next", "scan": "python -m eve_profit scan --live",
    "start": 'python -m eve_profit start --activity "Agent L1 step 4 Arabeton"', "stop": "python -m eve_profit stop --add-min 5",
    "pause": "python -m eve_profit pause", "resume": "python -m eve_profit resume", "bestprice": 'python -m eve_profit bestprice --item "Zydrine" --qty 25000',
    "journey": "python -m eve_profit journey --to Jita --live --quick", "compare": "python -m eve_profit compare --to Jita",
    "go": "python -m eve_profit go --pick 1 --send", "trainplan": "python -m eve_profit trainplan --hours 24", "skills": "python -m eve_profit skills --hours 72",
    "combatfit": 'python -m eve_profit combatfit --ship "Vexor" --dps 450 --ehp 60000 --tank 200 --value 30000000',
    "fixlast": 'python -m eve_profit fixlast --activity "step 2 Soldier" --isk 180000', "agents": "python -m eve_profit agents", "buy": 'python -m eve_profit buy --item "Cap Booster 25" --qty 20', "docs": "python -m eve_profit docs --check", "status": "python -m eve_profit status",
    "log": 'python -m eve_profit log --activity "Level 2 security mission" --isk 8000000 --hours 1', "day": "python -m eve_profit day --hours 8",
    "sellplan": "python -m eve_profit sellplan --world 5", "login": "python -m eve_profit login", "sync": "python -m eve_profit sync",
}
OPT_FALLBACK = {"--db": "database file (default E:\\EveProfit\\eve_profit.db)", "--profile": "profile file (default profile.json)",
                "--max-pages": "limit pages per region (testing)", "--top": "how many rows to show", "--hours": "hours to plan / training hours to show",
                "--pick": "which ranked task (1 = best)", "--isk": "ISK amount", "--activity": "name of the activity (use the same name each time)",
                "--to": "destination (or system) name", "--item": "item name or type id", "--qty": "quantity", "--send": "really set waypoints in the game client",
                "--interval": "seconds between scans", "--depth": "jumps around your system", "--force": "reload even if already loaded",
                "--sde-file": "local game-data file to import", "--sde-url": "download game data from this address", "--regions": "region ids, comma separated",
                "--system": "set your current system", "--cargo": "set your cargo m3", "--world": "also check the N biggest stacks in every region",
                "--cash": "extra ISK you expect to have", "--no-stock": "leave out selling/listing stock", "--ship": "ship hull name",
                "--dps": "damage per second (from Pyfa)", "--ehp": "effective HP (from Pyfa)", "--tank": "sustained repair per second", "--value": "ship + fit value in ISK",
                "--detour": "jumps off the route to look", "--quick": "refresh only the items you own", "--paused": "minutes you were away (not counted)",
                "--add-min": "minutes of work to add", "--no-loot": "do not value picked-up items", "--fast": "skip the market re-scan", "--check": "show where notes and code disagree",
                "--quiet": "write files, print nothing", "--away": "unattended mode: long safe autopilot hauls only", "--max-age": "skip regions fresher than this many minutes",
                "--live": "use real ESI market data", "--sync": "refresh your character data first", "--char": "which character (label, id or part of the name)",
                "--client-id": "EVE app client id (else client_id.txt)"}
GLOBAL_OPTS = ["--db", "--profile", "--char", "--sync", "--client-id"]


def option_help():
    s = open(os.path.join(ROOT, "eve_profit", "cli.py"), encoding="utf-8").read()
    out = {}
    for m in re.finditer(r'add_argument\("(--[\w-]+)"([^\n]*)', s):
        h = re.search(r'help="([^"]*)"', m.group(2))
        out[m.group(1)] = h.group(1) if h else ""
    return out


def reference_lines(commands):
    oh = option_help()
    L = ["EVE PROFIT - EVERY COMMAND AND ITS OPTIONS", "=" * 44,
         "Run each as:  python -m eve_profit <command> [options]   (in PowerShell, from the repo folder)", "",
         "OPTIONS THAT WORK WITH EVERY COMMAND:"]
    L += [f"   {o:<14} {oh.get(o) or OPT_FALLBACK.get(o, '')}" for o in GLOBAL_OPTS] + [""]
    for c in commands:
        L.append(f"{c.upper()}  -  {COMMAND_HELP.get(c, '(no description yet)')}")
        for o in CMD_OPTS.get(c, []):
            L.append(f"   {o:<14} {oh.get(o) or OPT_FALLBACK.get(o, '')}")
        L.append(f"   example: {EXAMPLES.get(c, 'python -m eve_profit ' + c)}")
        L.append("")
    L.append("Scripts: python scripts/agent_steps.py [next|list|done|skip|back|reset]  - Level 1 agent checklist.")
    return L


def write_docx(path, lines):
    import zipfile
    from xml.sax.saxutils import escape
    paras = []
    for l in lines:
        bold = l and not l.startswith(" ") and (l.isupper() or l[:1].isupper() and "  -  " in l)
        run = ("<w:rPr><w:b/></w:rPr>" if bold else "") + '<w:t xml:space="preserve">' + escape(l) + "</w:t>"
        paras.append("<w:p><w:r>" + run + "</w:r></w:p>")
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
           + "".join(paras) + "</w:body></w:document>")
    def put(z, name, data):                     # fixed timestamp: the same text always gives the same bytes (no git churn)
        info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(info, data)

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        put(z, "[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        put(z, "_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        put(z, "word/document.xml", doc)


def code_commands():
    s = open(os.path.join(ROOT, "eve_profit", "cli.py"), encoding="utf-8").read()
    return re.findall(r'"(\w+)"', re.search(r'choices=\[([^\]]*)\]', s).group(1))


def git(*args):
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def count_tests():
    n = 0
    for f in glob.glob(os.path.join(ROOT, "tests", "test_*.py")):
        n += len(re.findall(r"^\s+def test_", open(f, encoding="utf-8").read(), re.M))
    return n


def gather(con=None, db_path=""):
    d = {"when": time.strftime("%Y-%m-%d %H:%M"), "branch": git("rev-parse", "--abbrev-ref", "HEAD"), "commit": git("log", "--oneline", "-1"),
         "dirty": [l for l in git("status", "--short").splitlines() if l.strip()], "commands": code_commands(), "tests": count_tests(),
         "db": db_path, "session": None, "agent_offers": None, "runs": []}
    if con is not None:
        try:
            r = con.execute("SELECT value FROM meta WHERE key='session'").fetchone()
            if r:
                d["session"] = json.loads(r[0])
            d["runs"] = [dict(x) for x in con.execute("SELECT activity,isk,hours,ship,ts FROM activity_log ORDER BY ts DESC LIMIT 8")]
        except Exception:
            pass
    f = os.path.join(ROOT, "agent_offers.json")
    if os.path.exists(f):
        try:
            offers = json.load(open(f, encoding="utf-8")).get("offers", [])
            d["agent_offers"] = [o["agent"].split(" (")[0] + ": " + o["mission"][:60] for o in offers if o.get("available", True)]
        except (ValueError, KeyError):
            pass
    return d


def write(d):
    os.makedirs(MD, exist_ok=True)
    L = ["# STATE (auto-generated by `python -m eve_profit docs` - do not edit by hand)", "",
         "(No timestamps or commit ids here on purpose: this file only changes when the real state changes. "
         "Uncommitted files and the last commit are shown by `docs --check` and `git status`.)",
         f"Branch `{d['branch']}` | tests defined: {d['tests']} | commands in code: {len(d['commands'])}", ""]
    if d["agent_offers"]:
        L.append("\nOpen agent offers (agent_offers.json):")
        L += [f"- {x}" for x in d["agent_offers"]]
    open(os.path.join(MD, "STATE.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    # per-PC facts (timer, timed runs) go to a git-ignored file so the tracked notes never differ between machines
    L = ["# LOCAL STATE (this PC only, git-ignored, auto-generated by `docs`)", ""]
    if d["session"]:
        s = d["session"]
        L.append(f"\nTimer RUNNING: '{s['activity']}' since {time.strftime('%H:%M', time.localtime(s['t']))}"
                 + (" (PAUSED: run `python -m eve_profit resume`)" if s.get("pause_t") else "") + ". Finish with `python -m eve_profit stop`.")
    else:
        L.append("\nNo timer running.")
    if d["runs"]:
        L.append("\nLatest timed runs:")
        L += [f"- {time.strftime('%m-%d %H:%M', time.localtime(r['ts']))} {r['activity']}: {r['isk']:,.0f} ISK in {r['hours'] * 60:.0f} min ({r['isk'] / max(r['hours'], 1e-9):,.0f} ISK/hr) {r['ship'] or ''}" for r in d["runs"]]
    open(os.path.join(MD, "LOCAL_STATE.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    ref = reference_lines(d["commands"])
    C = ["# COMMANDS (auto-generated; also md/COMMANDS.txt for Notepad and md/COMMANDS.docx for Word)", "", "```"] + ref + ["```"]
    open(os.path.join(MD, "COMMANDS.txt"), "w", encoding="utf-8").write("\n".join(ref) + "\n")
    write_docx(os.path.join(MD, "COMMANDS.docx"), ref)
    open(os.path.join(MD, "COMMANDS.md"), "w", encoding="utf-8").write("\n".join(C) + "\n")


def check(d):
    """-> list of differences between what the notes say and what the code is."""
    out = []
    missing = [c for c in d["commands"] if c not in COMMAND_HELP]
    if missing:
        out.append(f"commands in code with no description in docs.py: {', '.join(missing)}")
    extra = [c for c in COMMAND_HELP if c not in d["commands"]]
    if extra:
        out.append(f"commands described in docs.py but not in the code: {', '.join(extra)}")
    for f in sorted(glob.glob(os.path.join(MD, "*.md")) + [os.path.join(ROOT, "README.md")]):
        if os.path.basename(f) in ("STATE.md", "COMMANDS.md"):
            continue
        text = open(f, encoding="utf-8").read()
        for m in re.finditer(r"(\d+) (?:unit )?tests", text):
            if int(m.group(1)) != d["tests"] and int(m.group(1)) > 20:
                out.append(f"{os.path.basename(f)} says {m.group(1)} tests, code has {d['tests']}")
        for c in set(re.findall(r"python -m eve_profit (\w+)", text)):
            if c not in d["commands"] and c not in ("x",):
                out.append(f"{os.path.basename(f)} mentions `{c}`, which is not a command in the code")
    if d["dirty"]:
        out.append(f"{len(d['dirty'])} uncommitted file(s): the notes on GitHub may be behind what is on disk")
    if d["session"] and d["session"].get("pause_t"):
        out.append("a timer is PAUSED: the code is waiting for `resume`")
    return sorted(set(out))
