"""Does ESI offer a route for something? Downloads the public ESI route list and prints the routes whose path or summary contains a word
(e.g. project, freelance, opportunity, job), with the login scope each one needs."""
import json
import urllib.request

SPECS = ("https://esi.evetech.net/meta/openapi.json", "https://esi.evetech.net/latest/swagger.json", "https://esi.evetech.net/_latest/swagger.json")


def find(words):
    spec, err = None, ""
    for u in SPECS:
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "eve_profit route finder", "X-Compatibility-Date": "2025-12-16"})
            spec = json.load(urllib.request.urlopen(req, timeout=40))
            break
        except Exception as e:                                          # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
    if not spec:
        return "Could not download the ESI route list (" + err + ")."
    out = []
    for path, ops in spec.get("paths", {}).items():
        for method, op in ops.items():
            if not isinstance(op, dict):
                continue
            text = (path + " " + str(op.get("summary", "")) + " " + str(op.get("operationId", ""))).lower()
            if any(w.lower() in text for w in words):
                sec = op.get("security") or []
                scopes = sorted({s for d in sec for v in d.values() for s in v})
                params = [x.get("name", "?") + ("*" if x.get("required") else "") for x in op.get("parameters", []) if isinstance(x, dict) and x.get("in") in ("query", "header")]
                out.append(f"{method.upper():5} {path}   {op.get('summary', '')}" + (f"   params: {', '.join(params)}" if params else "") + (f"   needs: {', '.join(scopes)}" if scopes else "   (public)"))
    return "\n".join(sorted(out)) or "No ESI route mentions: " + ", ".join(words)
