"""damos —— OIDC 接入演示日记本（完全自包含 Flask 客户端）。

演示：登录 / 登出 / 进入自动跳转 / 获取用户信息；业务为按用户隔离的日记本。
OIDC 逻辑参照 mirror_cortex 的 app/oidc_client.py、app/auth_utils.py。
"""
import os
from functools import wraps
from urllib.parse import quote, urlsplit, urlunsplit

from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
from flask import (Flask, abort, current_app, g, redirect, render_template,
                   request, session, url_for)

import db

load_dotenv()

oauth = OAuth()


class Identity:
    """轻量身份：字段取自认证中心 id_token，不查任何用户表。"""

    def __init__(self, id, email="", name="", is_admin=False):
        self.id = id
        self.email = email
        self.name = name
        self.is_admin = is_admin


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return Identity(uid, session.get("email", ""), session.get("name", ""),
                    bool(session.get("is_admin", False)))


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = current_user()
        if user is None:
            # 进入受保护页未登录 → 自动跳转发起 OIDC 登录
            return redirect(url_for("login"))
        g.user = user
        return f(*args, **kwargs)
    return wrapper


def _logout_endpoint():
    """认证中心登出端点：从 discovery 取 end_session_endpoint，不能用 ISSUER 拼。"""
    try:
        md = oauth.idp.load_server_metadata()
        end = md.get("end_session_endpoint")
        if end:
            return end
        a = urlsplit(md.get("authorization_endpoint", ""))
        if a.netloc:
            return urlunsplit((a.scheme, a.netloc, "/logout", "", ""))
    except Exception:
        pass
    return current_app.config["OIDC_ISSUER"].rstrip("/") + "/logout"


def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("APP_SECRET_KEY", "dev-secret-change-me")
    app.config["OIDC_ISSUER"] = os.environ["OIDC_ISSUER"]
    app.config["OIDC_CLIENT_ID"] = os.environ["OIDC_CLIENT_ID"]
    app.config["OIDC_CLIENT_SECRET"] = os.environ["OIDC_CLIENT_SECRET"]
    app.config["OIDC_REDIRECT_URI"] = os.environ["OIDC_REDIRECT_URI"]

    oauth.init_app(app)
    oauth.register(
        name="idp",
        client_id=app.config["OIDC_CLIENT_ID"],
        client_secret=app.config["OIDC_CLIENT_SECRET"],
        server_metadata_url=app.config["OIDC_ISSUER"].rstrip("/")
        + "/.well-known/openid-configuration",
        client_kwargs={"scope": "openid profile email", "code_challenge_method": "S256"},
    )

    db.init_db()
    _register_routes(app)
    return app


def _register_routes(app):
    # ---- OIDC 登录 / 回调 / 登出 ----
    @app.get("/auth/login")
    def login():
        return oauth.idp.authorize_redirect(app.config["OIDC_REDIRECT_URI"])

    @app.get("/auth/callback")
    def callback():
        token = oauth.idp.authorize_access_token()  # 换 token + 验签 + 验 nonce
        claims = token.get("userinfo") or oauth.idp.userinfo(token=token)
        session["user_id"] = claims["sub"]
        session["email"] = claims.get("email", "")
        session["name"] = claims.get("name", "")
        session["is_admin"] = bool(claims.get("is_admin", False))
        return redirect(url_for("index"))

    @app.get("/logout")
    def logout():
        session.clear()
        url = _logout_endpoint()
        ru = urlsplit(app.config["OIDC_REDIRECT_URI"])
        if ru.netloc:
            home = urlunsplit((ru.scheme, ru.netloc, "/", "", ""))
            url += ("&" if "?" in url else "?") + "post_logout_redirect_uri=" + quote(home, safe="")
        return redirect(url)

    # ---- 日记 CRUD（全部 login_required + 按 owner_sub 隔离）----
    @app.get("/")
    @login_required
    def index():
        entries = db.list_entries(g.user.id)
        return render_template("index.html", user=g.user, entries=entries)

    @app.route("/entry/new", methods=["GET", "POST"])
    @login_required
    def entry_new():
        if request.method == "POST":
            db.create_entry(g.user.id, request.form["title"].strip(),
                            request.form["content"].strip())
            return redirect(url_for("index"))
        return render_template("edit.html", user=g.user, entry=None)

    @app.get("/entry/<int:entry_id>")
    @login_required
    def entry_view(entry_id):
        entry = db.get_entry(entry_id, g.user.id)
        if entry is None:
            abort(404)
        return render_template("view.html", user=g.user, entry=entry)

    @app.route("/entry/<int:entry_id>/edit", methods=["GET", "POST"])
    @login_required
    def entry_edit(entry_id):
        entry = db.get_entry(entry_id, g.user.id)
        if entry is None:
            abort(404)
        if request.method == "POST":
            db.update_entry(entry_id, g.user.id, request.form["title"].strip(),
                            request.form["content"].strip())
            return redirect(url_for("entry_view", entry_id=entry_id))
        return render_template("edit.html", user=g.user, entry=entry)

    @app.post("/entry/<int:entry_id>/delete")
    @login_required
    def entry_delete(entry_id):
        if db.get_entry(entry_id, g.user.id) is None:
            abort(404)
        db.delete_entry(entry_id, g.user.id)
        return redirect(url_for("index"))
