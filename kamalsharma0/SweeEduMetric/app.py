from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import sqlite3
import os

app = Flask(__name__)
app.secret_key = "sweejal_ai_secure_key_10"
DB_FILE = "database.db"

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with app.app_context():
        db = get_db()
        
        # YAHAN AUTO-REFRESH LOGIC ADD KIYA HAI - Ye sirf questions table ko fresh karega
        db.executescript('DROP TABLE IF EXISTS questions;')
        
        db.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY, username TEXT, pin TEXT,
                xp INTEGER DEFAULT 0, questions_solved INTEGER DEFAULT 0,
                correct_answers INTEGER DEFAULT 0, streak INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS chapters (
                id INTEGER PRIMARY KEY, name TEXT, progress INTEGER DEFAULT 0
            );
            CREATE TABLE questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, chapter_id INTEGER, question_text TEXT,
                opt_a TEXT, opt_b TEXT, opt_c TEXT, opt_d TEXT, correct_opt TEXT, difficulty TEXT
            );
            CREATE TABLE IF NOT EXISTS badges (
                id INTEGER PRIMARY KEY, name TEXT, icon TEXT, description TEXT, req_xp INTEGER
            );
            CREATE TABLE IF NOT EXISTS user_badges (
                user_id INTEGER, badge_id INTEGER, UNIQUE(user_id, badge_id)
            );
        ''')
        
        # 1. Default User
        user = db.execute('SELECT * FROM users WHERE username = "Sweejal"').fetchone()
        if not user:
            db.execute('INSERT INTO users (username, pin) VALUES ("Sweejal", "1234")')

        # 2. Add Chapters
        chapters = ["Real Numbers", "Polynomials", "Pair of Linear Equations",
                    "Quadratic Equations", "Arithmetic Progressions", "Triangles",
                    "Coordinate Geometry", "Introduction to Trigonometry", "Circles",
                    "Surface Areas and Volumes", "Statistics", "Probability"]
        for i, chap in enumerate(chapters, 1):
            db.execute('INSERT OR IGNORE INTO chapters (id, name) VALUES (?, ?)', (i, chap))

        # 3. Add 60 Static Questions (5 per chapter)
        questions = [
            # Ch 1: Real Numbers
            (1, "The HCF of 96 and 404 is:", "4", "2", "6", "8", "A", "Level 1"),
            (1, "If p is a prime number, what is the LCM of p and p+1?", "p", "p+1", "p(p+1)", "1", "C", "Level 2"),
            (1, "Which of the following is an irrational number?", "√4", "√9", "√3", "√16", "C", "Level 1"),
            (1, "The decimal expansion of 17/8 will terminate after how many places?", "1", "2", "3", "4", "C", "Level 3"),
            (1, "The product of a non-zero rational and an irrational number is always:", "Rational", "Irrational", "1", "0", "B", "Level 2"),
            # Ch 2: Polynomials
            (2, "The zeroes of the polynomial x^2 - 2x - 8 are:", "2, -4", "-2, 4", "-2, -4", "2, 4", "B", "Level 1"),
            (2, "Sum of zeroes of quadratic polynomial ax^2 + bx + c is:", "c/a", "-b/a", "b/a", "-c/a", "B", "Level 1"),
            (2, "Product of zeroes of polynomial 3x^2 - 4x + 1 is:", "1/3", "-4/3", "4/3", "-1/3", "A", "Level 2"),
            (2, "If zeroes of a polynomial are 3 and -3, the polynomial is:", "x^2 - 9", "x^2 + 9", "x^2 - 3x", "x^2 + 3", "A", "Level 2"),
            (2, "A polynomial of degree 2 is called:", "Linear", "Quadratic", "Cubic", "Bi-quadratic", "B", "Level 1"),
            # Ch 3: Pair of Linear Equations
            (3, "If lines are parallel, the pair of linear equations has:", "Unique solution", "Two solutions", "No solution", "Infinite solutions", "C", "Level 1"),
            (3, "The condition for intersecting lines is:", "a1/a2 = b1/b2", "a1/a2 != b1/b2", "a1/a2 = b1/b2 = c1/c2", "None", "B", "Level 2"),
            (3, "Solve: x + y = 5 and x - y = 1", "x=2, y=3", "x=3, y=2", "x=4, y=1", "x=1, y=4", "B", "Level 2"),
            (3, "If a pair of linear equations is consistent, the lines will be:", "Parallel", "Always coincident", "Intersecting or coincident", "Always intersecting", "C", "Level 3"),
            (3, "For what value of k will lines 3x+2ky=2 and 2x+5y+1=0 be parallel?", "15/4", "4/15", "15/2", "5/4", "A", "Level 3"),
            # Ch 4: Quadratic Equations
            (4, "The standard form of a quadratic equation is:", "ax+b=0", "ax^2+bx+c=0", "ax^3+bx^2+c=0", "None", "B", "Level 1"),
            (4, "Discriminant of ax^2 + bx + c = 0 is:", "b^2 - 4ac", "4ac - b^2", "b - 4ac", "b^2 + 4ac", "A", "Level 1"),
            (4, "A quadratic equation has real and distinct roots if:", "D = 0", "D < 0", "D > 0", "D = 1", "C", "Level 2"),
            (4, "Roots of equation x^2 - 9 = 0 are:", "3, 3", "3, -3", "-3, -3", "9, -9", "B", "Level 1"),
            (4, "Maximum number of roots for a quadratic equation is:", "1", "2", "3", "4", "B", "Level 1"),
            # Ch 5: Arithmetic Progressions
            (5, "The common difference of AP: 3, 1, -1, -3... is:", "2", "-2", "3", "-1", "B", "Level 1"),
            (5, "The formula for nth term of an AP is:", "a + (n-1)d", "a + nd", "a + (n+1)d", "n/2(2a)", "A", "Level 1"),
            (5, "10th term of the AP: 2, 7, 12... is:", "47", "52", "42", "50", "A", "Level 2"),
            (5, "Sum of first n natural numbers is:", "n(n+1)/2", "n/2", "n^2", "n(n-1)/2", "A", "Level 2"),
            (5, "If a=5, d=3, what is the 5th term?", "15", "17", "20", "22", "B", "Level 2"),
            # Ch 6: Triangles
            (6, "All circles are:", "Congruent", "Similar", "Equal", "None", "B", "Level 1"),
            (6, "The ratio of corresponding sides of similar triangles is:", "Equal", "Different", "Zero", "One", "A", "Level 1"),
            (6, "Which theorem states: In a right triangle, square of hypotenuse = sum of squares of other two sides?", "Thales", "Pythagoras", "BPT", "Converse of BPT", "B", "Level 1"),
            (6, "If two angles of a triangle are equal to two angles of another, similarity is:", "SSS", "SAS", "AA", "RHS", "C", "Level 2"),
            (6, "Ratio of areas of two similar triangles is equal to square of ratio of their:", "Altitudes", "Medians", "Corresponding sides", "All of these", "D", "Level 3"),
            # Ch 7: Coordinate Geometry
            (7, "Distance of point (x,y) from origin is:", "x^2 + y^2", "√(x^2 + y^2)", "x + y", "x^2 - y^2", "B", "Level 1"),
            (7, "Midpoint of line joining (x1,y1) and (x2,y2) is:", "((x1+x2)/2, (y1+y2)/2)", "(x1-x2, y1-y2)", "((x1-x2)/2, (y1-y2)/2)", "None", "A", "Level 1"),
            (7, "Distance between (0,0) and (3,4) is:", "5", "6", "7", "12", "A", "Level 2"),
            (7, "Points A, B, C are collinear if area of triangle ABC is:", "1", "0", "-1", "Infinite", "B", "Level 2"),
            (7, "The section formula divides a line segment in a specific:", "Area", "Ratio", "Volume", "Distance", "B", "Level 1"),
            # Ch 8: Introduction to Trigonometry
            (8, "Value of sin^2 A + cos^2 A is:", "0", "1", "-1", "2", "B", "Level 1"),
            (8, "tan 45 degree equals to:", "0", "1", "√3", "1/√3", "B", "Level 1"),
            (8, "sin 30 degree equals to:", "1/2", "1/√2", "√3/2", "1", "A", "Level 1"),
            (8, "sec^2 A - tan^2 A is equal to:", "0", "1", "-1", "2", "B", "Level 2"),
            (8, "Value of cos 90 degree is:", "1", "0", "1/2", "Not defined", "B", "Level 1"),
            # Ch 9: Circles
            (9, "A line intersecting a circle in two points is called a:", "Tangent", "Secant", "Chord", "Radius", "B", "Level 1"),
            (9, "How many tangents can be drawn from an external point to a circle?", "1", "2", "3", "Infinite", "B", "Level 1"),
            (9, "Lengths of tangents drawn from an external point to a circle are:", "Unequal", "Equal", "Parallel", "Perpendicular", "B", "Level 2"),
            (9, "Angle between tangent and radius at point of contact is:", "45 deg", "60 deg", "90 deg", "180 deg", "C", "Level 1"),
            (9, "A circle can have how many parallel tangents at the most?", "1", "2", "3", "Infinite", "B", "Level 2"),
            # Ch 10: Surface Areas and Volumes
            (10, "Volume of a cylinder is:", "πr^2h", "1/3 πr^2h", "2πrh", "4/3 πr^3", "A", "Level 1"),
            (10, "Curved surface area of a cone is:", "πrl", "πr^2h", "2πr", "πr^2", "A", "Level 1"),
            (10, "Total surface area of a hemisphere is:", "2πr^2", "3πr^2", "4πr^2", "πr^2", "B", "Level 2"),
            (10, "Volume of a sphere of radius r is:", "4/3 πr^3", "2/3 πr^3", "πr^2h", "4πr^2", "A", "Level 1"),
            (10, "Volume of a cube with edge 'a' is:", "a^2", "3a", "a^3", "6a^2", "C", "Level 1"),
            # Ch 11: Statistics
            (11, "The mean of first 5 natural numbers is:", "2", "3", "4", "5", "B", "Level 2"),
            (11, "Class mark of class interval 10-20 is:", "10", "20", "15", "30", "C", "Level 1"),
            (11, "Empirical relationship between mean, median, mode is: 3 Median = Mode + ?", "Mean", "2 Mean", "3 Mean", "None", "B", "Level 2"),
            (11, "The value of observation having maximum frequency is called:", "Mean", "Median", "Mode", "Range", "C", "Level 1"),
            (11, "Cumulative frequency is used to find:", "Mean", "Median", "Mode", "Standard Deviation", "B", "Level 2"),
            # Ch 12: Probability
            (12, "Probability of a sure event is:", "0", "1", "0.5", "Infinite", "B", "Level 1"),
            (12, "P(E) + P(not E) equals to:", "0", "1", "-1", "2", "B", "Level 1"),
            (12, "Probability of getting a head on tossing a coin is:", "1", "0", "1/2", "2", "C", "Level 1"),
            (12, "Probability of an impossible event is:", "0", "1", "-1", "1/2", "A", "Level 1"),
            (12, "Probability of getting a prime number when a dice is thrown is:", "1/6", "2/6", "1/2", "1", "C", "Level 2")
        ]
        db.executemany('INSERT INTO questions (chapter_id, question_text, opt_a, opt_b, opt_c, opt_d, correct_opt, difficulty) VALUES (?,?,?,?,?,?,?,?)', questions)
        
        # 4. Badges
        badges = [
            (1, "XP Pioneer", "🌟", "Initiate learning and earn 15 XP", 15),
            (2, "Consistency", "🔥", "Reach 50 XP milestone", 50),
            (3, "Century Solver", "💯", "Earn 100 XP", 100),
            (4, "Math Scholar", "🎓", "Earn 500 XP", 500)
        ]
        for b in badges:
            db.execute('INSERT OR IGNORE INTO badges (id, name, icon, description, req_xp) VALUES (?,?,?,?,?)', b)
            
        db.commit()

@app.route('/')
def index():
    if 'user_id' in session: return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE LOWER(username)=LOWER(?) AND pin=?', 
                      (data['username'].strip(), data['pin'].strip())).fetchone()
    if user:
        session['user_id'] = user['id']
        session['username'] = user['username']
        return jsonify({"success": True, "msg": "ACCESS GRANTED. INITIALIZING..."})
    return jsonify({"success": False, "msg": "ACCESS DENIED. INVALID CREDENTIALS."})

@app.route('/register', methods=['POST'])
def register():
    data = request.json
    db = get_db()
    
    user = db.execute('SELECT * FROM users WHERE LOWER(username)=LOWER(?)', 
                      (data['username'].strip(),)).fetchone()
    if user: 
        return jsonify({"success": False, "msg": "USERNAME ALREADY IN USE."})
        
    db.execute('INSERT INTO users (username, pin) VALUES (?, ?)', 
               (data['username'].strip(), data['pin'].strip()))
    db.commit()
    return jsonify({"success": True, "msg": "PROFILE CREATED. PLEASE LOGIN."})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('index'))
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()
    accuracy = int((user['correct_answers'] / user['questions_solved'] * 100)) if user['questions_solved'] > 0 else 0
    badges = db.execute('''SELECT b.*, (ub.badge_id IS NOT NULL) as earned 
                           FROM badges b LEFT JOIN user_badges ub ON b.id=ub.badge_id AND ub.user_id=?''', (user['id'],)).fetchall()
    return render_template('dashboard.html', user=user, accuracy=accuracy, badges=badges)

@app.route('/learning')
def learning():
    if 'user_id' not in session: return redirect(url_for('index'))
    db = get_db()
    chapters = db.execute('SELECT * FROM chapters').fetchall()
    return render_template('learning.html', chapters=chapters)

@app.route('/practice/<int:chapter_id>')
def practice(chapter_id):
    if 'user_id' not in session: return redirect(url_for('index'))
    db = get_db()
    chapter = db.execute('SELECT * FROM chapters WHERE id=?', (chapter_id,)).fetchone()
    questions = db.execute('SELECT * FROM questions WHERE chapter_id=?', (chapter_id,)).fetchall()
    questions_list = [dict(q) for q in questions]
    return render_template('practice.html', chapter=chapter, questions=questions_list)

@app.route('/api/answer', methods=['POST'])
def submit_answer():
    if 'user_id' not in session: return jsonify({"error": "Unauthorized"})
    data = request.json
    db = get_db()
    
    q = db.execute('SELECT * FROM questions WHERE id=?', (data['question_id'],)).fetchone()
    user = db.execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()

    is_correct = (data['selected_option'] == q['correct_opt'])
    xp_earned = 15 if is_correct else 5 

    new_xp = user['xp'] + xp_earned
    new_solved = user['questions_solved'] + 1
    new_correct = user['correct_answers'] + (1 if is_correct else 0)

    db.execute('UPDATE users SET xp=?, questions_solved=?, correct_answers=? WHERE id=?', 
               (new_xp, new_solved, new_correct, user['id']))

    new_badges = []
    unearned_badges = db.execute('''SELECT * FROM badges WHERE req_xp <= ? AND id NOT IN 
                                    (SELECT badge_id FROM user_badges WHERE user_id=?)''', (new_xp, user['id'])).fetchall()
    for b in unearned_badges:
        db.execute('INSERT INTO user_badges (user_id, badge_id) VALUES (?,?)', (user['id'], b['id']))
        new_badges.append(b['name'])

    db.commit()

    return jsonify({
        "correct": is_correct,
        "correct_option": q['correct_opt'],
        "xp_earned": xp_earned,
        "new_xp": new_xp,
        "new_badges": new_badges
    })

if __name__ == '__main__':
    if not os.path.exists(DB_FILE):
        init_db()
    else:
        # File exist karne ke baad bhi force update ho jayega bina progress loose kiye
        init_db()
    app.run(host='0.0.0.0', debug=True, port=5000)