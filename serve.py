"""
serve.py - ローカルWebサーバー
==============================
ダッシュボードをブラウザで表示するための簡易HTTPサーバー。
CORSの問題を回避するため、fetch() で data/results.json を読み込みます。

使い方:
  python serve.py          # http://localhost:8080 で起動
  python serve.py 3000     # ポート3000で起動
"""

import http.server
import socketserver
import sys
import webbrowser
import os

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080

class CustomHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        # Override translate_path to route requests to correct directories
        # original path translation
        root = os.getcwd()
        
        # Parse query parameters are not an issue for SimpleHTTPRequestHandler usually, 
        # but path might contain them. standard translate_path handles basic adjustments.
        
        if path.startswith("/data/"):
            # Serve data from ./data
            return os.path.join(root, path.lstrip("/"))
        else:
            # Serve everything else from ./web
            # effective root for other requests is ./web
            p = path.lstrip("/")
            if p == "" or p == "index.html":
                p = "index.html"
            return os.path.join(root, "web", p)

Handler = CustomHandler

with socketserver.TCPServer(("", PORT), Handler) as httpd:
    url = f"http://localhost:{PORT}"
    print(f"🌐 CIO Dashboard を起動中...")
    print(f"   URL: {url}")
    print(f"   停止: Ctrl+C")
    webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 サーバーを停止しました")
