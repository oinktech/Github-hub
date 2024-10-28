import os
import logging
from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from authlib.integrations.flask_client import OAuth
from github import Github
from dotenv import load_dotenv
from flask_caching import Cache
from pymongo import MongoClient
from bson.objectid import ObjectId

# 載入環境變數
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'supersecretkey')
app.config['MONGO_URI'] = os.getenv('MONGO_URI')  # MongoDB 連接字串
app.config['CACHE_TYPE'] = 'SimpleCache'  # 設定快取類型
app.config['CACHE_DEFAULT_TIMEOUT'] = 300  # 預設快取過期時間

# 初始化資料庫
mongo_uri = os.getenv('MONGO_URI')
client = MongoClient(mongo_uri)
db = client['0001']
users_collection = db.users  # 使用 users 集合
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
class User(UserMixin):
    def __init__(self, id, username, github_token=None):
        self.id = id
        self.username = username
        self.github_token = github_token

# 載入使用者的函數
@login_manager.user_loader
def load_user(user_id):
    user = users_collection.find_one({"_id": ObjectId(user_id)})
    if user:
        return User(id=str(user["_id"]), username=user["username"], github_token=user.get("github_token"))
    return None

@app.route('/')
def index():
    return render_template('index.html')

# 處理登入與註冊
@app.route('/auth', methods=['POST'])
def auth():
    action = request.form.get('action')
    username = request.form.get('username')

    if action == 'register':
        if users_collection.find_one({"username": username}):
            flash('使用者名稱已被使用，請選擇其他名稱。', 'error')
            return redirect(url_for('index'))
        user = {"username": username}
        user_id = users_collection.insert_one(user).inserted_id
        login_user(User(id=str(user_id), username=username))
        flash('註冊成功！', 'success')
        return redirect(url_for('dashboard'))

    elif action == 'login':
        user = users_collection.find_one({"username": username})
        if user:
            login_user(User(id=str(user["_id"]), username=user["username"]))
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
        users_collection.update_one({"_id": ObjectId(current_user.id)}, {"$set": {"github_token": token['access_token']}})
        flash('GitHub 連接成功！', 'success')
        return redirect(url_for('dashboard'))
    except Exception as e:
        flash(f'GitHub 認證失敗：{str(e)}', 'error')
        return redirect(url_for('index'))

@app.route('/json/streams')
def streams():
    return jsonify(app.send_static_file('json/streams.json'))

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
            if any(repo.name == repo_name for repo in gh.get_user().get_repos()):
                flash('儲存庫名稱已存在，請選擇其他名稱。', 'error')
            else:
                gh.get_user().create_repo(repo_name)
                flash(f'儲存庫 {repo_name} 已成功創建！', 'success')
        except Exception as e:
            flash(f'創建儲存庫失敗：{str(e)}', 'error')

    page = request.args.get('page', 1, type=int)
    per_page = 30
    start = (page - 1) * per_page

    repos = list(gh.get_user().get_repos())
    total_repos = len(repos)
    total_pages = (total_repos + per_page - 1) // per_page

    repos = repos[start:start + per_page]

    return render_template('dashboard.html', repos=repos, page=page, total_pages=total_pages)

@app.route('/search_repos', methods=['GET'])
@login_required
def search_repos():
    query = request.args.get('query')
    gh = Github(current_user.github_token)

    try:
        repos = gh.get_user().get_repos()
        filtered_repos = [repo for repo in repos if query.lower() in repo.name.lower()]

        return render_template('dashboard.html', repos=filtered_repos, page=1, total_pages=1)
    except Exception as e:
        flash(f'搜尋失敗：{str(e)}', 'error')
        return redirect(url_for('dashboard'))

@app.route('/repo/<owner>/<name>', methods=['GET'])
@login_required
def repo(owner, name):
    gh = Github(current_user.github_token)
    file_path = request.args.get('file_path', '')  # 獲取當前檔案路徑
    if file_path == '..':
        # 處理返回上層資料夾的邏輯
        if '/' in file_path:
            file_path = '/'.join(file_path.split('/')[:-1])  # 去掉最後一部分
        else:
            file_path = ''
    try:
        repo = gh.get_repo(f"{owner}/{name}")
        contents = repo.get_contents(file_path) if file_path else repo.get_contents("")  # 根據路徑獲取內容

        return render_template('repo.html', repo=repo, contents=contents)
    except Exception as e:
        if "This repository is empty." in str(e):
            try:
                file_path = "README.md"
                commit_message = "初始化 README 檔案來自 GitHub-hub"
                repo.create_file(file_path, commit_message, "", branch="main")

                flash(f'儲存庫 "{repo.name}" 為空，已創建空白檔案 {file_path}。', 'success')
                contents = repo.get_contents("")
                return render_template('repo.html', repo=repo, contents=contents)
            except Exception as create_error:
                flash(f'創建檔案失敗：{str(create_error)}', 'error')
        else:
            flash(f'無法取得儲存庫內容：{str(e)}', 'error')

        return redirect(url_for('dashboard'))

@app.route('/repo/<owner>/<name>/file', methods=['GET', 'POST'])
@login_required
def repo_file(owner, name):
    gh = Github(current_user.github_token)
    repo = gh.get_repo(f"{owner}/{name}")

    if request.method == 'POST':
        file_path = request.form.get('file_path')
        file_content = request.form.get('file_content')
        commit_message = request.form.get('commit_message')
        action = request.form.get('action')

        try:
            if action == 'edit':
                contents = repo.get_contents(file_path)
                repo.update_file(contents.path, commit_message, file_content, contents.sha)
                flash(f'檔案 "{file_path}" 已更新！', 'success')
            else:
                repo.create_file(file_path, commit_message, file_content)
                flash(f'檔案 "{file_path}" 已創建！', 'success')

            return redirect(url_for('repo', owner=owner, name=name))
        except Exception as e:
            flash(f'操作失敗：{str(e)}', 'error')

    # 獲取檔案內容以便顯示
    file_path = request.args.get('file_path')
    try:
        contents = repo.get_contents(file_path)
        file_content = contents.decoded_content.decode('utf-8')  # 取得檔案內容
        return render_template('file_form.html', repo=repo, file_path=file_path, file_content=file_content)
    except Exception as e:
        flash(f'無法取得檔案內容：{str(e)}', 'error')
        return redirect(url_for('repo', owner=owner, name=name))

@app.route('/repo/<owner>/<name>/delete_file', methods=['POST'])
@login_required
def delete_file(owner, name):
    gh = Github(current_user.github_token)
    repo = gh.get_repo(f"{owner}/{name}")
    file_path = request.form.get('file_path')

    try:
        contents = repo.get_contents(file_path)
        repo.delete_file(contents.path, f"刪除檔案 {file_path}", contents.sha)
        flash(f'檔案 "{file_path}" 已刪除。', 'success')
    except Exception as e:
        flash(f'刪除檔案失敗：{str(e)}', 'error')

    return redirect(url_for('repo', owner=owner, name=name))

# 錯誤處理
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    app.run(host='0.0.0.0', port=10000, debug=True)
