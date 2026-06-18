from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
from datetime import datetime
import os
import string
import random

app = Flask(__name__)
app.secret_key = 'vnet_ledger_secure_key'

# --- SECURITY CONFIG ---
PASSWORD_FILE = "master_password.txt"
DEFAULT_PASSWORD_HASH = "scrypt:32768:8:1$KlFWbdpi820yuwd8$fac25421c637c37b620218375ce7e9fab37b7a42d5e9f3441a0a2c7663cc603d642233551a45ab6d2fdddfeba2e88b3a258fdd4ac15647afb5b29ceb9eaaced5"

def load_password():
    """ෆයිල් එක තිබේ නම් කියවයි, නැතහොත් Default Hash එක ලබා දෙයි"""
    if os.path.exists(PASSWORD_FILE):
        with open(PASSWORD_FILE, "r") as f:
            return f.read().strip()
    return DEFAULT_PASSWORD_HASH

def save_password(new_hash):
    """නව මුරපදයේ Hash එක ස්ථිරවම ෆයිල් එකේ ලියයි"""
    with open(PASSWORD_FILE, "w") as f:
        f.write(new_hash)

def is_logged_in():
    return session.get('authenticated') == True

def generate_slug(length=8):
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def get_previous_month_db():
    now = datetime.now()
    month = now.month
    year = now.year
    if month == 1:
        prev_month = 12
        prev_year = year - 1
    else:
        prev_month = month - 1
        prev_year = year
    prev_date = datetime(prev_year, prev_month, 1)
    return f"{prev_date.strftime('%B_%Y')}.db"

def get_db_path():
    # Priority 1: Manual selection from history/dropdown
    if 'selected_db' in session:
        return session['selected_db']
    # Priority 2: Real-time system clock
    return f"{datetime.now().strftime('%B_%Y')}.db"

def init_db(db_path):
    exists = os.path.exists(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS entries 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  user TEXT, slug TEXT, date TEXT, 
                  description TEXT, amount REAL, type TEXT)''')
    conn.commit()

    # AUTO CARRY-FORWARD: If the file is brand new, pull balances from last month
    if not exists:
        prev_db = get_previous_month_db()
        if os.path.exists(prev_db):
            conn_prev = sqlite3.connect(prev_db)
            c_prev = conn_prev.cursor()
            c_prev.execute("SELECT DISTINCT user, slug FROM entries")
            users_info = c_prev.fetchall()
            
            for user, slug in users_info:
                c_prev.execute("SELECT amount, type FROM entries WHERE user = ?", (user,))
                rows = c_prev.fetchall()
                prev_bal = sum(r[0] if r[1] == 'take' else -r[0] for r in rows)
                
                # Carry over non-zero balances
                if prev_bal != 0:
                    etype = 'take' if prev_bal >= 0 else 'give'
                    current_month_start = datetime.now().strftime("%m/01") # වත්මන් මාසයේ 01 වෙනිදා දිනය ලෙස ලබා ගැනීම (උදා: 05/01)
                    c.execute("INSERT INTO entries (user, slug, date, description, amount, type) VALUES (?, ?, ?, ?, ?, ?)",
                    (user, slug, current_month_start, "Previous Balance", abs(prev_bal), etype))
            conn_prev.close()
            conn.commit()
    conn.close()

def get_balance(db_path, username):
    if not os.path.exists(db_path): return 0
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT amount, type FROM entries WHERE user = ?", (username,))
    rows = c.fetchall()
    conn.close()
    return sum(r[0] if r[1] == 'take' else -r[0] for r in rows)

# --- ROUTES ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password')
        current_hash = load_password()  # ෆයිල් එකේ තියෙන අලුත්ම Password එක කියවීම
        
        if check_password_hash(current_hash, password):
            session['authenticated'] = True
            return redirect(url_for('select_user'))
        else:
            # 🛠️ ඔයාගේ අලුත් flow එකට අනුව වැරදි නම් 'invalid_password' පේජ් එකට රීඩිරෙක්ට් කරයි
            return redirect(url_for('invalid_password'))
            
    return render_template('login.html')

@app.route('/invalid_password')
def invalid_password():
    # 🛠️ FIX: Internal Server Error එක නැති කරන්න මෙතන render_template එක හරියටම දාන්න
    return render_template('invalid_password.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/forget-password', methods=['GET', 'POST'])
def forget_password():
    if request.method == 'POST':
        current_pass = request.form.get('current_pass')
        new_pass = request.form.get('new_pass')
        confirm_pass = request.form.get('confirm_pass')

        current_hash = load_password() # දැනට පවතින මුරපදය ලබා ගැනීම

        # 1. දැනට පවතින මුරපදය නිවැරදිදැයි බැලීම
        if not check_password_hash(current_hash, current_pass):
            return "<script>alert('Current password එක වැරදියි!'); window.location.href='/forget-password';</script>"
            
        # 2. අලුත් මුරපද දෙක එකිනෙකට සමානදැයි බැලීම
        if new_pass != confirm_pass:
            return "<script>alert('New password සහ Confirm password එකිනෙකට ගැලපෙන්නේ නැත!'); window.location.href='/forget-password';</script>"

        # 3. නව මුරපදය Hash කර ස්ථිරවම සේව් කිරීම
        new_hash = generate_password_hash(new_pass)
        save_password(new_hash) 
        
        return "<script>alert('Password එක සාර්ථකව වෙනස් කරන ලදී!'); window.location.href='/login';</script>"

    return render_template('forget-password.html')

@app.route('/')
def select_user():
    if not is_logged_in(): return redirect(url_for('login'))
    db_path = get_db_path()
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT DISTINCT user FROM entries")
    users = [row[0] for row in c.fetchall()]
    conn.close()
    is_live = 'selected_db' not in session
    display_month = db_path.replace('.db', '').replace('_', ' ')
    return render_template('select.html', users=users, current_month=display_month, is_live=is_live)

@app.route('/add_user', methods=['POST'])
def add_user():
    if not is_logged_in(): return redirect(url_for('login'))
    new_user = request.form.get('new_username').strip()
    if new_user:
        db_path = get_db_path()
        init_db(db_path) 
        new_slug = generate_slug()
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("INSERT INTO entries (user, slug, date, description, amount, type) VALUES (?, ?, ?, ?, ?, ?)",
                  (new_user, new_slug, datetime.now().strftime("%m/%d"), "Account Opened", 0, "take"))
        conn.commit()
        conn.close()
    return redirect(url_for('select_user'))

@app.route('/delete_user/<username>')
def delete_user(username):
    if not is_logged_in(): return redirect(url_for('login'))
    db_path = get_db_path()
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("DELETE FROM entries WHERE user = ?", (username,))
        conn.commit()
        conn.close()
    return redirect(url_for('admin'))

@app.route('/set_month/<filename>')
def set_month(filename):
    if not is_logged_in(): return redirect(url_for('login'))
    if filename == "LIVE":
        session.pop('selected_db', None)
    else:
        session['selected_db'] = filename
    return redirect(url_for('select_user'))

@app.route('/admin')
def admin():
    if not is_logged_in(): return redirect(url_for('login'))
    db_path = get_db_path()
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT user, slug FROM entries GROUP BY user")
    rows = c.fetchall()
    user_data = []
    grand_total = 0
    for r in rows:
        bal = get_balance(db_path, r[0])
        user_data.append({'name': r[0], 'slug': r[1], 'balance': round(bal, 2)})
        grand_total += bal
    conn.close()
    return render_template('admin.html', users=user_data, grand_total=round(grand_total, 2), month=db_path.replace('.db',''))

@app.route('/user/<username>')
def index(username):
    if not is_logged_in(): return redirect(url_for('login'))
    db_path = get_db_path()
    
    # පද්ධතියේ ඇති සියලුම .db ගොනු ලබා ගැනීම (Dropdown එක සඳහා)
    all_db_files = [f for f in os.listdir('.') if f.endswith('.db')]
    files = sorted(all_db_files, key=lambda f: datetime.strptime(f.replace('.db', ''), '%B_%Y'), reverse=True)
    
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT * FROM entries WHERE user = ? ORDER BY date ASC, id ASC", (username,))
    rows = c.fetchall()
    balance = get_balance(db_path, username)
    conn.close()
    
    # files, current_month සහ is_live යන දත්ත template එකට යැවීම
    return render_template('index.html', rows=rows, balance=round(balance, 2), username=username, files=files, current_month=db_path, is_live=('selected_db' not in session))

@app.route('/add/<username>', methods=['POST'])
def add_entry(username):
    if not is_logged_in(): return redirect(url_for('login'))
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT slug FROM entries WHERE user = ? LIMIT 1", (username,))
    res = c.fetchone()
    slug = res[0] if res else generate_slug()
    date_str = request.form.get('custom_date') or datetime.now().strftime("%m/%d")
    c.execute("INSERT INTO entries (user, slug, date, description, amount, type) VALUES (?, ?, ?, ?, ?, ?)",
              (username, slug, date_str, request.form['description'], float(request.form['amount']), request.form['type']))
    conn.commit()
    conn.close()
    return redirect(url_for('index', username=username))

@app.route('/delete_entry/<username>/<int:entry_id>')
def delete_entry(username, entry_id):
    if not is_logged_in(): return redirect(url_for('login'))
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('index', username=username))

@app.route('/history')
def history():
    if not is_logged_in(): return redirect(url_for('login'))
    # පැරණි පේළිය වෙනුවට මෙය දාන්න:
    all_db_files = [f for f in os.listdir('.') if f.endswith('.db')]
    files = sorted(all_db_files, key=lambda f: datetime.strptime(f.replace('.db', ''), '%B_%Y'), reverse=True)
    return render_template('history.html', files=files)

@app.route('/view/<slug>')
def user_view(slug):
    # Only reset to LIVE if the user is visiting freshly (without selection)
    if not request.args.get('stay'):
        session.pop('selected_db', None)
    
    db_path = get_db_path()
    init_db(db_path)
    all_db_files = [f for f in os.listdir('.') if f.endswith('.db')]
    files = sorted(all_db_files, key=lambda f: datetime.strptime(f.replace('.db', ''), '%B_%Y'), reverse=True)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT user FROM entries WHERE slug = ? LIMIT 1", (slug,))
    res = c.fetchone()
    if not res: return render_template('notfound.html'), 404
    username = res[0]
    c.execute("SELECT * FROM entries WHERE user = ? ORDER BY date ASC, id ASC", (username,))
    rows = c.fetchall()
    balance = get_balance(db_path, username)
    conn.close()
    return render_template('user_view.html', rows=rows, balance=round(balance, 2), username=username, files=files, current_month=db_path, is_live=('selected_db' not in session))

@app.route('/admin/set_month/<username>/<filename>')
def admin_set_month(username, filename):
    if not is_logged_in(): return redirect(url_for('login'))
    if filename == "LIVE":
        session.pop('selected_db', None)
    else:
        session['selected_db'] = filename
    # මෙතනදී කෙලින්ම ආපහු අදාළ User ගේ index (Manage) පිටුවටම රීඩිරෙක්ට් කරනවා!
    return redirect(url_for('index', username=username))

@app.route('/view/<slug>/set_month/<filename>')
def user_view_set_month(slug, filename):
    if filename == "LIVE":
        session.pop('selected_db', None)
    elif os.path.exists(filename) and filename.endswith('.db'):
        session['selected_db'] = filename
    return redirect(url_for('user_view', slug=slug, stay=1))
    

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=8888)
