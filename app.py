import os
from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from authlib.integrations.flask_client import OAuth
from github import Github
from dotenv import load_dotenv
from flask_caching import Cache  # 引入快取模組

# 載入環境變數
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'supersecretkey')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['CACHE_TYPE'] = 'SimpleCache'  # 設定快取類型
app.config['CACHE_DEFAULT_TIMEOUT'] = 300  # 預設快取過期時間

# 初始化資料庫
db = SQLAlchemy(app)
cache = Cache(app)  # 初始化快取

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
@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    if not current_user.github_token:
        flash('請先連接 GitHub 帳號。', 'warning')
        return redirect(url_for('github_login'))
    
    gh = Github(current_user.github_token)

    if request.method == 'POST':
        repo_name = request.form.get('repo_name')
        
        # 檢查儲存庫名稱是否已存在
        existing_repo = gh.get_user().get_repos()
        if any(repo.name == repo_name for repo in existing_repo):
            flash('儲存庫名稱已存在，請選擇其他名稱。', 'error')
            return redirect(url_for('dashboard'))

        # 呼叫 GitHub API 來創建儲存庫
        try:
            gh.get_user().create_repo(repo_name)
            flash(f'儲存庫 "{repo_name}" 已成功創建！', 'success')
        except Exception as e:
            flash(f'創建儲存庫失敗：{str(e)}', 'error')

    # 儲存庫快取
    @cache.cached(timeout=300, query_string=True)
    def get_repos():
        return gh.get_user().get_repos()

    try:
        repos = get_repos()
        return render_template('dashboard.html', repos=repos)
    except Exception as e:
        flash(f'無法取得儲存庫：{str(e)}', 'error')
        return redirect(url_for('index'))

# 搜尋儲存庫
@app.route('/search_repos', methods=['GET'])
@login_required
def search_repos():
    query = request.args.get('query')
    gh = Github(current_user.github_token)
    
    try:
        repos = gh.search_repositories(query)
        return render_template('dashboard.html', repos=repos)
    except Exception as e:
        flash(f'搜尋失敗：{str(e)}', 'error')
        return redirect(url_for('dashboard'))

# 顯示儲存庫內容
@app.route('/repo/<owner>/<name>')
@login_required
def repo(owner, name):
    gh = Github(current_user.github_token)
    try:
        repo = gh.get_repo(f"{owner}/{name}")
        contents = repo.get_contents("")  # 嘗試獲取儲存庫內容
        return render_template('repo.html', repo=repo, contents=contents)
    except Exception as e:
        # 檢查錯誤訊息，特別是空儲存庫的情況
        if "This repository is empty." in str(e):
            # 嘗試創建一個空白檔案
            try:
                file_path = "README.md"  # 空白檔案名稱
                commit_message = "初始化 README 檔案 來自Github-hub"  # 提交訊息
                repo.create_file(file_path, commit_message, "", branch="main")  # 創建空檔案
                
                flash(f'儲存庫 "{repo.name}" 為空，已創建空白檔案 {file_path}。', 'success')
                
                # 重新獲取檔案內容
                contents = repo.get_contents("")  
                return render_template('repo.html', repo=repo, contents=contents)
            except Exception as create_error:
                flash(f'創建檔案失敗：{str(create_error)}', 'error')
        else:
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
    
    # 讀取檔案內容以顯示在表單中
    file_path = request.args.get('file_path')
    if file_path:
        try:
            contents = repo.get_contents(file_path)
            file_content = contents.decoded_content.decode("utf-8")
        except Exception as e:
            file_content = ''
            flash(f'無法讀取檔案內容：{str(e)}', 'error')
    else:
        file_content = ''
    
    return render_template('file_form.html', repo=repo, owner=owner, name=name, file_content=file_content)

# 启动 Flask 应用
if __name__ == '__main__':
    db.create_all()
    app.run(host='0.0.0.0', port=10000)
