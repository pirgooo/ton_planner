from flask import Flask, render_template, request, redirect, url_for
import sqlite3
import os

app = Flask(__name__)
app.config['DATABASE'] = 'tasks.db'

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
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                priority TEXT DEFAULT 'medium',
                status TEXT DEFAULT 'pending',
                due_date TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        db.commit()
    finally:
        close_db(db)

@app.route('/')
def index():
    db = get_db()
    try:
        cursor = db.execute('''SELECT * FROM tasks ORDER BY 
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
            due_date ASC''')
        tasks = cursor.fetchall()
    finally:
        close_db(db)
    
    status_counts = {'pending': 0, 'in_progress': 0, 'completed': 0}
    for task in tasks:
        status = task['status']
        if status in status_counts:
            status_counts[status] += 1
    
    return render_template('index.html', tasks=tasks, status_counts=status_counts)

@app.route('/add', methods=['GET', 'POST'])
def add_task():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        priority = request.form.get('priority', 'medium')
        due_date = request.form.get('due_date', '')
        
        if not title:
            return redirect(url_for('add_task'))
        
        db = get_db()
        try:
            db.execute(
                'INSERT INTO tasks (title, description, priority, due_date) VALUES (?, ?, ?, ?)',
                (title, description, priority, due_date)
            )
            db.commit()
        finally:
            close_db(db)
        
        return redirect(url_for('index'))
    
    return render_template('add_task.html')

@app.route('/edit/<int:task_id>', methods=['GET', 'POST'])
def edit_task(task_id):
    db = get_db()
    try:
        if request.method == 'POST':
            title = request.form.get('title', '').strip()
            description = request.form.get('description', '').strip()
            priority = request.form.get('priority', 'medium')
            status = request.form.get('status', 'pending')
            due_date = request.form.get('due_date', '')
            
            db.execute('''
                UPDATE tasks 
                SET title = ?, description = ?, priority = ?, status = ?, due_date = ?
                WHERE id = ?
            ''', (title, description, priority, status, due_date, task_id))
            db.commit()
            close_db(db)
            return redirect(url_for('index'))
        
        cursor = db.execute('SELECT * FROM tasks WHERE id = ?', (task_id,))
        task = cursor.fetchone()
    finally:
        close_db(db)
    
    if task is None:
        return redirect(url_for('index'))
    
    return render_template('edit_task.html', task=task)

@app.route('/delete/<int:task_id>', methods=['POST'])
def delete_task(task_id):
    db = get_db()
    try:
        db.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
        db.commit()
    finally:
        close_db(db)
    return redirect(url_for('index'))

@app.route('/complete/<int:task_id>', methods=['POST'])
def complete_task(task_id):
    db = get_db()
    try:
        db.execute('UPDATE tasks SET status = ? WHERE id = ?', ('completed', task_id))
        db.commit()
    finally:
        close_db(db)
    return redirect(url_for('index'))

@app.route('/revert/<int:task_id>', methods=['POST'])
def revert_task(task_id):
    db = get_db()
    try:
        db.execute('UPDATE tasks SET status = ? WHERE id = ?', ('pending', task_id))
        db.commit()
    finally:
        close_db(db)
    return redirect(url_for('index'))




@app.route('/test_index')
def test_index():
    return render_template('test_index.html')

@app.route('/about')
def about():
    return render_template('about.html')


if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)
