
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
import sqlite3, csv, io, math, os
from functools import wraps
from datetime import datetime
import qrcode

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-in-production")
DB = os.path.abspath(os.path.join(app.root_path, os.environ.get("DATABASE_PATH", "inventory.db")))
QR_DIR = os.path.join(app.root_path, "static", "qr")
SAMPLE_CSV = os.path.join(app.root_path, "sample_dataset.csv")
os.makedirs(QR_DIR, exist_ok=True)


# ---------------- DSA: Hash Table ----------------
# Python dictionary gives average O(1) lookup by QR/barcode.
chemical_cache = {}


# ---------------- DSA: AVL Tree ----------------
class AVLNode:
    def __init__(self, key, chemical):
        self.key = key
        self.chemical = chemical
        self.left = None
        self.right = None
        self.height = 1

class AVLTree:
    def height(self, node):
        return node.height if node else 0

    def rotate_right(self, y):
        x = y.left
        t2 = x.right
        x.right = y
        y.left = t2
        y.height = 1 + max(self.height(y.left), self.height(y.right))
        x.height = 1 + max(self.height(x.left), self.height(x.right))
        return x

    def rotate_left(self, x):
        y = x.right
        t2 = y.left
        y.left = x
        x.right = t2
        x.height = 1 + max(self.height(x.left), self.height(x.right))
        y.height = 1 + max(self.height(y.left), self.height(y.right))
        return y

    def insert(self, node, key, chemical):
        if not node:
            return AVLNode(key, chemical)
        if key < node.key:
            node.left = self.insert(node.left, key, chemical)
        elif key > node.key:
            node.right = self.insert(node.right, key, chemical)
        else:
            node.chemical = chemical
            return node

        node.height = 1 + max(self.height(node.left), self.height(node.right))
        balance = self.height(node.left) - self.height(node.right)

        if balance > 1 and key < node.left.key:
            return self.rotate_right(node)
        if balance < -1 and key > node.right.key:
            return self.rotate_left(node)
        if balance > 1 and key > node.left.key:
            node.left = self.rotate_left(node.left)
            return self.rotate_right(node)
        if balance < -1 and key < node.right.key:
            node.right = self.rotate_right(node.right)
            return self.rotate_left(node)
        return node

    def inorder(self, node, result):
        if node:
            self.inorder(node.left, result)
            result.append(node.chemical)
            self.inorder(node.right, result)


# ---------------- DSA: Queue ----------------
class AlertQueue:
    def __init__(self):
        self.items = []

    def enqueue(self, item):
        self.items.append(item)

    def dequeue(self):
        return self.items.pop(0) if self.items else None


# ---------------- DSA: Stack ----------------
class UndoStack:
    def __init__(self):
        self.items = []

    def push(self, item):
        self.items.append(item)

    def pop(self):
        return self.items.pop() if self.items else None


def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS chemicals (
        barcode TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT,
        current_weight REAL NOT NULL DEFAULT 0,
        max_capacity REAL NOT NULL DEFAULT 0,
        unit TEXT NOT NULL DEFAULT 'g',
        hazard TEXT NOT NULL DEFAULT 'General',
        location TEXT DEFAULT '',
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('attendee','manager'))
    );

    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        barcode TEXT NOT NULL,
        username TEXT NOT NULL,
        action TEXT NOT NULL,
        old_weight REAL,
        new_weight REAL,
        timestamp TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        barcode TEXT NOT NULL,
        message TEXT NOT NULL,
        created_at TEXT NOT NULL,
        resolved INTEGER DEFAULT 0
    );
    """)
    # Demo accounts. Change these before real deployment.
    try:
        conn.execute("INSERT INTO users(username,password,role) VALUES (?,?,?)",
                     ("manager", "manager123", "manager"))
        conn.execute("INSERT INTO users(username,password,role) VALUES (?,?,?)",
                     ("student", "student123", "attendee"))
    except sqlite3.IntegrityError:
        pass
    conn.commit()
    conn.close()
    rebuild_structures()

def rebuild_structures():
    global chemical_cache, avl
    conn = db()
    rows = conn.execute("SELECT * FROM chemicals").fetchall()
    conn.close()
    chemical_cache = {r["barcode"]: dict(r) for r in rows}
    avl = AVLTree()
    root = None
    for r in rows:
        root = avl.insert(root, r["barcode"], dict(r))
    return root

avl = AVLTree()
avl_root = None

def get_all_chemicals_sorted():
    global avl_root
    avl_root = None
    conn = db()
    rows = conn.execute("SELECT * FROM chemicals").fetchall()
    conn.close()
    root = None
    for r in rows:
        root = avl.insert(root, r["barcode"], dict(r))
    result = []
    avl.inorder(root, result)
    return result

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

def manager_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("role") != "manager":
            flash("Manager access required.", "error")
            return redirect(url_for("dashboard"))
        return view(*args, **kwargs)
    return wrapped

def add_alert_if_low(barcode, new_weight, max_capacity):
    if max_capacity > 0 and new_weight < 0.20 * max_capacity:
        conn = db()
        message = f"Low stock: {barcode} is below 20% of capacity."
        conn.execute("INSERT INTO alerts(barcode,message,created_at) VALUES (?,?,?)",
                     (barcode, message, datetime.now().isoformat(timespec="seconds")))
        conn.commit()
        conn.close()

@app.route("/")
def home():
    return render_template("home.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        conn = db()
        user = conn.execute("SELECT * FROM users WHERE username=? AND password=?",
                            (username, password)).fetchone()
        conn.close()
        if user:
            session["username"] = user["username"]
            session["role"] = user["role"]
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.route("/dashboard")
@login_required
def dashboard():
    chemicals = get_all_chemicals_sorted()
    conn = db()
    alerts = conn.execute("SELECT * FROM alerts WHERE resolved=0 ORDER BY id ASC").fetchall()
    conn.close()
    return render_template("dashboard.html", chemicals=chemicals, alerts=alerts)

@app.route("/chemical/<barcode>")
def chemical(barcode):
    # QR code points here. The barcode string is the lookup key.
    item = chemical_cache.get(barcode)
    if not item:
        conn = db()
        row = conn.execute("SELECT * FROM chemicals WHERE barcode=?", (barcode,)).fetchone()
        conn.close()
        item = dict(row) if row else None
    if not item:
        return render_template("not_found.html", barcode=barcode), 404
    return render_template("chemical.html", chemical=item)

@app.route("/chemical/<barcode>/transaction", methods=["POST"])
@login_required
def transaction(barcode):
    conn = db()
    row = conn.execute("SELECT * FROM chemicals WHERE barcode=?", (barcode,)).fetchone()
    if not row:
        conn.close()
        flash("Chemical not found.", "error")
        return redirect(url_for("dashboard"))

    action = request.form["action"]
    if action == "borrow" and row["hazard"] in ("Dangerous", "Hazardous") and session["role"] != "manager":
        conn.close()
        flash("This chemical requires manager authorization.", "error")
        return redirect(url_for("chemical", barcode=barcode))

    old_weight = row["current_weight"]
    new_weight = old_weight
    if action == "return":
        try:
            new_weight = float(request.form["new_weight"])
        except ValueError:
            conn.close()
            flash("Enter a valid weight.", "error")
            return redirect(url_for("chemical", barcode=barcode))

    conn.execute("INSERT INTO transactions(barcode,username,action,old_weight,new_weight,timestamp) VALUES (?,?,?,?,?,?)",
                 (barcode, session["username"], action, old_weight, new_weight,
                  datetime.now().isoformat(timespec="seconds")))
    conn.execute("UPDATE chemicals SET current_weight=? WHERE barcode=?",
                 (new_weight, barcode))
    conn.commit()
    conn.close()

    if action == "return":
        add_alert_if_low(barcode, new_weight, row["max_capacity"])
    rebuild_structures()
    flash(f"{action.title()} recorded for {row['name']}.", "success")
    return redirect(url_for("chemical", barcode=barcode))

@app.route("/manager/add", methods=["GET", "POST"])
@manager_required
def add_chemical():
    if request.method == "POST":
        data = (
            request.form["barcode"].strip(),
            request.form["name"].strip(),
            request.form["description"].strip(),
            float(request.form["current_weight"]),
            float(request.form["max_capacity"]),
            request.form["unit"].strip(),
            request.form["hazard"],
            request.form["location"].strip(),
            datetime.now().isoformat(timespec="seconds")
        )
        conn = db()
        try:
            conn.execute("""INSERT INTO chemicals
                (barcode,name,description,current_weight,max_capacity,unit,hazard,location,created_at)
                VALUES (?,?,?,?,?,?,?,?,?)""", data)
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            flash("That QR/barcode value already exists.", "error")
            return redirect(url_for("add_chemical"))
        conn.close()
        rebuild_structures()
        generate_qr(data[0])
        flash("Chemical added and QR code generated.", "success")
        return redirect(url_for("dashboard"))
    return render_template("add.html")

@app.route("/manager/import", methods=["GET", "POST"])
@manager_required
def import_csv():
    if request.method == "POST":
        file = request.files.get("file")
        if not file:
            flash("Choose a CSV file.", "error")
            return redirect(url_for("import_csv"))
        try:
            text = file.stream.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            flash("CSV must be a UTF-8 encoded file.", "error")
            return redirect(url_for("import_csv"))

        reader = csv.DictReader(io.StringIO(text))
        required = {
            "barcode", "name", "description", "current_weight",
            "max_capacity", "unit", "hazard", "location"
        }
        if reader.fieldnames:
            reader.fieldnames = [field.strip().lower() for field in reader.fieldnames]
        if not required.issubset(set(reader.fieldnames or [])):
            flash("CSV columns are incorrect. Download the sample template.", "error")
            return redirect(url_for("import_csv"))

        records = []
        try:
            for row_number, row in enumerate(reader, start=2):
                if None in row:
                    raise ValueError(f"Row {row_number} has more values than the header.")

                values = {key: (value or "").strip() for key, value in row.items()}
                if not values["barcode"] or not values["name"] or not values["unit"] or not values["hazard"]:
                    raise ValueError(f"Row {row_number} is missing a required value.")
                try:
                    current_weight = float(values["current_weight"])
                    max_capacity = float(values["max_capacity"])
                except ValueError:
                    raise ValueError(f"Row {row_number} has an invalid weight or capacity.") from None
                if (not math.isfinite(current_weight) or not math.isfinite(max_capacity)
                        or current_weight < 0 or max_capacity < 0):
                    raise ValueError(f"Row {row_number} has a negative or non-finite weight or capacity.")

                records.append((
                    values["barcode"], values["name"], values["description"],
                    current_weight, max_capacity, values["unit"], values["hazard"],
                    values["location"], datetime.now().isoformat(timespec="seconds")
                ))
        except (csv.Error, ValueError) as error:
            flash(f"Could not import CSV: {error}", "error")
            return redirect(url_for("import_csv"))

        if not records:
            flash("The CSV contains no chemical records.", "error")
            return redirect(url_for("import_csv"))

        conn = db()
        conn.executemany("""INSERT OR REPLACE INTO chemicals
            (barcode,name,description,current_weight,max_capacity,unit,hazard,location,created_at)
            VALUES (?,?,?,?,?,?,?,?,?)""", records)
        conn.commit()
        conn.close()
        for record in records:
            generate_qr(record[0])
        rebuild_structures()
        flash(f"Imported {len(records)} chemicals.", "success")
        return redirect(url_for("dashboard"))
    return render_template("import.html")

@app.route("/manager/import/template")
@manager_required
def download_import_template():
    return send_file(
        SAMPLE_CSV,
        mimetype="text/csv",
        as_attachment=True,
        download_name="sample_dataset.csv"
    )

@app.route("/manager/alerts")
@manager_required
def alerts():
    conn = db()
    rows = conn.execute("SELECT * FROM alerts ORDER BY resolved ASC, id DESC").fetchall()
    conn.close()
    return render_template("alerts.html", alerts=rows)

@app.route("/manager/alerts/<int:alert_id>/resolve", methods=["POST"])
@manager_required
def resolve_alert(alert_id):
    conn = db()
    conn.execute("UPDATE alerts SET resolved=1 WHERE id=?", (alert_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("alerts"))

@app.route("/manager/undo", methods=["POST"])
@manager_required
def undo():
    conn = db()
    last = conn.execute("SELECT * FROM transactions ORDER BY id DESC LIMIT 1").fetchone()
    if not last:
        conn.close()
        flash("Nothing to undo.", "error")
        return redirect(url_for("dashboard"))
    conn.execute("UPDATE chemicals SET current_weight=? WHERE barcode=?",
                 (last["old_weight"], last["barcode"]))
    conn.execute("DELETE FROM transactions WHERE id=?", (last["id"],))
    conn.commit()
    conn.close()
    rebuild_structures()
    flash("Last transaction undone.", "success")
    return redirect(url_for("dashboard"))

@app.route("/manager/qr/<barcode>")
@manager_required
def qr(barcode):
    path = os.path.join(QR_DIR, f"{barcode}.png")
    if not os.path.exists(path):
        generate_qr(barcode)
    return send_file(path, mimetype="image/png")

def generate_qr(barcode):
    # Set PUBLIC_BASE_URL on the deployed server, e.g. https://your-site.onrender.com
    base = os.environ.get("PUBLIC_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
    target = f"{base}/chemical/{barcode}"
    img = qrcode.make(target)
    img.save(os.path.join(QR_DIR, f"{barcode}.png"))

@app.route("/health")
def health():
    return {"status": "ok"}

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
