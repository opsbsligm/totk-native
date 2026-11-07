# SPDX-License-Identifier: MIT
"""Renderer-independent anchor contract. Pixel coordinates are authoritative.
Optional coverage can be supplied in pixels; legacy source shapes can instead be
projected with a restricted arithmetic expression, never eval or executable code.
"""
import ast
import math
import operator

OPS={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv}

def arithmetic(expression,x,y):
    tree=ast.parse(expression,mode='eval')
    if sum(1 for _ in ast.walk(tree))>128:raise ValueError('Projection expression too complex')
    def visit(n):
        if isinstance(n,ast.Expression):return visit(n.body)
        if isinstance(n,ast.Constant) and type(n.value) in (int,float):return float(n.value)
        if isinstance(n,ast.Name) and n.id in ('x','y'):return x if n.id=='x' else y
        if isinstance(n,ast.UnaryOp) and isinstance(n.op,(ast.UAdd,ast.USub)):return visit(n.operand)*(1 if isinstance(n.op,ast.UAdd) else -1)
        if isinstance(n,ast.BinOp) and type(n.op) in OPS:return OPS[type(n.op)](visit(n.left),visit(n.right))
        raise ValueError('Projection accepts numbers, x/y and + - * / only')
    result=visit(tree)
    if not math.isfinite(result):raise ValueError('Nonfinite projection result')
    return result

def validate(doc):
    width,height=doc['width'],doc['height']
    if not all(type(v) in (int,float) and math.isfinite(v) and v>0 for v in (width,height)):raise ValueError('Positive finite renderer canvas required')
    out={}
    for a in doc['anchors']:
        if not isinstance(a['id'],str) or a['id'] in out:raise ValueError('Unique string anchor IDs required')
        p=a['pixel']
        if len(p)!=2 or not all(type(v) in (int,float) and math.isfinite(v) for v in p) or not (0<=p[0]<=width and 0<=p[1]<=height):raise ValueError('Anchor pixel outside renderer canvas')
        out[a['id']]=a
    return out

def coverage_points(control,anchors,doc):
    """Return absolute pixel support points, priority: explicit > source > fallback."""
    if control in doc.get('group_coverage',{}):
        points=doc['group_coverage'][control]
    else:
        ids=('face_south','face_east','face_west','face_north') if control=='ABXY' else ('dpad_center',) if control=='CrossKey' else ()
        points=[]
        for key in ids:
            a=anchors[key];px,py=a['pixel']
            if 'coverage_points' in a:points.extend(a['coverage_points']);continue
            if 'coverage_bounds' in a:
                x0,y0,x1,y1=a['coverage_bounds']
                if x1<x0 or y1<y0:raise ValueError('Invalid coverage bounds')
                points.extend([[x,y] for x in (x0,x1) for y in (y0,y1)]);continue
            if 'coverage_radius' in a:
                r=a['coverage_radius']
                if not math.isfinite(r) or r<0:raise ValueError('Invalid coverage radius')
                points.extend([[px+sx*r,py+sy*r] for sx in (-1,1) for sy in (-1,1)]);continue
            transform=doc.get('transform',{})
            if a.get('source') is not None and 'x' in transform and 'y' in transform:
                x,y=a['source']
                offsets=[(sx*10.,sy*10.) for sx in (-1,1) for sy in (-1,1)] if control=='ABXY' else [(sx*hx,sy*hy) for hx,hy in [(6.,19.),(19.,6.)] for sx in (-1,1) for sy in (-1,1)]
                bx=arithmetic(transform['x'],x,y);by=arithmetic(transform['y'],x,y)
                # Pixel anchor wins even if source metadata is not moved with it.
                points.extend([[px+arithmetic(transform['x'],x+dx,y+dy)-bx,py+arithmetic(transform['y'],x+dx,y+dy)-by] for dx,dy in offsets])
            else:
                r=10. if control=='ABXY' else 19.
                points.extend([[px+sx*r,py+sy*r] for sx in (-1,1) for sy in (-1,1)])
    if not points or any(len(p)!=2 or not all(type(v) in (int,float) and math.isfinite(v) for v in p) for p in points):
        if control not in ('ABXY','CrossKey') and not points:return []
        raise ValueError('Finite coverage points required')
    return points
