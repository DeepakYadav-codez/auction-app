import os
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.types import TypeDecorator, Float

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
    if t and t.players:
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
    if p and p.status == "sold":
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


if __name__ == "__main__":
    app.run(debug=True)