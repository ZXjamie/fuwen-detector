#!/usr/bin/env python3
"""
赋文检测器 HTTP API 服务
端口 8010
"""

import sys
import os
import json
from http.server import HTTPServer, BaseHTTPRequestHandler

# 确保能导入同目录模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fuwen_detector import fetch_all_fuwen, detect_fuwen

PORT = 8010

# 缓存赋文节点列表
_fuwen_cache = None


def get_fuwen_list():
    """获取赋文列表（带缓存）"""
    global _fuwen_cache
    if _fuwen_cache is None:
        print("📦 从Neo4j加载赋文数据...")
        _fuwen_cache = fetch_all_fuwen()
        print(f"✅ 加载了 {len(_fuwen_cache)} 个赋文节点")
    return _fuwen_cache


class FuwenDetectorHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/fuwen/detect':
            self.handle_detect()
        else:
            self.send_error(404)

    def do_GET(self):
        if self.path == '/health':
            self.send_json({'status': 'ok', 'fuwen_count': len(get_fuwen_list())})
        elif self.path == '/reload':
            global _fuwen_cache
            _fuwen_cache = None
            count = len(get_fuwen_list())
            self.send_json({'status': 'reloaded', 'count': count})
        else:
            self.send_error(404)

    def handle_detect(self):
        """处理检测请求"""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            ke_json = json.loads(body)

            fuwen_list = get_fuwen_list()
            matched = detect_fuwen(ke_json, fuwen_list)

            self.send_json({
                'success': True,
                'matched_count': len(matched),
                'matched_fuwen': matched
            })

        except Exception as e:
            self.send_json({
                'success': False,
                'error': str(e)
            }, 500)

    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def log_message(self, format, *args):
        print(f"[{self.log_date_time_string()}] {args[0]}")


def wait_for_neo4j(timeout=60):
    """等待 Neo4j 就绪"""
    import time
    import requests
    
    print("⏳ 等待 Neo4j 就绪...")
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            resp = requests.get("http://localhost:7474", timeout=2)
            if resp.status_code == 200:
                print("✅ Neo4j 就绪")
                return True
        except:
            pass
        time.sleep(2)
    
    print("❌ Neo4j 启动超时")
    return False


if __name__ == '__main__':
    print(f"🔮 赋文检测器启动中...")
    
    # 等待 Neo4j
    if not wait_for_neo4j():
        sys.exit(1)
    
    # 预加载赋文数据
    get_fuwen_list()
    
    server = HTTPServer(('0.0.0.0', PORT), FuwenDetectorHandler)
    print(f"✅ 赋文检测器运行在 http://0.0.0.0:{PORT}")
    print(f"   检测接口: POST /fuwen/detect")
    print(f"   健康检查: GET /health")
    print(f"   重新加载: GET /reload")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 赋文检测器已停止")
        server.server_close()
