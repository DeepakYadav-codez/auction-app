"""Cricket scoring engine (pure Python, no Flask). Used by app.py."""

WICKET_TYPES = ["bowled", "caught", "lbw", "run out", "stumped", "hit wicket"]
BOWLER_WICKETS = {"bowled", "caught", "lbw", "stumped", "hit wicket"}
KINDS = ("normal", "wd", "nb", "b", "lb")


def is_legal(extra_type):
    return extra_type not in ("wd", "nb")


def team_runs(b):
    return b.runs_bat + b.extra_runs


def conceded(b):
    """Runs charged to the bowler (byes and leg-byes are not)."""
    return b.runs_bat + (b.extra_runs if b.extra_type in ("wd", "nb") else 0)


def overs_str(legal):
    return f"{legal // 6}.{legal % 6}"


def ball_label(b):
    return f"{b.over_no}.{b.legal_before + 1}"


def ball_spec(kind, runs):
    """runs = runs the batters ran. Wide: runs on top of the wide."""
    if kind == "wd":
        return dict(runs_bat=0, extra_runs=1 + runs)
    if kind == "nb":
        return dict(runs_bat=runs, extra_runs=1)
    if kind in ("b", "lb"):
        return dict(runs_bat=0, extra_runs=runs)
    return dict(runs_bat=runs, extra_runs=0)


def totals(balls):
    runs = sum(team_runs(b) for b in balls)
    wickets = sum(1 for b in balls if b.is_wicket)
    legal = sum(1 for b in balls if is_legal(b.extra_type))
    return runs, wickets, legal


def apply_ball(inn, prior, n_xi, max_overs, target, kind, runs,
               wicket="", out_who="striker", fielder=""):
    """Score one ball. Updates inn (striker, non_striker, bowler, done).
    Returns (ball_fields, end_reason)."""
    legal_total = sum(1 for b in prior if is_legal(b.extra_type))
    over_no, legal_before = divmod(legal_total, 6)
    spec = ball_spec(kind, runs)
    extra_type = None if kind == "normal" else kind
    out_id = None
    if wicket:
        out_id = inn.striker_id if out_who == "striker" else inn.non_striker_id
    ball = dict(
        innings=inn.number, over_no=over_no, legal_before=legal_before,
        batter_id=inn.striker_id, non_striker_id=inn.non_striker_id, bowler_id=inn.bowler_id,
        runs_bat=spec["runs_bat"], extra_type=extra_type, extra_runs=spec["extra_runs"],
        is_wicket=bool(wicket), wicket_type=wicket or None, out_player_id=out_id,
        fielder=(fielder or "").strip()[:40] or None,
    )
    if runs % 2 == 1:
        inn.striker_id, inn.non_striker_id = inn.non_striker_id, inn.striker_id
    if wicket:
        if inn.striker_id == out_id:
            inn.striker_id = None
        elif inn.non_striker_id == out_id:
            inn.non_striker_id = None
    if is_legal(extra_type):
        legal_total += 1
        if legal_total % 6 == 0:
            inn.striker_id, inn.non_striker_id = inn.non_striker_id, inn.striker_id
            inn.bowler_id = None
    runs_total = sum(team_runs(b) for b in prior) + spec["runs_bat"] + spec["extra_runs"]
    wickets = sum(1 for b in prior if b.is_wicket) + (1 if wicket else 0)
    reason = None
    if wickets >= n_xi - 1:
        reason = "all out"
    elif legal_total >= max_overs * 6:
        reason = "overs"
    elif target is not None and runs_total >= target:
        reason = "target"
    if reason:
        inn.done = True
    return ball, reason


def dismissal(b, names):
    w = b.wicket_type
    bn = names.get(b.bowler_id, "?")
    f = b.fielder or ""
    if w == "bowled":
        return f"b {bn}"
    if w == "lbw":
        return f"lbw b {bn}"
    if w == "caught":
        return f"c & b {bn}" if f == bn else f"c {f or 'fielder'} b {bn}"
    if w == "stumped":
        return f"st {f or 'keeper'} b {bn}"
    if w == "hit wicket":
        return f"hit wicket b {bn}"
    return f"run out ({f})" if f else "run out"


def chip(b):
    if b.is_wicket:
        return dict(text="W", cls="w")
    if b.extra_type == "wd":
        return dict(text="wd" if b.extra_runs == 1 else f"wd+{b.extra_runs - 1}", cls="ex")
    if b.extra_type == "nb":
        return dict(text="nb" if b.runs_bat == 0 else f"nb+{b.runs_bat}", cls="ex")
    if b.extra_type == "b":
        return dict(text=f"{b.extra_runs}b", cls="ex")
    if b.extra_type == "lb":
        return dict(text=f"{b.extra_runs}lb", cls="ex")
    if b.runs_bat == 0:
        return dict(text="•", cls="dot")
    return dict(text=str(b.runs_bat), cls="four" if b.runs_bat == 4 else "six" if b.runs_bat == 6 else "run")


def ball_text(b, names):
    bo, ba = names.get(b.bowler_id, "?"), names.get(b.batter_id, "?")
    if b.is_wicket:
        return f"{bo} to {ba}: OUT! {names.get(b.out_player_id, '?')} {dismissal(b, names)}"
    if b.extra_type == "wd":
        d = "wide" + (f" +{b.extra_runs - 1}" if b.extra_runs > 1 else "")
    elif b.extra_type == "nb":
        d = "no-ball" + (f", {b.runs_bat} off the bat" if b.runs_bat else "")
    elif b.extra_type == "b":
        d = f"{b.extra_runs} bye{'s' if b.extra_runs != 1 else ''}"
    elif b.extra_type == "lb":
        d = f"{b.extra_runs} leg-bye{'s' if b.extra_runs != 1 else ''}"
    elif b.runs_bat == 0:
        d = "no run"
    elif b.runs_bat == 4:
        d = "FOUR"
    elif b.runs_bat == 6:
        d = "SIX"
    else:
        d = f"{b.runs_bat} run{'s' if b.runs_bat != 1 else ''}"
    return f"{bo} to {ba}: {d}"


def summarize(inn, balls, xi_ids, names):
    bat, order, bowl, over_map, fow = {}, [], {}, {}, []
    ex = {"wd": 0, "nb": 0, "b": 0, "lb": 0}
    runs = wk = legal = 0

    def touch(pid):
        if pid is None or pid in bat:
            return
        bat[pid] = dict(id=pid, name=names.get(pid, "?"), runs=0, balls=0, fours=0, sixes=0, out=None)
        order.append(pid)

    def bowler(pid):
        if pid not in bowl:
            bowl[pid] = dict(id=pid, name=names.get(pid, "?"), balls=0, runs=0, wkts=0, maidens=0)
        return bowl[pid]

    for b in balls:
        touch(b.batter_id)
        touch(b.non_striker_id)
        runs += team_runs(b)
        if b.extra_type:
            ex[b.extra_type] += b.extra_runs
        if b.extra_type != "wd":
            s = bat[b.batter_id]
            s["balls"] += 1
            s["runs"] += b.runs_bat
            s["fours"] += 1 if b.runs_bat == 4 else 0
            s["sixes"] += 1 if b.runs_bat == 6 else 0
        bw = bowler(b.bowler_id)
        bw["runs"] += conceded(b)
        om = over_map.setdefault((b.bowler_id, b.over_no), dict(legal=0, runs=0))
        om["runs"] += conceded(b)
        if is_legal(b.extra_type):
            bw["balls"] += 1
            om["legal"] += 1
            legal += 1
        if b.is_wicket:
            wk += 1
            if b.wicket_type in BOWLER_WICKETS:
                bw["wkts"] += 1
            touch(b.out_player_id)
            bat[b.out_player_id]["out"] = dismissal(b, names)
            fow.append(f"{wk}-{runs} ({names.get(b.out_player_id, '?')}, {ball_label(b)} ov)")
    for (pid, _), om in over_map.items():
        if om["legal"] == 6 and om["runs"] == 0:
            bowl[pid]["maidens"] += 1
    touch(inn.striker_id)
    touch(inn.non_striker_id)

    batting = []
    for pid in order:
        s = dict(bat[pid])
        s["sr"] = f"{s['runs'] * 100 / s['balls']:.1f}" if s["balls"] else "-"
        s["is_out"] = s["out"] is not None
        if not s["is_out"]:
            s["out"] = "not out"
        s["at_crease"] = pid in (inn.striker_id, inn.non_striker_id)
        s["on_strike"] = pid == inn.striker_id
        batting.append(s)
    bowling = []
    for pid, r in bowl.items():
        r = dict(r)
        r["overs"] = overs_str(r["balls"])
        r["econ"] = f"{r['runs'] * 6 / r['balls']:.2f}" if r["balls"] else "-"
        bowling.append(r)
    cur_over = legal // 6
    return dict(
        runs=runs, wickets=wk, legal=legal, overs=overs_str(legal),
        run_rate=f"{runs * 6 / legal:.2f}" if legal else "0.00",
        batting=batting, bowling=bowling,
        did_not_bat=[names.get(p, "?") for p in xi_ids if p not in bat],
        extras=dict(ex, total=sum(ex.values())), fow=fow,
        chips=[chip(b) for b in balls if b.over_no == cur_over],
        commentary=[dict(label=ball_label(b), text=ball_text(b, names), wicket=b.is_wicket,
                         big=(b.runs_bat in (4, 6) and not b.extra_type == "wd")) for b in reversed(balls[-12:])],
    )


def result_text(team1, team2, runs1, runs2, wkts2, n_xi2):
    if runs2 > runs1:
        left = (n_xi2 - 1) - wkts2
        return f"{team2} won by {left} wicket{'s' if left != 1 else ''}"
    if runs2 == runs1:
        return "Match tied"
    diff = runs1 - runs2
    return f"{team1} won by {diff} run{'s' if diff != 1 else ''}"
