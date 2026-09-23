#!/usr/bin/env python3
"""
赋文检测器核心逻辑
支持多种赋文（心印赋、指掌赋等）的 conditions_code 检测
"""

import json
import sys
import os
import importlib.util
import requests
from requests.auth import HTTPBasicAuth

# Neo4j配置
NEO4J_HTTP = 'http://localhost:7474/db/neo4j/query/v2'
NEO4J_AUTH = HTTPBasicAuth('neo4j', 'password123')

# 积木目录
BLOCKS_DIR = os.path.expanduser('~/.openclaw/workspace/memory/renke-blocks')
BLOCKS_SUBDIRS = ['atoms', 'relations', 'state', 'combinations', 'combinations/liuqin']

# 添加积木目录到 sys.path
for subdir in BLOCKS_SUBDIRS:
    subdir_path = os.path.join(BLOCKS_DIR, subdir)
    if subdir_path not in sys.path:
        sys.path.insert(0, subdir_path)

# 缓存已加载的积木模块
_blocks_cache = {}


def load_block_module(block_name: str):
    """动态加载积木模块"""
    if block_name in _blocks_cache:
        return _blocks_cache[block_name]
    
    for subdir in BLOCKS_SUBDIRS:
        block_path = os.path.join(BLOCKS_DIR, subdir, f'{block_name}.py')
        if os.path.exists(block_path):
            spec = importlib.util.spec_from_file_location(block_name, block_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            _blocks_cache[block_name] = module
            return module
    
    raise ImportError(f"积木模块未找到: {block_name}")


def resolve_var(var_name, context: dict):
    """解析变量引用（$开头的变量），支持嵌套字典和列表"""
    # 字符串变量引用
    if isinstance(var_name, str) and var_name.startswith('$'):
        key = var_name[1:]
        if key in context:
            return context[key]
        else:
            raise ValueError(f"变量未定义: {var_name}")
    
    # 字典格式变量引用 {"var": "xxx"}
    if isinstance(var_name, dict) and 'var' in var_name and 'block' not in var_name:
        key = var_name['var']
        if key in context:
            return context[key]
        else:
            raise ValueError(f"变量未定义: {key}")
    
    # 嵌套字典（积木函数调用）
    if isinstance(var_name, dict) and 'block' in var_name and 'fn' in var_name:
        block_name = var_name['block']
        fn_name = var_name['fn']
        args = var_name.get('args', [])
        
        module = load_block_module(block_name)
        func = getattr(module, fn_name)
        
        resolved_args = [resolve_var(arg, context) for arg in args]
        # 如果参数中有空字符串（可选变量未提供），返回空字符串而非调用函数
        if any(isinstance(a, str) and a == '' for a in resolved_args):
            return ''
        return func(*resolved_args)
    
    # 列表（递归解析）
    if isinstance(var_name, list):
        return [resolve_var(item, context) for item in var_name]
    
    return var_name


def _has_empty_arg(args: list, context: dict) -> bool:
    """检查参数列表中是否有空字符串（可选变量未提供）"""
    for arg in args:
        try:
            val = resolve_var(arg, context)
            if isinstance(val, str) and val == '':
                return True
        except:
            return True
    return False


def execute_vars(vars_def: dict, context: dict) -> dict:
    """执行vars定义，计算变量值"""
    computed = {}
    
    for var_name, var_def in vars_def.items():
        block_name = var_def['block']
        fn_name = var_def['fn']
        args = var_def['args']
        
        # 如果参数中包含空字符串（可选变量未提供），跳过计算
        if _has_empty_arg(args, {**context, **computed}):
            computed[var_name] = ''
            continue
        
        module = load_block_module(block_name)
        func = getattr(module, fn_name)
        
        resolved_args = [resolve_var(arg, {**context, **computed}) for arg in args]
        try:
            result = func(*resolved_args)
            # 元组返回值处理
            if isinstance(result, tuple) and len(result) > 0 and isinstance(result[0], bool):
                result = result[0]
            computed[var_name] = result
        except Exception:
            computed[var_name] = ''
    
    return computed


def execute_condition(condition: dict, context: dict) -> bool:
    """执行单个条件判断"""
    # 简写格式兼容：{"and": [...]} 等价于 {"op": "and", "conditions": [...]}
    if 'and' in condition and 'op' not in condition and 'logic' not in condition and 'block' not in condition:
        sub_conditions = condition['and']
        return all(execute_condition(cond, context) for cond in sub_conditions)
    
    # 简写格式兼容：{"or": [...]} 等价于 {"op": "or", "conditions": [...]}
    if 'or' in condition and 'op' not in condition and 'logic' not in condition and 'block' not in condition:
        sub_conditions = condition['or']
        return any(execute_condition(cond, context) for cond in sub_conditions)
    
    # 积木函数调用
    if 'block' in condition and 'fn' in condition:
        block_name = condition['block']
        fn_name = condition['fn']
        args = condition.get('args', [])
        
        # 如果参数中包含空字符串（可选变量未提供），直接返回 False
        if _has_empty_arg(args, context):
            return False
        
        module = load_block_module(block_name)
        func = getattr(module, fn_name)
        
        try:
            resolved_args = [resolve_var(arg, context) for arg in args]
            result = func(*resolved_args)
            if isinstance(result, tuple) and len(result) > 0 and isinstance(result[0], bool):
                return result[0]
            return result
        except Exception:
            return False
    
    # 或逻辑（嵌套）
    if condition.get('op') == 'or' or condition.get('logic') == 'OR':
        sub_conditions = condition.get('conditions', [])
        return any(execute_condition(cond, context) for cond in sub_conditions)
    
    # 且逻辑（嵌套）
    if condition.get('op') == 'and' or condition.get('logic') == 'AND':
        sub_conditions = condition.get('conditions', [])
        return all(execute_condition(cond, context) for cond in sub_conditions)
    
    # 比较操作符
    op = condition.get('op')
    
    if op == '==':
        left = resolve_var(condition['left'], context)
        right = resolve_var(condition['right'], context)
        return left == right
    
    elif op == '!=':
        left = resolve_var(condition['left'], context)
        right = resolve_var(condition['right'], context)
        return left != right
    
    elif op == 'in':
        left = resolve_var(condition['left'], context)
        right = condition['right']
        if isinstance(right, list):
            right = [resolve_var(x, context) for x in right]
        else:
            right = resolve_var(right, context)
        if isinstance(right, (list, tuple, set)):
            return left in right
        return False
    
    elif op == 'not_in':
        left = resolve_var(condition['left'], context)
        right = resolve_var(condition['right'], context)
        if isinstance(right, (list, tuple, set)):
            return left not in right
        return True
    
    elif op == '>=':
        left = resolve_var(condition['left'], context)
        right = resolve_var(condition['right'], context)
        return left >= right
    
    elif op == '>':
        left = resolve_var(condition['left'], context)
        right = resolve_var(condition['right'], context)
        return left > right
    
    elif op == '<=':
        left = resolve_var(condition['left'], context)
        right = resolve_var(condition['right'], context)
        return left <= right
    
    elif op == '<':
        left = resolve_var(condition['left'], context)
        right = resolve_var(condition['right'], context)
        return left < right
    
    elif op == 'contains':
        left = resolve_var(condition['left'], context)
        right = resolve_var(condition['right'], context)
        if isinstance(left, (list, tuple, set)):
            return right in left
        return False
    
    else:
        raise ValueError(f"不支持的操作符: {op}")


def detect_fuwen(ke_json: dict, fuwen_list: list) -> list:
    """
    检测课式匹配的赋文格局
    
    Args:
        ke_json: 起课引擎输出的课式JSON
        fuwen_list: 赋文格局列表（从Neo4j查询）
    
    Returns:
        匹配的赋文格局列表
    """
    # 预处理：转换格式（与课体课格检测器相同）
    
    # 天地盘映射
    tiandipan_raw = ke_json.get('tiandipan_struct', ke_json.get('tiandipan', {}))
    if isinstance(tiandipan_raw, list):
        context_tiandipan = {item[1]: item[0] for item in tiandipan_raw}
    else:
        context_tiandipan = tiandipan_raw
    
    # 四课
    sike_raw = ke_json.get('sike_struct', ke_json.get('sike', {}))
    if isinstance(sike_raw, list) and len(sike_raw) >= 4:
        context_sike = {
            "第一课": {"上神": sike_raw[0][1], "下神": sike_raw[0][0]},
            "第二课": {"上神": sike_raw[1][1], "下神": sike_raw[1][0]},
            "第三课": {"上神": sike_raw[2][1], "下神": sike_raw[2][0]},
            "第四课": {"上神": sike_raw[3][1], "下神": sike_raw[3][0]},
        }
    else:
        context_sike = sike_raw
    
    # 三传
    sanchuan_raw = ke_json.get('sanchuan', ke_json.get('sanchuan_struct', {}))
    if isinstance(sanchuan_raw, list) and len(sanchuan_raw) >= 3:
        context_sanchuan = {
            "初传": {"地支": sanchuan_raw[0]},
            "中传": {"地支": sanchuan_raw[1]},
            "末传": {"地支": sanchuan_raw[2]},
        }
    elif isinstance(sanchuan_raw, dict):
        first_val = next(iter(sanchuan_raw.values()), None)
        if isinstance(first_val, str):
            context_sanchuan = {
                "初传": {"地支": sanchuan_raw.get("初传", "")},
                "中传": {"地支": sanchuan_raw.get("中传", "")},
                "末传": {"地支": sanchuan_raw.get("末传", "")},
            }
        else:
            context_sanchuan = sanchuan_raw
    else:
        context_sanchuan = sanchuan_raw
    
    # 天将位置
    tianjiang_raw = ke_json.get('tianjiang', ke_json.get('tianjiang_position', {}))
    if tianjiang_raw and isinstance(tianjiang_raw, dict):
        first_val = next(iter(tianjiang_raw.values()), None)
        if first_val and first_val in ['贵人', '螣蛇', '朱雀', '六合', '勾陈', '青龙', '天空', '白虎', '太常', '玄武', '太阴', '天后']:
            context_tianjiang_position = {v: k for k, v in tianjiang_raw.items()}
        else:
            context_tianjiang_position = tianjiang_raw
    else:
        context_tianjiang_position = tianjiang_raw
    
    # 日干寄宫
    TIANGAN_JIGONG = {
        '甲': '寅', '乙': '辰', '丙': '巳', '丁': '未',
        '戊': '巳', '己': '未', '庚': '申', '辛': '戌',
        '壬': '亥', '癸': '丑'
    }
    rigan = ke_json.get('day', '甲')[0]
    jigong = TIANGAN_JIGONG.get(rigan, '')
    
    # 构建检测上下文
    context = {
        # 四柱
        'year_gz': ke_json.get('year', '甲子'),
        'month_gz': ke_json.get('month', '甲子'),
        'day_gz': ke_json.get('day', '甲子'),
        'hour_gz': ke_json.get('hour', '甲子'),
        
        # 四柱（分离）
        'rigan': rigan,
        'rizhi': ke_json.get('day', '甲')[1],
        'year_branch': ke_json.get('year', '甲')[1],
        'month_branch': ke_json.get('month', '甲')[1],
        'hour_branch': ke_json.get('hour', '甲子')[1] if len(ke_json.get('hour', '甲子')) > 1 else '',
        'zhanshi': ke_json.get('zhanshi', '子'),
        
        # 日干寄宫
        'jigong': jigong,
        
        # 日期时间
        'datetime': ke_json.get('datetime', ''),
        
        # 三传
        'chuchuan': ke_json.get('chu_chuan', '子'),
        'zhongchuan': ke_json.get('zhong_chuan', '子'),
        'mochuan': ke_json.get('mo_chuan', '子'),
        
        # 空亡
        'kong_wang': ke_json.get('kong_wang', []),
        'kongwang': ke_json.get('kong_wang', []),  # 兼容别名
        
        # 月将
        'yuejiang': ke_json.get('yuejiang', '子'),
        
        # 天地盘
        'tiandipan': context_tiandipan,
        
        # 四课
        'sike': context_sike,
        
        # 三传
        'sanchuan': context_sanchuan,
        
        # 三传列表（列表格式，供需要列表参数的积木函数使用）
        'sanchuan_list': [
            ke_json.get('chu_chuan', '子'),
            ke_json.get('zhong_chuan', '子'),
            ke_json.get('mo_chuan', '子'),
        ],
        
        # 四课列表（列表格式，供需要列表参数的积木函数使用）
        'sike_list': [
            [sike_raw[i][0], sike_raw[i][1]] if isinstance(sike_raw, list) and i < len(sike_raw) else ['','']
            for i in range(4)
        ] if isinstance(sike_raw, list) and len(sike_raw) >= 4 else [],
        
        # 天将位置
        'tianjiang_position': context_tianjiang_position,
    }
    
    # 可选字段
    if ke_json.get('benming'):
        context['benming'] = ke_json['benming'][1] if len(ke_json['benming']) > 1 else ke_json['benming']
    else:
        context['benming'] = ''
    
    if ke_json.get('xingnian_branch'):
        context['xingnian'] = ke_json['xingnian_branch']
    else:
        context['xingnian'] = ''
    
    # 男女行年、男女本命
    if ke_json.get('nan_xingnian'):
        context['nan_xingnian'] = ke_json['nan_xingnian']
    else:
        context['nan_xingnian'] = ''
    
    if ke_json.get('nv_xingnian'):
        context['nv_xingnian'] = ke_json['nv_xingnian']
    else:
        context['nv_xingnian'] = ''
    
    if ke_json.get('nan_benming'):
        context['nan_benming'] = ke_json['nan_benming']
    else:
        context['nan_benming'] = ''
    
    if ke_json.get('nv_benming'):
        context['nv_benming'] = ke_json['nv_benming']
    else:
        context['nv_benming'] = ''
    
    matched = []
    
    for fuwen in fuwen_list:
        try:
            fuwen_id = fuwen.get('id', '')
            fuwen_name = fuwen.get('name', '')
            fuwen_label = fuwen.get('label', '')
            
            # 解析conditions_code
            cc_str = fuwen.get('conditions_code', '{}')
            cc = json.loads(cc_str) if isinstance(cc_str, str) else cc_str
            
            vars_def = cc.get('vars', {})
            conditions = cc.get('conditions', [])
            logic = cc.get('logic', 'AND')
            
            # 执行vars
            computed_vars = execute_vars(vars_def, context)
            full_context = {**context, **computed_vars}
            
            # 执行conditions
            results = [execute_condition(cond, full_context) for cond in conditions]
            
            # 根据logic判断
            if logic == 'AND':
                is_match = all(results)
            elif logic == 'OR':
                is_match = any(results)
            else:
                is_match = False
            
            if is_match:
                matched.append({
                    'id': fuwen_id,
                    'name': fuwen_name,
                    'label': fuwen_label,
                    'judgment': fuwen.get('judgment', ''),
                    'yuanwen': fuwen.get('yuanwen', '')
                })
        
        except Exception as e:
            print(f"⚠️ 赋文 {fuwen.get('id')} 检测失败: {e}", file=sys.stderr)
            continue
    
    return matched


def fetch_all_fuwen() -> list:
    """从Neo4j查询所有赋文节点（支持多标签）"""
    # 支持：心印赋:概念、指掌赋：条文
    # 使用 UNION 合并两种标签的查询，统一属性名映射
    statement = """
    MATCH (n:`心印赋:概念`)
    WHERE n.conditions_code IS NOT NULL
    RETURN n.id AS id, n.name AS name, n.conditions_code AS conditions_code,
           n.judgment AS judgment, n.yuanwen AS yuanwen,
           '心印赋:概念' AS label
    UNION
    MATCH (n:`指掌赋：条文`)
    WHERE n.conditions_code IS NOT NULL
    RETURN n.id AS id, n.subject AS name, n.conditions_code AS conditions_code,
           n.judgment AS judgment, n.original_text AS yuanwen,
           '指掌赋：条文' AS label
    """
    
    payload = {'statement': statement}
    
    resp = requests.post(NEO4J_HTTP, json=payload, auth=NEO4J_AUTH)
    result = resp.json()
    
    if 'errors' in result and result['errors']:
        raise Exception(f"Neo4j查询失败: {result['errors']}")
    
    fields = result['data']['fields']
    values = result['data']['values']
    
    fuwen_list = []
    for row in values:
        fuwen = dict(zip(fields, row))
        fuwen_list.append(fuwen)
    
    return fuwen_list


if __name__ == '__main__':
    # 测试：加载所有赋文
    fuwen = fetch_all_fuwen()
    print(f"从Neo4j加载了 {len(fuwen)} 个赋文节点")
    
    # 测试：用一个简单课式检测
    test_ke = {
        'day': '甲子',
        'year': '丙午',
        'month': '庚寅',
        'zhanshi': '亥',
        'chu_chuan': '子',
        'zhong_chuan': '丑',
        'mo_chuan': '寅',
        'yuejiang': '子',
        'kong_wang': ['子', '丑']
    }
    
    matched = detect_fuwen(test_ke, fuwen)
    print(f"\n测试课式匹配了 {len(matched)} 个赋文格局:")
    for m in matched:
        print(f"  - [{m['label']}] {m['id']}: {m['name']}")
