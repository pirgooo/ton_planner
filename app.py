from flask import Flask, render_template, request, redirect, url_for, session, make_response, jsonify, send_from_directory
from flask_babel import Babel
import sqlite3
import os
import requests
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

pdfmetrics.registerFont(TTFont('DejaVu', 'C:/Windows/Fonts/DejaVuSans.ttf'))
pdfmetrics.registerFont(TTFont('DejaVuBold', 'C:/Windows/Fonts/DejaVuSans-Bold.ttf'))

app = Flask(__name__)
app.config['DATABASE'] = 'tasks.db'
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-change-in-production')
app.config['BABEL_DEFAULT_LOCALE'] = 'ru'
app.config['BABEL_TRANSLATION_DIRECTORIES'] = 'translations'

babel = Babel(app)

LANGUAGES = {
    'ru': 'Русский',
    'en': 'English'
}

def get_locale():
    if 'lang' in session:
        return session['lang']
    wallet = session.get('wallet')
    if wallet:
        db = get_db()
        try:
            cursor = db.execute('SELECT lang FROM users WHERE wallet_address = ?', (wallet,))
            user = cursor.fetchone()
            if user and user['lang']:
                return user['lang']
        finally:
            close_db(db)
    return 'ru'

babel.init_app(app, locale_selector=get_locale)

@app.route('/setlang/<lang>')
def set_language(lang):
    if lang in LANGUAGES:
        session['lang'] = lang
        wallet = session.get('wallet')
        if wallet:
            db = get_db()
            try:
                db.execute('UPDATE users SET lang = ? WHERE wallet_address = ?', (lang, wallet))
                db.commit()
            finally:
                close_db(db)
    return redirect(request.referrer or '/')

@app.context_processor
def inject_languages():
    return dict(LANGUAGES=LANGUAGES)

def get_db():
    db = sqlite3.connect(app.config['DATABASE'])
    db.row_factory = sqlite3.Row
    return db

def close_db(db):
    if db:
        db.close()

def init_db():
    db = get_db()
    try:
        db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address TEXT UNIQUE NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        db.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                priority TEXT DEFAULT 'medium',
                status TEXT DEFAULT 'pending',
                due_date TEXT,
                due_time TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        
        existing_columns = db.execute("PRAGMA table_info(tasks)").fetchall()
        column_names = [col[1] for col in existing_columns]
        
        if 'user_id' not in column_names:
            db.execute('ALTER TABLE tasks ADD COLUMN user_id INTEGER DEFAULT 1')
        
        if 'due_time' not in column_names:
            db.execute('ALTER TABLE tasks ADD COLUMN due_time TEXT')
        
        user_columns = db.execute("PRAGMA table_info(users)").fetchall()
        user_column_names = [col[1] for col in user_columns]
        
        if 'lang' not in user_column_names:
            db.execute('ALTER TABLE users ADD COLUMN lang TEXT DEFAULT "ru"')
            
    finally:
        close_db(db)

def get_balance(address):
    try:
        url = f"https://toncenter.com/api/v2/getAddressBalance"
        data = {"address": address}
        response = requests.post(url, json=data, timeout=5)
        if response.status_code == 200:
            balance = int(response.json().get('result', 0))
            return balance / 1e9
    except:
        pass
    return None

def get_current_user():
    wallet = session.get('wallet')
    if not wallet:
        return None
    db = get_db()
    try:
        cursor = db.execute('SELECT * FROM users WHERE wallet_address = ?', (wallet,))
        user = cursor.fetchone()
        if user:
            user_dict = dict(user)
            user_dict['balance'] = get_balance(wallet)
            return user_dict
        return None
    finally:
        close_db(db)

def create_or_get_user(wallet_address):
    db = get_db()
    try:
        cursor = db.execute('SELECT * FROM users WHERE wallet_address = ?', (wallet_address,))
        user = cursor.fetchone()
        if not user:
            db.execute('INSERT INTO users (wallet_address) VALUES (?)', (wallet_address,))
            db.commit()
            cursor = db.execute('SELECT * FROM users WHERE wallet_address = ?', (wallet_address,))
            user = cursor.fetchone()
        return user
    finally:
        close_db(db)

@app.route('/')
def index():
    import datetime
    current_user = get_current_user()
    tasks = []
    status_counts = {'pending': 0, 'in_progress': 0, 'completed': 0}
    calendar_days = []
    
    month_offset = request.args.get('month', 0, type=int)
    today = datetime.date.today()
    first_day = today.replace(day=1)
    if month_offset:
        from datetime import timedelta
        import calendar
        new_month = first_day.month + month_offset
        new_year = first_day.year + (new_month - 1) // 12
        new_month = ((new_month - 1) % 12) + 1
        last_day_of_month = calendar.monthrange(new_year, new_month)[1]
        first_day = first_day.replace(year=new_year, month=new_month, day=1)
    
    month_name = first_day.strftime('%B %Y')
    
    start_weekday = first_day.weekday()
    days_in_month = (first_day.replace(month=first_day.month % 12 + 1, year=first_day.year if first_day.month < 12 else first_day.year + 1) - datetime.timedelta(days=1)).day
    
    prev_month = (first_day - datetime.timedelta(days=1)).replace(day=1)
    prev_days = []
    for i in range(start_weekday):
        day_num = (prev_month - datetime.timedelta(days=start_weekday - i - 1)).day
        prev_days.append({'day': day_num, 'class': 'other-month', 'tasks': []})
    
    tasks_by_date = {}
    if current_user:
        db = get_db()
        try:
            cursor = db.execute('''SELECT * FROM tasks WHERE user_id = ? AND due_date IS NOT NULL AND due_date != '' ORDER BY 
                CASE status 
                    WHEN 'pending' THEN 1 
                    WHEN 'in_progress' THEN 2 
                    ELSE 3 
                END,
                CASE priority 
                    WHEN 'high' THEN 1 
                    WHEN 'medium' THEN 2 
                    ELSE 3 
                END,
                due_date ASC''', (current_user['id'],))
            tasks = cursor.fetchall()
            
            for task in tasks:
                status = task['status']
                if status in status_counts:
                    status_counts[status] += 1
                if task['due_date']:
                    if task['due_date'] not in tasks_by_date:
                        tasks_by_date[task['due_date']] = []
                    tasks_by_date[task['due_date']].append(task)
        finally:
            close_db(db)
    
    calendar_days = prev_days
    for day in range(1, days_in_month + 1):
        date_str = first_day.replace(day=day).strftime('%Y-%m-%d')
        day_tasks = tasks_by_date.get(date_str, [])
        is_today = (first_day.replace(day=day) == today)
        calendar_days.append({
            'day': day,
            'class': 'today' if is_today else ('has-tasks' if day_tasks else ''),
            'tasks': day_tasks
        })
    
    return render_template('index.html', 
                           tasks=tasks,
                           status_counts=status_counts,
                           current_user=current_user,
                           calendar_days=calendar_days,
                           calendar_month=month_name)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        wallet = request.form.get('wallet', '').strip()
        if wallet and len(wallet) >= 32:
            create_or_get_user(wallet)
            session['wallet'] = wallet
            db = get_db()
            try:
                cursor = db.execute('SELECT lang FROM users WHERE wallet_address = ?', (wallet,))
                user = cursor.fetchone()
                if user and user['lang']:
                    session['lang'] = user['lang']
            finally:
                close_db(db)
            return redirect(url_for('index'))
        return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('wallet', None)
    return redirect(url_for('index'))

@app.route('/add', methods=['GET', 'POST'])
def add_task():
    current_user = get_current_user()
    if not current_user:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        priority = request.form.get('priority', 'medium')
        due_date = request.form.get('due_date', '')
        due_time = request.form.get('due_time', '')
        
        if not title:
            return redirect(url_for('add_task'))
        
        db = get_db()
        try:
            db.execute(
                'INSERT INTO tasks (user_id, title, description, priority, due_date, due_time) VALUES (?, ?, ?, ?, ?, ?)',
                (current_user['id'], title, description, priority, due_date, due_time)
            )
            db.commit()
        finally:
            close_db(db)
        
        return redirect(url_for('index'))
    
    return render_template('add_task.html')

@app.route('/edit/<int:task_id>', methods=['GET', 'POST'])
def edit_task(task_id):
    current_user = get_current_user()
    if not current_user:
        return redirect(url_for('login'))
    
    db = get_db()
    try:
        if request.method == 'POST':
            title = request.form.get('title', '').strip()
            description = request.form.get('description', '').strip()
            priority = request.form.get('priority', 'medium')
            status = request.form.get('status', 'pending')
            due_date = request.form.get('due_date', '')
            due_time = request.form.get('due_time', '')
            
            db.execute('''
                UPDATE tasks 
                SET title = ?, description = ?, priority = ?, status = ?, due_date = ?, due_time = ?
                WHERE id = ? AND user_id = ?
            ''', (title, description, priority, status, due_date, due_time, task_id, current_user['id']))
            db.commit()
            close_db(db)
            return redirect(url_for('index'))
        
        cursor = db.execute('SELECT * FROM tasks WHERE id = ? AND user_id = ?', 
                           (task_id, current_user['id']))
        task = cursor.fetchone()
    finally:
        close_db(db)
    
    if task is None:
        return redirect(url_for('index'))
    
    return render_template('edit_task.html', task=task)

@app.route('/delete/<int:task_id>', methods=['POST'])
def delete_task(task_id):
    current_user = get_current_user()
    if not current_user:
        return redirect(url_for('login'))
    
    db = get_db()
    try:
        db.execute('DELETE FROM tasks WHERE id = ? AND user_id = ?', 
                  (task_id, current_user['id']))
        db.commit()
    finally:
        close_db(db)
    return redirect(url_for('index'))

@app.route('/complete/<int:task_id>', methods=['POST'])
def complete_task(task_id):
    current_user = get_current_user()
    if not current_user:
        return redirect(url_for('login'))
    
    db = get_db()
    try:
        db.execute('UPDATE tasks SET status = ? WHERE id = ? AND user_id = ?',
                  ('completed', task_id, current_user['id']))
        db.commit()
    finally:
        close_db(db)
    return redirect(url_for('index'))

@app.route('/revert/<int:task_id>', methods=['POST'])
def revert_task(task_id):
    current_user = get_current_user()
    if not current_user:
        return redirect(url_for('login'))
    
    db = get_db()
    try:
        db.execute('UPDATE tasks SET status = ? WHERE id = ? AND user_id = ?',
                  ('pending', task_id, current_user['id']))
        db.commit()
    finally:
        close_db(db)
    return redirect(url_for('index'))

@app.route('/test_index')
def test_index():
    return render_template('test_index.html')

@app.route('/about')
def about():
    current_user = get_current_user()
    return render_template('about.html', current_user=current_user)

@app.route('/manage')
def manage():
    current_user = get_current_user()
    if not current_user:
        return redirect(url_for('login'))
    return render_template('manage.html', current_user=current_user)

@app.route('/storage')
def storage():
    current_user = get_current_user()
    if not current_user:
        return redirect(url_for('login'))
    return render_template('storage.html', current_user=current_user)

@app.route('/export-pdf')
def export_pdf():
    current_user = get_current_user()
    if not current_user:
        return redirect(url_for('login'))
    
    db = get_db()
    try:
        cursor = db.execute('SELECT * FROM tasks WHERE user_id = ? ORDER BY CASE status WHEN "completed" THEN 1 ELSE 0 END, created_at DESC', (current_user['id'],))
        tasks = cursor.fetchall()
    finally:
        close_db(db)
    
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=15*mm, leftMargin=15*mm, topMargin=15*mm, bottomMargin=15*mm)
    styles = getSampleStyleSheet()
    
    normal_style = ParagraphStyle('CustomNormal', parent=styles['Normal'], fontName='DejaVu', fontSize=10)
    title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], fontName='DejaVuBold', fontSize=18, textColor=colors.HexColor('#667eea'))
    header_style = ParagraphStyle('Header', parent=styles['Normal'], fontName='DejaVuBold', fontSize=9, textColor=colors.white, alignment=TA_LEFT)
    
    elements = []
    
    elements.append(Paragraph('TON Planner - Мои задачи', title_style))
    elements.append(Spacer(1, 3*mm))
    
    wallet_short = current_user['wallet_address'][:16] + '...' + current_user['wallet_address'][-8:]
    elements.append(Paragraph(f"Кошелек: {wallet_short}", normal_style))
    elements.append(Paragraph(f"Всего задач: {len(tasks)}", normal_style))
    elements.append(Spacer(1, 8*mm))
    
    if tasks:
        table_data = [[Paragraph(h, header_style) for h in ['#', 'Задача', 'Приоритет', 'Статус', 'Срок']]]
        for i, task in enumerate(tasks, 1):
            priority = {'high': 'Высокий', 'medium': 'Средний', 'low': 'Низкий'}.get(task['priority'], '')
            status = {'pending': 'Ожидает', 'in_progress': 'В процессе', 'completed': 'Выполнено'}.get(task['status'], '')
            due = task['due_date'] if task['due_date'] else '-'
            if task['due_time'] and task['due_date']:
                due = f"{task['due_date']} {task['due_time']}"
            elif task['due_time']:
                due = task['due_time']
            title = task['title'][:40] + '...' if len(task['title']) > 40 else task['title']
            cell_style = ParagraphStyle('Cell', fontName='DejaVu', fontSize=8, leading=10)
            table_data.append([str(i), Paragraph(title, cell_style), Paragraph(priority, cell_style), Paragraph(status, cell_style), Paragraph(due, cell_style)])
        
        table = Table(table_data, colWidths=[12*mm, 70*mm, 26*mm, 26*mm, 30*mm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#667eea')),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (1, 1), (1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e5e7eb')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
        ]))
        elements.append(table)
    else:
        elements.append(Paragraph("Нет задач", normal_style))
    
    doc.build(elements)
    
    buffer.seek(0)
    response = make_response(buffer.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'attachment; filename=ton_planner_tasks.pdf'
    return response

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)
