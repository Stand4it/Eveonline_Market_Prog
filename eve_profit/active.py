"""Which character are you playing right now? Every logged-in character has its own tokens file; the one that is
online is picked automatically (else the one used last), so no --char is needed day to day."""
import glob
import json
import os
import re

from . import sso
from .esi import ESI


def known():
    """[{label, path, id, name}] for every logged-in character ('' = the original tokens.json)."""
    out = []
    paths = [("", "tokens.json")] + [(f[len("tokens_"):-len(".json")], f) for f in sorted(glob.glob("tokens_*.json"))]
    for label, path in paths:
        if label == "pending" or not os.path.exists(path):
            continue
        try:
            with open(path) as f:
                rec = json.load(f)
            out.append({"label": label, "path": path, "id": rec["character_id"], "name": rec.get("character_name", "")})
        except (OSError, ValueError, KeyError):
            continue
    return out


def is_online(client_id, k):
    """True / False, or None when unknown (old login without the online permission, or ESI trouble)."""
    try:
        esi = ESI(timeout=10)
        esi.token, cid = sso.get_token(client_id, k["path"])
        data, _ = esi.get(f"/characters/{cid}/online/")
        return bool(data.get("online"))
    except Exception:
        return None


def _state_file(state_dir):
    return os.path.join(state_dir, "active.json")


def _last(state_dir):
    try:
        with open(_state_file(state_dir)) as f:
            return json.load(f).get("label")
    except (OSError, ValueError):
        return None


def remember(state_dir, label):
    try:
        os.makedirs(state_dir or ".", exist_ok=True)
        with open(_state_file(state_dir), "w") as f:
            json.dump({"label": label}, f)
    except OSError:
        pass


def match(name_or_label):
    """--char accepts the label, a character id, or part of the character name."""
    ks = known()
    key = name_or_label.strip().lower()
    for k in ks:
        if key in (k["label"].lower(), str(k["id"])):
            return k["label"]
    for k in ks:
        if key and key in k["name"].lower():
            return k["label"]
    return name_or_label


def pick(client_id, state_dir, say=print):
    ks = known()
    if not ks:
        return ""
    if len(ks) == 1:
        return ks[0]["label"]
    on = [k for k in ks if is_online(client_id, k)]
    last = _last(state_dir)
    if on:
        choice = next((k for k in on if k["label"] == last), on[0])
        why = "online now"
    else:
        choice = next((k for k in ks if k["label"] == last), ks[0])
        names = ", ".join(k["name"] or k["label"] or "main" for k in ks)
        why = (f"cannot tell who is online, using the one you used last. Logged-in characters: {names}. "
               f"Run `login` while playing the one you want (also adds the online permission)")
    remember(state_dir, choice["label"])
    say(f"[playing as {choice['name'] or choice['label'] or 'main'}: {why}]  (override with --char NAME)")
    return choice["label"]


def register(pending="tokens_pending.json"):
    """After `login`: file the new token under the right character. -> (label, name)."""
    with open(pending) as f:
        rec = json.load(f)
    for k in known():
        if k["id"] == rec["character_id"]:
            os.replace(pending, k["path"])
            return k["label"], rec.get("character_name", "")
    slug = re.sub(r"[^a-z0-9]", "", (rec.get("character_name", "").split() or ["char"])[-1].lower()) or "char"
    if os.path.exists(f"tokens_{slug}.json"):
        slug += str(rec["character_id"])
    target = "tokens.json" if not os.path.exists("tokens.json") else f"tokens_{slug}.json"
    os.replace(pending, target)
    return ("" if target == "tokens.json" else slug), rec.get("character_name", "")
