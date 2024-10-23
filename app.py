import os
from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from authlib.integrations.flask_client import OAuth
from github import Github
from dotenv import load_dotenv
from flask_caching import Cache
from pymongo import MongoClient

# 載入環境變數
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'supersecretkey')
app.config['CACHE_TYPE'] = 'SimpleCache'  # 設定快取類型
app.config['CACHE_DEFAULT_TIMEOUT'] = 300  # 預設快取過期時間

# 初始化快取
cache = Cache(app)

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

# 連接到MongoDB Atlas
client = MongoClient(os.getenv('MONGO_URI'))
db = client['your_database_name']  # 替換為你的MongoDB數據庫名稱
users_collection = db['users']  # 使用者集合

# 使用者模型 (替換SQLAlchemy的ORM模型)
class User(UserMixin):
    def __init__(self, id, username, github_token=None):
        self.id = id
        self.username = username
        self.github_token = github_token

@login_manager.user_loader
def load_user(user_id):
    user = users_collection.find_one({"_id": int(user_id)})
    if user:
        return User(id=user["_id"], username=user["username"], github_token=user.get("github_token"))
    return None

@app.route('/')
def index():
    return render_template('index.html')

# 處理註冊與登入
@app.route('/auth', methods=['POST'])
def auth():
    action = request.form.get('action')
    username = request.form.get('username')

    if action == 'register':
        if users_collection.find_one({"username": username}):
            flash('使用者名稱已被使用，請選擇其他名稱。', 'error')
            return redirect(url_for('index'))
        
        new_user = {"username": username}
        result = users_collection.insert_one(new_user)
        user_id = result.inserted_id
        login_user(User(id=user_id, username=username))
        flash('註冊成功！', 'success')
        return redirect(url_for('dashboard'))

    elif action == 'login':
        user = users_collection.find_one({"username": username})
        if user:
            login_user(User(id=user["_id"], username=user["username"]))
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
        users_collection.update_one(
            {"_id": current_user.id},
            {"$set": {"github_token": token['access_token']}}
        )
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
        try:
            # 檢查儲存庫是否存在
            if any(repo.name == repo_name for repo in gh.get_user().get_repos()):
                flash('儲存庫名稱已存在，請選擇其他名稱。', 'error')
            else:
                gh.get_user().create_repo(repo_name)
                flash(f'儲存庫 {repo_name} 已成功創建！', 'success')
        except Exception as e:
            flash(f'創建儲存庫失敗：{str(e)}', 'error')

    # 取得當前頁碼
    page = request.args.get('page', 1, type=int)
    per_page = 30  # 每頁顯示的儲存庫數量
    start = (page - 1) * per_page

    # 獲取所有儲存庫
    repos = list(gh.get_user().get_repos())
    total_repos = len(repos)  # 總儲存庫數量
    total_pages = (total_repos + per_page - 1) // per_page  # 總頁數

    # 進行分頁
    repos = repos[start:start + per_page]

    return render_template('dashboard.html', repos=repos, page=page, total_pages=total_pages)

# 搜尋儲存庫
@app.route('/search_repos', methods=['GET'])
@login_required
def search_repos():
    query = request.args.get('query')
    gh = Github(current_user.github_token)

    try:
        # 透過 GitHub API 搜尋用戶的儲存庫
        repos = gh.get_user().get_repos()  # 取得所有儲存庫
        filtered_repos = [repo for repo in repos if query.lower() in repo.name.lower()]

        return render_template('dashboard.html', repos=filtered_repos, page=1, total_pages=1)
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
                commit_message = "初始化 README 檔案來自 Github-hub"  # 提交訊息
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

    return render_template('repo_file.html', repo=repo)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
