"""Pitch remapping for live edits of a roof contour."""
from __future__ import annotations
from math import sqrt

def _p3(p):
    v=tuple(float(x) for x in p)
    return (v[0],v[1],v[2] if len(v)>2 else 0.0)

def _sub(a,b): return tuple(a[i]-b[i] for i in range(3))
def _dot(a,b): return sum(x*y for x,y in zip(a,b))
def _len(v): return sqrt(_dot(v,v))
def _dist(a,b): return _len(_sub(a,b))

def _point_segment_distance(p,a,b):
    d=_sub(b,a); q=_dot(d,d)
    if q<=1e-24: return _dist(p,a)
    t=max(0.0,min(1.0,_dot(_sub(p,a),d)/q))
    return _dist(p,tuple(a[i]+d[i]*t for i in range(3)))

def _path(start,end,count,step):
    out=[]; cur=start
    while cur!=end and len(out)<count:
        out.append(cur if step>0 else (cur-1)%count)
        cur=(cur+step)%count
    return out if cur==end else []

def _weighted(indices,points,values):
    weights=[max(_dist(points[i],points[(i+1)%len(points)]),1e-12) for i in indices]
    return sum(values[i]*w for i,w in zip(indices,weights))/sum(weights)

def _match_vertex(p,points,tolerance):
    best=None; distance=tolerance
    for i,q in enumerate(points):
        d=_dist(p,q)
        if d<=distance: best,distance=i,d
    return best

def _incident_edge(vertex,role,new_vector,midpoint,old_points):
    n=len(old_points)
    if role=="START":
        candidates=((vertex,_sub(old_points[(vertex+1)%n],old_points[vertex])),
                    ((vertex-1)%n,_sub(old_points[(vertex-1)%n],old_points[vertex])))
    else:
        new_vector=tuple(-v for v in new_vector)
        candidates=(((vertex-1)%n,_sub(old_points[(vertex-1)%n],old_points[vertex])),
                    (vertex,_sub(old_points[(vertex+1)%n],old_points[vertex])))
    nl=_len(new_vector); best=candidates[0][0]; score_best=float("inf")
    for index,direction in candidates:
        dl=_len(direction)
        alignment=abs(_dot(new_vector,direction)/(nl*dl)) if nl>1e-12 and dl>1e-12 else 0.0
        distance=_point_segment_distance(midpoint,old_points[index],old_points[(index+1)%n])
        score=distance+(1.0-alignment)*max(nl,dl)*0.15
        if score<score_best: best,score_best=index,score
    return best

def remap_contour_edge_values(previous_points,previous_values,current_points,default_value):
    """Preserve pitches on split edges and blend pitches when edges are merged."""
    old=tuple(_p3(p) for p in previous_points); new=tuple(_p3(p) for p in current_points)
    values=tuple(float(v) for v in previous_values); default=float(default_value)
    if len(new)<3: raise ValueError("A roof contour needs at least three vertices.")
    if len(old)<3 or len(values)!=len(old): return [default]*len(new)
    all_points=old+new
    scale=max(1.0,*(
        max(p[a] for p in all_points)-min(p[a] for p in all_points)
        for a in range(3)
    ))
    tolerance=scale*1e-7; result=[]
    for i,a in enumerate(new):
        b=new[(i+1)%len(new)]; vector=_sub(b,a)
        midpoint=tuple((a[k]+b[k])*0.5 for k in range(3))
        ia=_match_vertex(a,old,tolerance); ib=_match_vertex(b,old,tolerance)
        if ia is not None and ib is not None and ia!=ib:
            paths=[p for p in (_path(ia,ib,len(old),1),_path(ia,ib,len(old),-1)) if p]
            if paths:
                path=min(paths,key=lambda p:(len(p),sum(_dist(old[j],old[(j+1)%len(old)]) for j in p)))
                result.append(_weighted(path,old,values)); continue
        if ia is not None:
            result.append(values[_incident_edge(ia,"START",vector,midpoint,old)]); continue
        if ib is not None:
            result.append(values[_incident_edge(ib,"END",vector,midpoint,old)]); continue
        nl=_len(vector); best=0; best_score=float("inf")
        for j,p in enumerate(old):
            q=old[(j+1)%len(old)]; d=_sub(q,p); dl=_len(d)
            alignment=abs(_dot(vector,d)/(nl*dl)) if nl>1e-12 and dl>1e-12 else 0.0
            score=_point_segment_distance(midpoint,p,q)+(1.0-alignment)*max(nl,dl)*0.15
            if score<best_score: best,best_score=j,score
        result.append(values[best])
    return result
