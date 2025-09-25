from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
import pandas as pd
import matplotlib.pyplot as plt
import io
import base64
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'your_secret_key'
DATABASE = 'finance_users.db'

# ------------------- Database -------------------
def init_db():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    )
    ''')
    c.execute('''
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        category TEXT NOT NULL,
        amount REAL NOT NULL,
        type TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    ''')
    conn.commit()
    conn.close()

# ------------------- Helper Functions -------------------
def load_transactions(user_id):
    conn = sqlite3.connect(DATABASE)
    df = pd.read_sql_query(
        "SELECT * FROM transactions WHERE user_id = ?",
        conn, params=(user_id,), parse_dates=['date']
    )
    conn.close()
    return df

def save_transaction(user_id, date, category, amount, type_of_transaction):
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute('''
        INSERT INTO transactions (user_id, date, category, amount, type)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, date, category, amount, type_of_transaction))
    conn.commit()
    conn.close()

# ------------------- Routes -------------------
@app.route('/')
def home():
    return render_template('home.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        hashed_password = generate_password_hash(password)

        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        try:
            c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed_password))
            conn.commit()
            flash("Επιτυχής εγγραφή! Συνδεθείτε.", "success")
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash("Το username υπάρχει ήδη.", "danger")
        finally:
            conn.close()
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = sqlite3.connect(DATABASE)
        c = conn.cursor()
        c.execute("SELECT id, password FROM users WHERE username = ?", (username,))
        user = c.fetchone()
        conn.close()

        if user and check_password_hash(user[1], password):
            session['user_id'] = user[0]
            session['username'] = username
            return redirect(url_for('index'))
        else:
            flash("Λανθασμένο username ή password.", "danger")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/index')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    df = load_transactions(session['user_id'])
    total_income = df[df['type']=='Εισόδημα']['amount'].sum() if not df.empty else 0
    total_expense = df[df['type']=='Έξοδος']['amount'].sum() if not df.empty else 0
    balance = total_income - total_expense

    return render_template('index.html',
                           income=total_income,
                           expense=total_expense,
                           balance=balance,
                           username=session['username'])

@app.route('/add', methods=['GET', 'POST'])
def add_transaction():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    categories = ['Φαγητό', 'Μετακινήσεις', 'Σπίτι', 'Ψυχαγωγία', 'Εκπαίδευση', 'Άλλα']

    if request.method == 'POST':
        date = request.form['date']
        category = request.form['category']
        amount = float(request.form['amount'])
        type_of_transaction = request.form['type']
        save_transaction(session['user_id'], date, category, amount, type_of_transaction)
        return redirect(url_for('index'))

    return render_template('add.html', categories=categories)

@app.route('/summary')
def summary():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    df = load_transactions(session['user_id'])
    expenses = df[df['type'] == 'Έξοδος']  # Μόνο έξοδα
    if expenses.empty:
        return render_template('summary.html', chart=None, data=None)

    # Ομαδοποίηση ανά κατηγορία και άθροισμα
    grouped = expenses.groupby('category')['amount'].sum().sort_values(ascending=False)

    # Δημιουργία γραφήματος
    fig, ax = plt.subplots()
    grouped.plot(kind='bar', ax=ax, color='lightcoral')
    ax.set_title('Έξοδα ανά Κατηγορία')
    ax.set_ylabel('Ποσό (€)')
    ax.set_xlabel('Κατηγορίες')

    # Μετατροπή σε base64 για HTML
    img = io.BytesIO()
    plt.tight_layout()
    plt.savefig(img, format='png')
    plt.close(fig)
    img.seek(0)
    img_base64 = base64.b64encode(img.getvalue()).decode('utf-8')

    return render_template('summary.html', chart=img_base64, data=grouped)


@app.route('/monthly')
def monthly():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # Φόρτωσε τις συναλλαγές του χρήστη
    df = load_transactions(session['user_id'])

    if df.empty:
        msg = "Δεν υπάρχουν δεδομένα για να εμφανιστούν γραφήματα."
        return render_template('monthly.html', chart=None, message=msg)

    # Μετατροπή ημερομηνίας σε μήνα
    df['date'] = pd.to_datetime(df['date'])
    df['Μήνας'] = df['date'].dt.strftime('%Y-%m')  # πχ 2025-09

    # Σύνοψη ανά μήνα για Έσοδα και Έξοδα
    summary = df.pivot_table(index='Μήνας', columns='type', values='amount', aggfunc='sum').fillna(0)

    # Γράφημα
    fig, ax = plt.subplots(figsize=(8, 5))
    colors = []
    if 'Εισόδημα' in summary.columns and 'Έξοδος' in summary.columns:
        summary[['Εισόδημα', 'Έξοδος']].plot(kind='bar', ax=ax, color=['green', 'red'])
    elif 'Εισόδημα' in summary.columns:
        summary[['Εισόδημα']].plot(kind='bar', ax=ax, color=['green'])
    elif 'Έξοδος' in summary.columns:
        summary[['Έξοδος']].plot(kind='bar', ax=ax, color=['red'])
    else:
        msg = "Δεν υπάρχουν δεδομένα για να εμφανιστούν γραφήματα."
        return render_template('monthly.html', chart=None, message=msg)

    ax.set_title('Έσοδα και Έξοδα ανά Μήνα')
    ax.set_ylabel('Ποσό (€)')
    ax.set_xlabel('Μήνας')
    ax.legend()

    # Μετατροπή σε base64 για εμφάνιση στο HTML
    img = io.BytesIO()
    plt.tight_layout()
    plt.savefig(img, format='png')
    img.seek(0)
    img_base64 = base64.b64encode(img.getvalue()).decode('utf-8')
    plt.close(fig)

    return render_template('monthly.html', chart=img_base64, message=None)


@app.route('/categories')
def categories():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    # Φόρτωση συναλλαγών του χρήστη
    df = load_transactions(session['user_id'])

    # Αν δεν υπάρχουν συναλλαγές
    if df.empty:
        flash("Δεν υπάρχουν διαθέσιμα δεδομένα για τις κατηγορίες.", "info")
        return render_template('categories.html', chart=None, data=None)

    # Βεβαιωνόμαστε ότι η στήλη 'amount' είναι αριθμητική
    df['amount'] = pd.to_numeric(df['amount'], errors='coerce')

    # Φιλτράρουμε μόνο τα έξοδα
    expenses = df[df['type'] == 'Έξοδος']

    # Αν δεν υπάρχουν έξοδα
    if expenses.empty:
        flash("Δεν υπάρχουν έξοδα για να εμφανιστούν.", "info")
        return render_template('categories.html', chart=None, data=None)

    # Ομαδοποίηση κατά κατηγορία
    grouped = expenses.groupby('category')['amount'].sum().sort_values(ascending=False)

    # Δημιουργία γραφήματος
    fig, ax = plt.subplots()
    grouped.plot(kind='bar', ax=ax, color='lightcoral')
    ax.set_title('Έξοδα ανά Κατηγορία')
    ax.set_ylabel('Ποσό (€)')
    ax.set_xlabel('Κατηγορίες')

    # Μετατροπή σε base64 για εμφάνιση στο HTML
    img = io.BytesIO()
    plt.tight_layout()
    plt.savefig(img, format='png')
    plt.close(fig)
    img.seek(0)
    img_base64 = base64.b64encode(img.getvalue()).decode('utf-8')

    return render_template('categories.html', chart=img_base64, data=grouped)

@app.route('/clear_transactions')
def clear_transactions_route():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    c.execute("DELETE FROM transactions WHERE user_id = ?", (session['user_id'],))
    conn.commit()
    conn.close()

    flash("Όλες οι συναλλαγές διαγράφηκαν!", "success")
    return redirect(url_for('index'))

# ------------------- Run App -------------------
if __name__ == '__main__':
    init_db()
    app.run(debug=True)
