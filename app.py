import os
from flask import Flask, render_template, request, redirect, url_for, flash, abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.types import TypeDecorator, Float

import cricket

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///auction.db"
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-secret")
db = SQLAlchemy(app)

MAX_SQUAD = 15      # max players per team
UNIT = "L"          # currency label (L = lakh)


class Money(TypeDecorator):
    """Stores decimals (0.2, 0.4...) and gives back 40 instead of 40.0."""
    impl = Float
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else round(float(value), 2)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        value = round(value, 2)
        return int(value) if value == int(value) else value


def num(text):
    try:
        return round(float(text), 2)
    except (TypeError, ValueError):
        return 0


def fmt(n):
    n = round(n, 2)
    return int(n) if n == int(n) else n


class Team(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    budget = db.Column(Money, nullable=False)
    remaining = db.Column(Money, nullable=False)
    players = db.relationship("Player", backref="team")

    @property
    def spent(self):
        return round(self.budget - self.remaining, 2)


class Player(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    role = db.Column(db.String(40), default="")
    base_price = db.Column(Money, nullable=False)
    status = db.Column(db.String(20), default="available")  # available/sold/unsold
    sold_price = db.Column(Money)
    team_id = db.Column(db.Integer, db.ForeignKey("team.id"))


class Match(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    team_a_id = db.Column(db.Integer, db.ForeignKey("team.id"), nullable=False)
    team_b_id = db.Column(db.Integer, db.ForeignKey("team.id"), nullable=False)
    overs = db.Column(db.Integer, nullable=False, default=5)
    toss_winner_id = db.Column(db.Integer, db.ForeignKey("team.id"))
    toss_choice = db.Column(db.String(10), default="bat")
    status = db.Column(db.String(20), default="setup")      # setup / live / finished
    current_innings = db.Column(db.Integer, default=1)
    result = db.Column(db.String(200))
    team_a = db.relationship("Team", foreign_keys=[team_a_id])
    team_b = db.relationship("Team", foreign_keys=[team_b_id])
    toss_winner = db.relationship("Team", foreign_keys=[toss_winner_id])


class MatchPlayer(db.Model):          # the playing XI of each team in a match
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey("match.id"), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey("team.id"), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey("player.id"), nullable=False)


class Innings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey("match.id"), nullable=False)
    number = db.Column(db.Integer, nullable=False)
    batting_team_id = db.Column(db.Integer, db.ForeignKey("team.id"), nullable=False)
    bowling_team_id = db.Column(db.Integer, db.ForeignKey("team.id"), nullable=False)
    striker_id = db.Column(db.Integer)
    non_striker_id = db.Column(db.Integer)
    bowler_id = db.Column(db.Integer)
    done = db.Column(db.Boolean, default=False)


class Ball(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    match_id = db.Column(db.Integer, db.ForeignKey("match.id"), nullable=False)
    innings = db.Column(db.Integer, nullable=False)
    over_no = db.Column(db.Integer, nullable=False)          # 0-based
    legal_before = db.Column(db.Integer, nullable=False)     # legal balls already bowled in this over
    batter_id = db.Column(db.Integer, nullable=False)        # on strike
    non_striker_id = db.Column(db.Integer, nullable=False)
    bowler_id = db.Column(db.Integer, nullable=False)
    runs_bat = db.Column(db.Integer, default=0)
    extra_type = db.Column(db.String(4))                     # wd / nb / b / lb
    extra_runs = db.Column(db.Integer, default=0)
    is_wicket = db.Column(db.Boolean, default=False)
    wicket_type = db.Column(db.String(20))
    out_player_id = db.Column(db.Integer)
    fielder = db.Column(db.String(40))


with app.app_context():
    db.create_all()


@app.context_processor
def inject():
    return dict(UNIT=UNIT, MAX_SQUAD=MAX_SQUAD)


@app.route("/")
def dashboard():
    teams = Team.query.order_by(Team.name).all()
    stats = {
        "available": Player.query.filter_by(status="available").count(),
        "sold": Player.query.filter_by(status="sold").count(),
        "unsold": Player.query.filter_by(status="unsold").count(),
    }
    sold = Player.query.filter_by(status="sold").order_by(Player.sold_price.desc()).all()
    top = sold[0] if sold else None
    total_spent = round(sum(p.sold_price for p in sold), 2)
    return render_template("dashboard.html", teams=teams, stats=stats, top=top,
                           sold=sold, total_spent=total_spent)


@app.route("/teams", methods=["GET", "POST"])
def teams():
    if request.method == "POST":
        name = request.form["name"].strip()
        budget = num(request.form["budget"])
        if not name or budget <= 0:
            flash("Enter a team name and a valid budget.", "error")
        elif Team.query.filter_by(name=name).first():
            flash("Team already exists.", "error")
        else:
            db.session.add(Team(name=name, budget=budget, remaining=budget))
            db.session.commit()
            flash(f"Team '{name}' added.", "ok")
        return redirect(url_for("teams"))
    return render_template("teams.html", teams=Team.query.order_by(Team.name).all())


@app.post("/teams/<int:tid>/delete")
def delete_team(tid):
    t = db.session.get(Team, tid)
    if t and Match.query.filter((Match.team_a_id == tid) | (Match.team_b_id == tid)).first():
        flash("This team is part of a match. Delete the match first.", "error")
    elif t and t.players:
        flash("Can't delete a team that has players. Undo their sales first.", "error")
    elif t:
        db.session.delete(t)
        db.session.commit()
        flash("Team deleted.", "ok")
    return redirect(url_for("teams"))


@app.route("/players", methods=["GET", "POST"])
def players():
    if request.method == "POST":
        name = request.form["name"].strip()
        base = num(request.form["base_price"])
        if not name or base <= 0:
            flash("Enter a player name and a valid base price.", "error")
        else:
            db.session.add(Player(name=name, role=request.form.get("role", "").strip(),
                                  base_price=base))
            db.session.commit()
            flash(f"Player '{name}' added.", "ok")
        return redirect(url_for("players"))
    return render_template("players.html", players=Player.query.order_by(Player.id).all())


@app.post("/players/<int:pid>/delete")
def delete_player(pid):
    p = db.session.get(Player, pid)
    if p and p.status == "sold":
        flash("Undo the sale before deleting this player.", "error")
    elif p:
        db.session.delete(p)
        db.session.commit()
        flash("Player deleted.", "ok")
    return redirect(url_for("players"))


@app.route("/auction")
def auction():
    pid = request.args.get("player", type=int)
    player = db.session.get(Player, pid) if pid else None
    if not player or player.status == "sold":
        player = Player.query.filter_by(status="available").order_by(Player.id).first()
    teams = Team.query.order_by(Team.name).all()
    team_data = [dict(id=t.id, name=t.name, remaining=t.remaining, count=len(t.players))
                 for t in teams]
    left = Player.query.filter_by(status="available").count()
    return render_template("auction.html", player=player, teams=teams,
                           team_data=team_data, left=left)


@app.post("/auction/sell/<int:pid>")
def sell(pid):
    p = db.session.get(Player, pid)
    t = db.session.get(Team, request.form.get("team_id", type=int) or 0)
    price = round(request.form.get("price", type=float) or 0, 2)
    if not p or not t:
        flash("Pick a team to sell to.", "error")
    elif p.status == "sold":
        flash("Player already sold.", "error")
    elif price < p.base_price:
        flash("Price is below the base price.", "error")
    elif price > t.remaining:
        flash(f"{t.name} doesn't have enough budget.", "error")
    elif len(t.players) >= MAX_SQUAD:
        flash(f"{t.name} already has a full squad ({MAX_SQUAD}).", "error")
    else:
        p.status, p.sold_price, p.team_id = "sold", price, t.id
        t.remaining = round(t.remaining - price, 2)
        db.session.commit()
        flash(f"SOLD! {p.name} to {t.name} for {fmt(price)}{UNIT}", "ok")
    return redirect(url_for("auction"))


@app.post("/auction/unsold/<int:pid>")
def unsold(pid):
    p = db.session.get(Player, pid)
    if p and p.status == "available":
        p.status = "unsold"
        db.session.commit()
        flash(f"{p.name} went unsold.", "ok")
    return redirect(url_for("auction"))


@app.post("/auction/undo/<int:pid>")
def undo(pid):
    p = db.session.get(Player, pid)
    if p and MatchPlayer.query.filter_by(player_id=p.id).first():
        flash(f"{p.name} has played in a match, so the sale can't be undone.", "error")
    elif p and p.status == "sold":
        p.team.remaining = round(p.team.remaining + p.sold_price, 2)
        p.status, p.sold_price, p.team_id = "available", None, None
        db.session.commit()
        flash(f"Sale of {p.name} undone.", "ok")
    return redirect(request.referrer or url_for("dashboard"))


@app.post("/auction/reauction")
def reauction():
    n = Player.query.filter_by(status="unsold").update({"status": "available"})
    db.session.commit()
    flash(f"{n} unsold player(s) moved back into the auction.", "ok")
    return redirect(url_for("auction"))



# ======================= MATCHES / SCORECARD =======================

def get_or_404(model, ident):
    obj = db.session.get(model, ident)
    if obj is None:
        abort(404)
    return obj


def team_name(tid):
    t = db.session.get(Team, tid)
    return t.name if t else "?"


def xi_ids(mid, team_id):
    return [mp.player_id for mp in MatchPlayer.query.filter_by(match_id=mid, team_id=team_id)]


def player_names():
    return {p.id: p.name for p in Player.query.all()}


def balls_of(mid, number):
    return Ball.query.filter_by(match_id=mid, innings=number).order_by(Ball.id).all()


def innings_of(mid, number):
    return Innings.query.filter_by(match_id=mid, number=number).first()


def finish_match(m):
    i1, i2 = innings_of(m.id, 1), innings_of(m.id, 2)
    r1, _, _ = cricket.totals(balls_of(m.id, 1))
    r2, w2, _ = cricket.totals(balls_of(m.id, 2))
    n2 = len(xi_ids(m.id, i2.batting_team_id))
    m.result = cricket.result_text(team_name(i1.batting_team_id), team_name(i2.batting_team_id),
                                   r1, r2, w2, n2)
    m.status = "finished"


@app.route("/matches")
def matches():
    return render_template("matches.html",
                           matches=Match.query.order_by(Match.id.desc()).all())


@app.route("/matches/new", methods=["GET", "POST"])
def match_new():
    all_teams = Team.query.order_by(Team.name).all()
    if request.method == "POST":
        ta = db.session.get(Team, request.form.get("team_a", type=int) or 0)
        tb = db.session.get(Team, request.form.get("team_b", type=int) or 0)
        overs = request.form.get("overs", type=int) or 0
        toss, choice = request.form.get("toss"), request.form.get("choice")
        if not ta or not tb or ta.id == tb.id:
            flash("Pick two different teams.", "error")
        elif not 1 <= overs <= 50:
            flash("Overs must be between 1 and 50.", "error")
        elif toss not in ("a", "b") or choice not in ("bat", "bowl"):
            flash("Select who won the toss and what they chose.", "error")
        elif len(ta.players) < 2 or len(tb.players) < 2:
            flash("Each team needs at least 2 players bought in the auction.", "error")
        else:
            m = Match(team_a_id=ta.id, team_b_id=tb.id, overs=overs, toss_choice=choice,
                      toss_winner_id=ta.id if toss == "a" else tb.id)
            db.session.add(m)
            db.session.commit()
            return redirect(url_for("match_squads", mid=m.id))
        return redirect(url_for("match_new"))
    return render_template("match_new.html", teams=all_teams)


@app.route("/matches/<int:mid>/squads", methods=["GET", "POST"])
def match_squads(mid):
    m = get_or_404(Match, mid)
    if m.status != "setup":
        return redirect(url_for("match_view", mid=mid))
    if request.method == "POST":
        picks = {}
        for key, team in (("team_a", m.team_a), ("team_b", m.team_b)):
            chosen = {int(x) for x in request.form.getlist(key) if x.isdigit()}
            picks[team.id] = chosen & {p.id for p in team.players}
        if any(len(v) < 2 or len(v) > 11 for v in picks.values()):
            flash("Choose between 2 and 11 players for each team.", "error")
            return redirect(url_for("match_squads", mid=mid))
        for tid, ids in picks.items():
            for pid in ids:
                db.session.add(MatchPlayer(match_id=m.id, team_id=tid, player_id=pid))
        other = m.team_b if m.toss_winner_id == m.team_a_id else m.team_a
        bat, bowl = (m.toss_winner, other) if m.toss_choice == "bat" else (other, m.toss_winner)
        db.session.add(Innings(match_id=m.id, number=1, batting_team_id=bat.id, bowling_team_id=bowl.id))
        m.status, m.current_innings = "live", 1
        db.session.commit()
        return redirect(url_for("match_view", mid=mid))
    return render_template("match_squads.html", m=m)


@app.route("/matches/<int:mid>")
def match_view(mid):
    m = get_or_404(Match, mid)
    if m.status == "setup":
        return redirect(url_for("match_squads", mid=mid))
    names = player_names()
    inn = innings_of(m.id, m.current_innings)
    balls = balls_of(m.id, inn.number)
    bat_xi, bowl_xi = xi_ids(m.id, inn.batting_team_id), xi_ids(m.id, inn.bowling_team_id)
    s = cricket.summarize(inn, balls, bat_xi, names)
    live = m.status == "live" and not inn.done

    first = chase = None
    if inn.number == 2:
        r1, w1, l1 = cricket.totals(balls_of(m.id, 1))
        first = dict(team=team_name(innings_of(m.id, 1).batting_team_id), runs=r1,
                     wickets=w1, overs=cricket.overs_str(l1))
        if live:
            chase = dict(target=r1 + 1, need=r1 + 1 - s["runs"], balls_left=m.overs * 6 - s["legal"])

    out_ids = {b.out_player_id for b in balls if b.is_wicket}
    at_crease = {inn.striker_id, inn.non_striker_id}
    avail_bat = [(pid, names[pid]) for pid in bat_xi if pid not in out_ids and pid not in at_crease]
    prev_bowler = balls[-1].bowler_id if (balls and inn.bowler_id is None) else None
    avail_bowl = [(pid, names[pid]) for pid in bowl_xi if pid != prev_bowler]
    cur_bowler = next((r for r in s["bowling"] if r["id"] == inn.bowler_id), None)

    return render_template(
        "match_live.html", m=m, inn=inn, s=s, live=live, chase=chase, first=first,
        bat_team=team_name(inn.batting_team_id), bowl_team=team_name(inn.bowling_team_id),
        avail_bat=avail_bat, avail_bowl=avail_bowl, cur_bowler=cur_bowler,
        bowler_name=names.get(inn.bowler_id), striker_name=names.get(inn.striker_id),
        non_striker_name=names.get(inn.non_striker_id),
        need_bowler=live and inn.bowler_id is None,
        need_striker=live and inn.striker_id is None,
        need_non_striker=live and inn.non_striker_id is None,
        wicket_types=cricket.WICKET_TYPES)


@app.post("/matches/<int:mid>/select")
def match_select(mid):
    m = get_or_404(Match, mid)
    inn = innings_of(m.id, m.current_innings)
    if m.status != "live" or inn.done:
        return redirect(url_for("match_view", mid=mid))
    balls = balls_of(m.id, inn.number)
    out_ids = {b.out_player_id for b in balls if b.is_wicket}
    at_crease = {inn.striker_id, inn.non_striker_id}
    allowed_bat = {p for p in xi_ids(m.id, inn.batting_team_id) if p not in out_ids and p not in at_crease}
    prev_bowler = balls[-1].bowler_id if (balls and inn.bowler_id is None) else None
    allowed_bowl = {p for p in xi_ids(m.id, inn.bowling_team_id) if p != prev_bowler}
    ok = True
    for slot, field in (("striker_id", "striker"), ("non_striker_id", "non_striker")):
        if getattr(inn, slot) is None:
            v = request.form.get(field, type=int)
            if v in allowed_bat:
                setattr(inn, slot, v)
                allowed_bat.discard(v)
            else:
                ok = False
    if inn.bowler_id is None:
        v = request.form.get("bowler", type=int)
        if v in allowed_bowl:
            inn.bowler_id = v
        else:
            ok = False
    if ok:
        db.session.commit()
    else:
        db.session.rollback()
        flash("Please choose valid players (the same bowler can't bowl two overs in a row).", "error")
    return redirect(url_for("match_view", mid=mid))


@app.post("/matches/<int:mid>/ball")
def match_ball(mid):
    m = get_or_404(Match, mid)
    inn = innings_of(m.id, m.current_innings)
    back = redirect(url_for("match_view", mid=mid))
    if m.status != "live" or inn.done or None in (inn.striker_id, inn.non_striker_id, inn.bowler_id):
        flash("Select the batters and bowler first.", "error")
        return back
    kind = request.form.get("kind", "normal")
    runs = request.form.get("runs", type=int) or 0
    wicket = request.form.get("wicket", "")
    out_who = request.form.get("out_who", "striker")
    if kind not in cricket.KINDS or not 0 <= runs <= 7:
        return back
    if wicket:
        if wicket not in cricket.WICKET_TYPES:
            return back
        bad = (kind == "nb" and wicket != "run out") or \
              (kind == "wd" and wicket not in ("stumped", "run out", "hit wicket")) or \
              (kind in ("b", "lb") and wicket != "run out")
        if bad:
            flash(f"A {wicket} isn't possible on that kind of ball.", "error")
            return back
        if wicket != "run out":
            out_who, runs = "striker", 0
    prior = balls_of(m.id, inn.number)
    n_xi = len(xi_ids(m.id, inn.batting_team_id))
    target = None
    if inn.number == 2:
        target = cricket.totals(balls_of(m.id, 1))[0] + 1
    ball, reason = cricket.apply_ball(inn, prior, n_xi, m.overs, target, kind, runs,
                                      wicket, out_who, request.form.get("fielder", ""))
    db.session.add(Ball(match_id=m.id, **ball))
    if inn.done:
        if inn.number == 1:
            db.session.add(Innings(match_id=m.id, number=2, batting_team_id=inn.bowling_team_id,
                                   bowling_team_id=inn.batting_team_id))
            m.current_innings = 2
        else:
            finish_match(m)
    db.session.commit()
    return back


@app.post("/matches/<int:mid>/undo")
def match_undo(mid):
    m = get_or_404(Match, mid)
    if m.status == "setup":
        return redirect(url_for("match_squads", mid=mid))
    inn = innings_of(m.id, m.current_innings)
    balls = balls_of(m.id, inn.number)
    if not balls and inn.number == 2:
        db.session.delete(inn)
        m.current_innings = 1
        db.session.flush()
        inn = innings_of(m.id, 1)
        balls = balls_of(m.id, 1)
    if not balls:
        flash("Nothing to undo.", "error")
        return redirect(url_for("match_view", mid=mid))
    last = balls[-1]
    inn.striker_id, inn.non_striker_id, inn.bowler_id = last.batter_id, last.non_striker_id, last.bowler_id
    inn.done = False
    db.session.delete(last)
    if m.status == "finished":
        m.status, m.result = "live", None
    db.session.commit()
    flash("Last ball removed.", "ok")
    return redirect(url_for("match_view", mid=mid))


@app.route("/matches/<int:mid>/scorecard")
def match_scorecard(mid):
    m = get_or_404(Match, mid)
    if m.status == "setup":
        return redirect(url_for("match_squads", mid=mid))
    names = player_names()
    cards = []
    for inn in Innings.query.filter_by(match_id=m.id).order_by(Innings.number):
        s = cricket.summarize(inn, balls_of(m.id, inn.number), xi_ids(m.id, inn.batting_team_id), names)
        cards.append(dict(inn=inn, s=s, bat=team_name(inn.batting_team_id),
                          bowl=team_name(inn.bowling_team_id)))
    return render_template("match_scorecard.html", m=m, cards=cards)


@app.post("/matches/<int:mid>/delete")
def match_delete(mid):
    m = get_or_404(Match, mid)
    for model in (Ball, Innings, MatchPlayer):
        model.query.filter_by(match_id=mid).delete()
    db.session.delete(m)
    db.session.commit()
    flash("Match deleted.", "ok")
    return redirect(url_for("matches"))


if __name__ == "__main__":
    app.run(debug=True)
