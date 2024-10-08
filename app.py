# app.py
import os
from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from authlib.integrations.flask_client import OAuth
from github import Github
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'supersecretkey')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 初始化資料庫
db = SQLAlchemy(app)

# 初始化登入管理
login_manager = LoginManager(app)
login_manager.login_view = 'index'

# 初始化 OAuth
oauth = OAuth(app)
github_oauth = oauth.register(
    name='github',
    client_id=os.getenv('GITHUB_CLIENT_ID'),
    client_secret=os.getenv('GITHUB_CLIENT_SECRET'),
    access_token_url='https://github.com/login/oauth/access_token',
    authorize_url='https://github.com/login/oauth/authorize',
    api_base_url='https://api.github.com/',
    client_kwargs={'scope': 'repo'}
)

# 使用者模型
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), nullable=False, unique=True)
    github_token = db.Column(db.String(200), nullable=True)

# 載入使用者的函數
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/')
def index():
    return render_template('index.html')

# 處理登入與註冊
@app.route('/auth', methods=['POST'])
def auth():
    action = request.form.get('action')
    username = request.form.get('username')
    password = request.form.get('password')  # 暫未實作密碼功能

    if action == 'register':
        if User.query.filter_by(username=username).first():
            flash('使用者名稱已被使用，請選擇其他名稱。', 'error')
            return redirect(url_for('index'))
        user = User(username=username)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash('註冊成功！', 'success')
        return redirect(url_for('dashboard'))

    elif action == 'login':
        user = User.query.filter_by(username=username).first()
        if user:
            login_user(user)
            flash('登入成功！', 'success')
            return redirect(url_for('dashboard'))
        flash('無效的使用者名稱或密碼。', 'error')
        return redirect(url_for('index'))

# 登出
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('已登出。', 'success')
    return redirect(url_for('index'))

# GitHub OAuth 認證
@app.route('/github/login')
@login_required
def github_login():
    redirect_uri = url_for('github_callback', _external=True)
    return github_oauth.authorize_redirect(redirect_uri)

@app.route('/github/callback')
@login_required
def github_callback():
    try:
        token = github_oauth.authorize_access_token()
        current_user.github_token = token['access_token']
        db.session.commit()
        flash('GitHub 連接成功！', 'success')
        return redirect(url_for('dashboard'))
    except Exception as e:
        flash(f'GitHub 認證失敗：{str(e)}', 'error')
        return redirect(url_for('index'))

# 儲存庫顯示與管理
@app.route('/dashboard')
@login_required
def dashboard():
    if not current_user.github_token:
        flash('請先連接 GitHub 帳號。', 'warning')
        return redirect(url_for('github_login'))
    
    try:
        gh = Github(current_user.github_token)
        repos = gh.get_user().get_repos()
        return render_template('dashboard.html', repos=repos)
    except Exception as e:
        flash(f'無法取得儲存庫：{str(e)}', 'error')
        return redirect(url_for('index'))

# 顯示儲存庫內容
@app.route('/repo/<owner>/<name>')
@login_required
def repo(owner, name):
    try:
        gh = Github(current_user.github_token)
        repo = gh.get_repo(f"{owner}/{name}")
        contents = repo.get_contents("")
        return render_template('repo.html', repo=repo, contents=contents)
    except Exception as e:
        flash(f'無法取得儲存庫內容：{str(e)}', 'error')
        return redirect(url_for('dashboard'))

# 新增、編輯、刪除檔案
@app.route('/repo/<owner>/<name>/file', methods=['GET', 'POST'])
@login_required
def repo_file(owner, name):
    gh = Github(current_user.github_token)
    repo = gh.get_repo(f"{owner}/{name}")
    
    if request.method == 'POST':
        file_path = request.form.get('file_path')
        file_content = request.form.get('file_content')
        commit_message = request.form.get('commit_message')
        action = request.form.get('action')  # 'create' 或 'edit'
        
        try:
            if action == 'edit':
                contents = repo.get_contents(file_path)
                repo.update_file(contents.path, commit_message, file_content, contents.sha)
                flash('檔案編輯成功。', 'success')
            elif action == 'create':
                repo.create_file(file_path, commit_message, file_content)
                flash('檔案新增成功。', 'success')
            return redirect(url_for('repo', owner=owner, name=name))
        except Exception as e:
            flash(f'操作失敗：{str(e)}', 'error')
            return redirect(url_for('repo', owner=owner, name=name))
    
    return render_template('file_form.html', repo=repo, owner=owner, name=name)

# 刪除檔案
@app.route('/repo/<owner>/<name>/delete', methods=['POST'])
@login_required
def delete_file(owner, name):
    file_path = request.form.get('file_path')
    commit_message = request.form.get('commit_message', '刪除檔案 via Flask app')
    
    gh = Github(current_user.github_token)
    repo = gh.get_repo(f"{owner}/{name}")
    
    try:
        contents = repo.get_contents(file_path)
        repo.delete_file(contents.path, commit_message, contents.sha)
        flash('檔案刪除成功。', 'success')
    except Exception as e:
        flash(f'刪除失敗：{str(e)}', 'error')
    
    return redirect(url_for('repo', owner=owner, name=name))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True,port=10000,host='0.0.0.0')
