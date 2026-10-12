#!/usr/bin/env python3
"""
赋文检测器 HTTP API 服务（FastAPI 异步版）
端口 8010
"""

import sys
import os
import json
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

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


app = FastAPI(title="赋文检测器", version="2.0.0")


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


@app.on_event("startup")
async def startup():
    print(f"🔮 赋文检测器启动中...")
    
    # 等待 Neo4j
    if not wait_for_neo4j():
        sys.exit(1)
    
    # 预加载赋文数据
    get_fuwen_list()
    
    print(f"✅ 赋文检测器运行在 http://0.0.0.0:{PORT}")
    print(f"   检测接口: POST /fuwen/detect")
    print(f"   健康检查: GET /health")
    print(f"   重新加载: GET /reload")


@app.get("/health")
async def health():
    return {"status": "ok", "fuwen_count": len(get_fuwen_list())}


@app.get("/reload")
async def reload():
    global _fuwen_cache
    _fuwen_cache = None
    count = len(get_fuwen_list())
    return {"status": "reloaded", "count": count}


@app.post("/fuwen/detect")
async def detect(request: Request):
    try:
        ke_json = await request.json()
        
        fuwen_list = get_fuwen_list()
        
        # CPU密集型，用 run_in_executor 避免阻塞
        loop = asyncio.get_event_loop()
        matched = await loop.run_in_executor(None, detect_fuwen, ke_json, fuwen_list)
        
        return {
            'success': True,
            'matched_count': len(matched),
            'matched_fuwen': matched
        }
    except Exception as e:
        return JSONResponse({
            'success': False,
            'error': str(e)
        }, status_code=500)


if __name__ == '__main__':
    uvicorn.run(app, host='0.0.0.0', port=PORT, log_level='info')
