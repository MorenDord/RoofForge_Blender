"""Experimental 3D-eave roof solver for RoofForge 2.8.

Each boundary edge defines a planar roof facet containing its 3D eave edge.
The requested pitch is the magnitude of that facet's horizontal height gradient.
The roof surface is the lower envelope of those support planes over the footprint.
This is a deterministic plane-arrangement solver, not a 3D straight-skeleton.
"""
import math
from collections import defaultdict

class SpatialRoofError(ValueError):
    pass

def _cross2(a,b): return a[0]*b[1]-a[1]*b[0]
def _area(poly): return .5*sum(_cross2(poly[i],poly[(i+1)%len(poly)]) for i in range(len(poly)))
def _dist2(a,b): return math.hypot(a[0]-b[0],a[1]-b[1])
def _clean(poly,eps):
    out=[]
    for p in poly:
        if not out or _dist2(p,out[-1])>eps: out.append(tuple(p))
    if len(out)>1 and _dist2(out[0],out[-1])<=eps: out.pop()
    return out

def _triangulate(poly,eps):
    """Ear-clip a simple CCW XY polygon; returns triangles of point tuples."""
    pts=list(poly); ids=list(range(len(pts))); result=[]
    if _area(pts)<0: ids.reverse()
    def inside(p,a,b,c):
        c1=_cross2((b[0]-a[0],b[1]-a[1]),(p[0]-a[0],p[1]-a[1]))
        c2=_cross2((c[0]-b[0],c[1]-b[1]),(p[0]-b[0],p[1]-b[1]))
        c3=_cross2((a[0]-c[0],a[1]-c[1]),(p[0]-c[0],p[1]-c[1]))
        return c1>=-eps and c2>=-eps and c3>=-eps
    guard=0
    while len(ids)>3:
        guard+=1
        if guard>len(pts)*len(pts)*2: raise SpatialRoofError('Не удалось триангулировать XY-проекцию контура.')
        found=False
        for k in range(len(ids)):
            ia,ib,ic=ids[k-1],ids[k],ids[(k+1)%len(ids)]
            a,b,c=pts[ia],pts[ib],pts[ic]
            if _cross2((b[0]-a[0],b[1]-a[1]),(c[0]-b[0],c[1]-b[1]))<=eps: continue
            if any(inside(pts[j],a,b,c) for j in ids if j not in (ia,ib,ic)): continue
            result.append((a,b,c)); ids.pop(k); found=True; break
        if not found: raise SpatialRoofError('Контур самопересекается, содержит вырожденные углы или не имеет простой XY-проекции.')
    result.append(tuple(pts[i] for i in ids))
    return result

def _clip(poly, A,B,C,eps):
    """Clip convex XY polygon to A*x+B*y+C <= 0."""
    if not poly: return []
    out=[]
    for p,q in zip(poly,poly[1:]+poly[:1]):
        fp=A*p[0]+B*p[1]+C; fq=A*q[0]+B*q[1]+C
        pin=fp<=eps; qin=fq<=eps
        if pin: out.append(p)
        if pin != qin:
            den=fp-fq
            if abs(den)>1e-20:
                t=fp/den
                out.append((p[0]+(q[0]-p[0])*t,p[1]+(q[1]-p[1])*t))
    return _clean(out,eps)

def _edge_plane(p,q,pitch,orientation):
    dx=q[0]-p[0]; dy=q[1]-p[1]; dz=q[2]-p[2]
    h=math.hypot(dx,dy)
    if h<=1e-10: raise SpatialRoofError('Обнаружено почти вертикальное ребро карниза: его XY-проекция имеет нулевую длину.')
    t=(dx/h,dy/h); inward=(-t[1],t[0])
    # Ensure inward is toward polygon interior (CCW).
    if orientation<0: inward=(-inward[0],-inward[1])
    along=dz/h; slope=math.tan(float(pitch))
    if slope+1e-9<abs(along):
        raise SpatialRoofError(f'Угол ската {math.degrees(pitch):.2f}° меньше уклона карнизного ребра {math.degrees(math.atan(abs(along))):.2f}°. Плоскость такого ската невозможна.')
    inward_component=math.sqrt(max(0.0,slope*slope-along*along))
    gx=along*t[0]+inward_component*inward[0]
    gy=along*t[1]+inward_component*inward[1]
    c=p[2]-gx*p[0]-gy*p[1]
    return (gx,gy,c)

def build_spatial_roof_mesh(outline_xyz, pitch_angles, eave_lift=0.0, tolerance=None):
    """Return (vertices, faces, source_edge_ids) for an arbitrary-Z eave loop.

    Pitch angles are radians, one per ordered contour edge. The support plane
    for each edge contains its 3D endpoints and rises inward. The lower envelope
    partitions the footprint into planar facet cells. Unsupported/ambiguous
    configurations fail explicitly instead of silently producing bad topology.
    """
    pts=[tuple(map(float,p)) for p in outline_xyz]; n=len(pts)
    if n<3 or len(pitch_angles)!=n: raise SpatialRoofError('Нужно минимум три вершины и ровно один угол на каждое ребро контура.')
    if any(len(p)!=3 or not all(math.isfinite(v) for v in p) for p in pts): raise SpatialRoofError('Координаты контура должны быть конечными XYZ.')
    xy=[p[:2] for p in pts]
    span=max(max(p[0] for p in xy)-min(p[0] for p in xy),max(p[1] for p in xy)-min(p[1] for p in xy),1.0)
    eps=float(tolerance or span*1e-9)
    area=_area(xy)
    if abs(area)<=eps*eps: raise SpatialRoofError('XY-проекция контура имеет нулевую площадь.')
    orient=1 if area>0 else -1
    # Normalize CCW while keeping edge-angle association correct.
    if orient<0:
        old_angles=list(pitch_angles)
        pts=list(reversed(pts))
        # Reversing vertex order also reverses each edge. New edge i maps to
        # old edge (n-2-i) modulo n, not simply the reversed array.
        pitch_angles=[old_angles[(n-2-i) % n] for i in range(n)]
        xy=[p[:2] for p in pts]; orient=1
    for i in range(n):
        if _dist2(xy[i],xy[(i+1)%n])<=eps: raise SpatialRoofError(f'Ребро {i+1} имеет нулевую длину в XY.')
    planes=[_edge_plane(pts[i],pts[(i+1)%n],pitch_angles[i],orient) for i in range(n)]
    triangles=_triangulate(xy,eps)
    patches=defaultdict(list)
    for edge_id,(a,b,c) in enumerate(planes):
        for tri in triangles:
            cell=list(tri)
            for aa,bb,cc in planes:
                if (aa,bb,cc)==(a,b,c): continue
                cell=_clip(cell,a-aa,b-bb,c-cc,eps)
                if len(cell)<3: break
            if len(cell)<3 or abs(_area(cell))<=eps*eps: continue
            patch=[(x,y,a*x+b*y+c+float(eave_lift)) for x,y in cell]
            if _area(cell)<0: patch.reverse()
            patches[edge_id].append(patch)
    # Union adjacent triangle fragments by cancelling their directed edges.
    vertices=[]; faces=[]; sources=[]; vmap={}
    qtol=max(eps*10,1e-8)
    for edge_id,group in patches.items():
        # Canonical point ids, then directed boundary incidence.
        local_points=[]; buckets=defaultdict(list)
        def vid(p):
            key=tuple(round(v/qtol) for v in p)
            for idx in buckets[key]:
                if math.dist(local_points[idx],p)<=qtol: return idx
            idx=len(local_points); local_points.append(p); buckets[key].append(idx); return idx
        uses=defaultdict(int)
        for patch in group:
            ids=[vid(p) for p in patch]
            for a,b in zip(ids,ids[1:]+ids[:1]):
                if a!=b: uses[(a,b)]+=1
        boundary=[]
        for (a,b),count in uses.items():
            reverse=uses.get((b,a),0); net=count-reverse
            if net>0:
                if net!=1: raise SpatialRoofError(f'Скат {edge_id+1}: неманифолдная граница между треугольными фрагментами.')
                boundary.append((a,b))
        outgoing=defaultdict(list)
        for a,b in boundary: outgoing[a].append(b)
        unused=set(boundary)
        while unused:
            start=min(unused); loop=[start[0]]; cur=start; guard=0
            while True:
                guard+=1
                if guard>len(boundary)+2: raise SpatialRoofError(f'Скат {edge_id+1}: не удалось замкнуть границу.')
                if cur not in unused: raise SpatialRoofError(f'Скат {edge_id+1}: повторная граница.')
                unused.remove(cur); a,b=cur; loop.append(b)
                if b==loop[0]: break
                candidates=[(b,c) for c in outgoing[b] if (b,c) in unused]
                if not candidates: raise SpatialRoofError(f'Скат {edge_id+1}: незамкнутая граница.')
                cur=min(candidates)
            loop=loop[:-1]
            if len(loop)<3: continue
            face=[]
            for local_id in loop:
                p=local_points[local_id]; key=tuple(round(v/qtol) for v in p)
                idx=vmap.get(key)
                if idx is None:
                    idx=len(vertices); vertices.append(p); vmap[key]=idx
                face.append(idx)
            if len(set(face))>=3:
                faces.append(tuple(face)); sources.append(edge_id)
    if not faces: raise SpatialRoofError('Для заданных высот и углов не удалось сформировать ни одного ската.')
    # Verify the generated surface really closes over the complete eave loop.
    # A lower-envelope arrangement can otherwise silently discard an eave
    # segment when a non-adjacent support plane falls below its endpoint.
    edge_use=defaultdict(int)
    for face in faces:
        for a,b in zip(face,face[1:]+face[:1]): edge_use[tuple(sorted((a,b)))]+=1
    if any(v>2 for v in edge_use.values()): raise SpatialRoofError('Получена неманифолдная пространственная сетка крыши.')
    boundary=[(vertices[a],vertices[b]) for (a,b),uses in edge_use.items() if uses==1]
    intervals=[[] for _ in range(n)]
    scale=max(span,1.0)
    check_eps=max(eps*20,scale*1.0e-7)
    for a,b in boundary:
        matched=False
        for i in range(n):
            p,q=pts[i],pts[(i+1)%n]
            dx,dy=q[0]-p[0],q[1]-p[1]
            ll=dx*dx+dy*dy
            if ll<=eps*eps: continue
            ta=((a[0]-p[0])*dx+(a[1]-p[1])*dy)/ll
            tb=((b[0]-p[0])*dx+(b[1]-p[1])*dy)/ll
            da=math.hypot(a[0]-(p[0]+ta*dx),a[1]-(p[1]+ta*dy))
            db=math.hypot(b[0]-(p[0]+tb*dx),b[1]-(p[1]+tb*dy))
            za=p[2]+ta*(q[2]-p[2]); zb=p[2]+tb*(q[2]-p[2])
            if (-check_eps<=ta<=1+check_eps and -check_eps<=tb<=1+check_eps
                and da<=check_eps and db<=check_eps
                and abs(a[2]-za)<=check_eps and abs(b[2]-zb)<=check_eps):
                intervals[i].append((min(ta,tb),max(ta,tb))); matched=True; break
        if not matched:
            raise SpatialRoofError('Внутренняя граница пространственной поверхности не замкнулась: найдено ребро вне карниза. Измените высоты или углы скатов.')
    for i,parts in enumerate(intervals):
        parts.sort(); covered=0.0
        for lo,hi in parts:
            if lo>covered+check_eps:
                raise SpatialRoofError(f'Скат у ребра карниза {i+1} не доходит до всей кромки. Заданные высоты и углы несовместимы.')
            covered=max(covered,hi)
        if covered<1.0-check_eps:
            raise SpatialRoofError(f'Скат у ребра карниза {i+1} не покрывает всю кромку. Заданные высоты и углы несовместимы.')
    return vertices,faces,sources


def _face_unit_normal(vertices, face):
    """Return an upward-oriented unit normal for a planar XY-height face."""
    nx = ny = nz = 0.0
    points = [vertices[i] for i in face]
    for a, b in zip(points, points[1:] + points[:1]):
        nx += (a[1] - b[1]) * (a[2] + b[2])
        ny += (a[2] - b[2]) * (a[0] + b[0])
        nz += (a[0] - b[0]) * (a[1] + b[1])
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length <= 1.0e-14:
        raise SpatialRoofError("Нельзя определить нормаль одного из пространственных скатов.")
    normal = (nx / length, ny / length, nz / length)
    return normal if normal[2] >= 0.0 else tuple(-v for v in normal)


def _cross3(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _unit3(v, eps=1.0e-14):
    length = math.sqrt(sum(float(x) * float(x) for x in v))
    if length <= eps:
        raise SpatialRoofError("Невозможно вычислить направление пространственного свеса.")
    return tuple(float(x) / length for x in v)


def extend_spatial_roof_eaves(vertices, faces, face_source_ids, overhang, tolerance=None):
    """Extend the eave with one shared 3D miter vertex at each corner.

    Each eave edge is offset in its own facet plane. The two offset endpoints
    at a corner are replaced by one shared miter point on their 3D bisector.
    Each edge strip is triangulated, so adjacent strips share the single
    corner-to-miter edge instead of the old two-spoke corner triangle.

    Returns (vertices, faces, face_source_ids). Added eave faces use source -1.
    """
    distance = float(overhang)
    if distance <= 1.0e-10:
        return list(vertices), list(faces), list(face_source_ids)
    if len(faces) != len(face_source_ids):
        raise SpatialRoofError("Не совпадает число граней и идентификаторов скатов для свеса.")
    if not vertices or not faces:
        return list(vertices), list(faces), list(face_source_ids)

    span = max(
        max(max(float(v[k]) for v in vertices) - min(float(v[k]) for v in vertices) for k in range(3)),
        1.0,
    )
    eps = float(tolerance) if tolerance is not None else span * 1.0e-8
    eps = max(eps, 1.0e-9)

    edge_uses = defaultdict(list)
    for face_index, face in enumerate(faces):
        for a, b in zip(face, face[1:] + face[:1]):
            key = (a, b) if a < b else (b, a)
            edge_uses[key].append((face_index, a, b))
    if any(len(uses) > 2 for uses in edge_uses.values()):
        raise SpatialRoofError("Исходная пространственная поверхность уже имеет неманифолдные рёбра.")
    boundary = [uses[0] for uses in edge_uses.values() if len(uses) == 1]
    if len(boundary) < 3:
        raise SpatialRoofError("Не найдена замкнутая граница пространственной крыши.")

    out_vertices = [tuple(float(c) for c in v) for v in vertices]
    out_faces = [tuple(face) for face in faces]
    out_sources = list(face_source_ids)

    def point_key(point):
        return tuple(int(round(float(c) / eps)) for c in point)

    buckets = defaultdict(list)
    for index, point in enumerate(out_vertices):
        buckets[point_key(point)].append(index)

    def add_vertex(point):
        point = tuple(float(c) for c in point)
        key = point_key(point)
        for index in buckets[key]:
            if math.dist(out_vertices[index], point) <= eps * 2.0:
                return index
        index = len(out_vertices)
        out_vertices.append(point)
        buckets[key].append(index)
        return index

    incoming = defaultdict(list)
    outgoing = defaultdict(list)
    edge_records = []
    for face_index, a, b in boundary:
        face = faces[face_index]
        normal = _face_unit_normal(vertices, face)
        edge = tuple(float(vertices[b][k]) - float(vertices[a][k]) for k in range(3))
        edge_unit = _unit3(edge)
        outward = _unit3(_cross3(edge_unit, normal))
        pa = tuple(float(vertices[a][k]) + distance * outward[k] for k in range(3))
        pb = tuple(float(vertices[b][k]) + distance * outward[k] for k in range(3))
        incoming[b].append(pb)
        outgoing[a].append(pa)
        edge_records.append((a, b))

    corner_miters = {}
    for vertex_id in set(incoming) | set(outgoing):
        inc = incoming.get(vertex_id, ())
        out = outgoing.get(vertex_id, ())
        if len(inc) != 1 or len(out) != 1:
            raise SpatialRoofError("Свес встретил разветвлённую или незамкнутую границу крыши.")
        p = out_vertices[vertex_id]
        u = _unit3(tuple(inc[0][k] - p[k] for k in range(3)))
        v = _unit3(tuple(out[0][k] - p[k] for k in range(3)))
        raw = tuple(u[k] + v[k] for k in range(3))
        raw_length = math.sqrt(sum(value * value for value in raw))
        if raw_length <= 1.0e-8:
            raise SpatialRoofError(
                "Свес: смещения соседних скатов почти противоположны; невозможно построить единый митровый угол."
            )
        bisector = tuple(value / raw_length for value in raw)
        projection = sum(bisector[k] * u[k] for k in range(3))
        if projection <= 1.0e-5:
            raise SpatialRoofError(
                "Свес: слишком острый пространственный угол для устойчивого митрового сопряжения."
            )
        miter_distance = distance / projection
        if miter_distance > distance * 12.0:
            raise SpatialRoofError(
                "Свес: митровый вылет угла чрезмерно велик; уменьшите свес или измените угол контура."
            )
        miter = tuple(p[k] + bisector[k] * miter_distance for k in range(3))
        corner_miters[vertex_id] = add_vertex(miter)

    # One quad per edge strip. Adjacent strips share the original-corner
    # -> miter edge; keeping the strip as a quad avoids a diagonal spoke from
    # the corner to the neighbouring miter point.
    for a, b in edge_records:
        ma = corner_miters[a]
        mb = corner_miters[b]
        quad = (b, a, ma, mb)
        if len(set(quad)) < 4:
            raise SpatialRoofError("Свес: митровая полоса схлопнулась в вырожденный четырёхугольник.")
        normal = _face_unit_normal(out_vertices, quad)
        if normal[2] < 0.0:
            quad = tuple(reversed(quad))
            normal = _face_unit_normal(out_vertices, quad)
        if normal[2] <= eps:
            raise SpatialRoofError(
                "Свес: митровая полоса выродилась или перевернулась у угла карниза."
            )
        out_faces.append(quad)
        out_sources.append(-1)

    verify = defaultdict(int)
    for face in out_faces:
        for a, b in zip(face, face[1:] + face[:1]):
            verify[tuple(sorted((a, b)))] += 1
    if any(count > 2 for count in verify.values()):
        raise SpatialRoofError("Пространственный свес создал неманифолдное соединение.")
    if not any(count == 1 for count in verify.values()):
        raise SpatialRoofError("После свеса не осталось внешней границы кровли.")
    return out_vertices, out_faces, out_sources