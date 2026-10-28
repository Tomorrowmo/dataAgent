"""damos 启动：python run.py（Flask 开发服务器，端口 5005）。"""
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5005, debug=True)
