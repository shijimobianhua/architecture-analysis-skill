"""Small, opt-in map acquisition helper. No AI, tile crawling or implicit CRS conversion.

Python 3.10+, Pillow. Credentials are read from environment, never saved in records.
Run --help; workflow and licensing notes are in references/location-sources.md.
"""
import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError
from PIL import Image

SCHEMA = '1.0'  # Sidecar only; existing order/layer/experience schema stays 2.0.
RADIUS = 6378137.0


class MapError(ValueError):
    pass


def need(condition, message):
    if not condition:
        raise MapError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    path = Path(path)
    need(not path.exists(), 'Output exists; reuse it or choose a new version directory.')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fingerprint(value):
    return digest(json.dumps(value, sort_keys=True, ensure_ascii=False).encode('utf8'))


def now():
    return datetime.now(timezone.utc).isoformat()


def coords(x, y, crs):
    x, y = float(x), float(y)
    need(math.isfinite(x) and math.isfinite(y), 'Coordinates must be finite.')
    need(crs in ('WGS84', 'GCJ02', 'BD09', 'EPSG:3857'), 'Unknown CRS; identify its source first.')
    if crs == 'EPSG:3857':
        need(abs(x) <= 20037508.35 and abs(y) <= 20037508.35, 'Mercator coordinates outside supported extent.')
    else:
        need(-180 <= x <= 180 and -85.05112878 <= y <= 85.05112878,
             'Longitude/latitude outside supported map range; order is longitude, latitude.')
    return [x, y]


def mercator(x, y):
    coords(x, y, 'WGS84')
    return [RADIUS * math.radians(x), RADIUS * math.log(math.tan(math.pi / 4 + math.radians(y) / 2))]


def service_url(url):
    p = urlsplit(url)
    need(p.scheme == 'https' and p.hostname and not p.username and not p.password
         and not p.query and not p.fragment, 'Service must be an HTTPS URL without credentials/query/fragment.')
    need(p.path.rstrip('/').endswith('/MapServer'), 'Expected an ArcGIS MapServer URL.')
    return url.rstrip('/')


class SameHostRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urlsplit(req.full_url), urlsplit(newurl)
        need(new.scheme == 'https' and new.netloc == old.netloc, 'Cross-host redirect blocked.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Transport:
    """At most 30 seconds across requests in one invocation; no automatic retries."""
    def __init__(self):
        self.deadline = time.monotonic() + 30
        self.opener = build_opener(SameHostRedirect())

    def get(self, url, params=None, binary=False):
        remaining = self.deadline - time.monotonic()
        need(remaining > 0, 'Acquisition time budget exhausted; use the documented fallback.')
        if params:
            url += '?' + urlencode(params)
        request = Request(url, headers={'User-Agent': 'ArchitectureAnalysis/3.0 map-source',
                                       'Accept': 'image/*,application/json' if binary else 'application/json'})
        try:
            with self.opener.open(request, timeout=min(10, remaining)) as response:
                cap = 30_000_000 if binary else 3_000_000
                data = response.read(cap + 1)
                need(len(data) <= cap, 'Response too large; request a smaller map.')
        except HTTPError as exc:
            raise MapError('Map service HTTP error %s; no automatic retry.' % exc.code) from None
        except MapError:
            raise
        except Exception as exc:
            # Exception URLs/bodies may contain credentials. Never echo them.
            raise MapError('Map request failed (%s); use the documented fallback.' % type(exc).__name__) from None
        if binary:
            return data
        try:
            result = json.loads(data)
        except (ValueError, UnicodeError):
            raise MapError('Map service returned invalid JSON.') from None
        need(isinstance(result, dict), 'Unexpected map service response.')
        need(not result.get('error'), 'Map service rejected the request; check access and configuration.')
        return result


def key_from(env):
    key = os.environ.get(env, '').strip()
    need(bool(key), 'Missing credential environment variable: ' + env + '; use a verified page or supplied map.')
    return key


def amap_call(path, params, env, transport):
    result = transport.get('https://restapi.amap.com/v3/' + path, params | {'key': key_from(env)})
    need(result.get('status') == '1', 'AMap rejected the request; check key, quota and API permissions.')
    return result


def geocode(address, city, key_env, transport):
    need(bool(address.strip()) and bool(city.strip()), 'Provide address and city to disambiguate the search.')
    result = amap_call('geocode/geo', {'address': address, 'city': city}, key_env, transport)
    candidates = []
    for item in result.get('geocodes', []):
        try:
            point = coords(*map(float, item['location'].split(',')), 'GCJ02')
        except (KeyError, TypeError, ValueError):
            continue
        candidates.append({'label': item.get('formatted_address'), 'coordinates': point, 'crs': 'GCJ02',
                           'level': item.get('level'), 'adcode': item.get('adcode')})
    return {'schema_version': SCHEMA, 'provider': 'amap', 'query': {'address': address, 'city': city},
            'retrieved_at': now(), 'candidates': candidates, 'selection': None,
            'status': 'needs_location_check' if candidates else 'not_found',
            'source': 'https://restapi.amap.com/v3/geocode/geo',
            'note': 'Candidate point is not a project boundary or independently verified site.'}


def point_record(x, y, crs, label, evidence):
    need(bool(label.strip()) and bool(evidence.strip()), 'Record label and material/page/control-point evidence.')
    return {'schema_version': SCHEMA, 'label': label, 'coordinates': coords(x, y, crs), 'crs': crs,
            'evidence': evidence, 'status': 'provided_or_cross_checked', 'project_boundary': None}


def convert_point(point, key_env, transport):
    source = point['crs']
    need(source in ('WGS84', 'BD09'), 'AMap conversion supports explicitly identified WGS84 or BD09 here.')
    x, y = coords(*point['coordinates'], source)
    result = amap_call('assistant/coordinate/convert', {'locations': f'{x},{y}',
                        'coordsys': 'gps' if source == 'WGS84' else 'baidu'}, key_env, transport)
    try:
        target = coords(*map(float, result['locations'].split(',')), 'GCJ02')
    except (KeyError, TypeError, ValueError):
        raise MapError('Invalid coordinate conversion response.') from None
    return point | {'coordinates': target, 'crs': 'GCJ02', 'conversion': {
        'provider': 'amap', 'source_crs': source, 'source_coordinates': [x, y], 'retrieved_at': now()}}


def size_check(width, height, maximum=4096):
    need(isinstance(width, int) and isinstance(height, int) and 1 <= width <= maximum
         and 1 <= height <= maximum, 'Invalid image size or service maximum exceeded.')


def cached(out, request):
    out = Path(out)
    if not out.exists():
        return None
    need((out/'map.json').is_file(), 'Existing incomplete output; choose a new version directory.')
    record = read(out/'map.json')
    need(record['request_fingerprint'] == fingerprint(request), 'Output request differs; choose a new version directory.')
    image = out/'basemap.png'
    need(image.is_file() and digest(image.read_bytes()) == record['image_sha256'], 'Cached image hash mismatch.')
    return record


def save_map(out, image_bytes, record, request):
    try:
        im = Image.open(io.BytesIO(image_bytes))
        need(im.format in ('PNG', 'JPEG'), 'Expected a PNG/JPEG map, not a service error or another file.')
        size_check(*im.size)
        need(list(im.size) == record['size'], 'Returned map size differs from its coordinate record.')
        im.load()
        original_format = im.format
        image = im.convert('RGBA' if 'A' in im.getbands() else 'RGB')
    except MapError:
        raise
    except Exception:
        raise MapError('Map response is not a valid supported raster image.') from None
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    if original_format == 'PNG':
        (out/'basemap.png').write_bytes(image_bytes)  # Preserve source pixels/alpha without re-encoding.
    else:
        (out/'source.jpg').write_bytes(image_bytes)
        image.save(out/'basemap.png')  # Lossless decoded JPEG pixels; keep the original too.
    record |= {'schema_version': SCHEMA, 'retrieved_at': now(), 'capture_date': None,
               'request': request, 'request_fingerprint': fingerprint(request),
               'image': 'basemap.png', 'image_sha256': digest((out/'basemap.png').read_bytes()),
               'raw_source': 'basemap.png' if original_format == 'PNG' else 'source.jpg',
               'raw_source_sha256': digest(image_bytes),
               'geometry_check': 'pending_control_points', 'project_boundary': None,
               'commercial_rights': 'not_verified_by_tool', 'cost': None}
    write(out/'map.json', record)
    return record


def amap_map(point, zoom, width, height, scale, key_env, usage_note, out, transport):
    need(point['crs'] == 'GCJ02', 'CRS mismatch: AMap needs GCJ02; convert explicitly first.')
    x, y = coords(*point['coordinates'], 'GCJ02')
    size_check(width, height, 1024)
    need(isinstance(zoom, int) and 1 <= zoom <= 17 and scale in (1, 2), 'Invalid zoom or scale.')
    need(bool(usage_note.strip()), 'Record intended use/source permission basis; tool does not grant rights.')
    request = {'provider': 'amap', 'kind': 'map', 'center': [x,y], 'zoom': zoom,
               'size': [width,height], 'scale': scale, 'usage_note': usage_note}
    old = cached(out, request)
    if old: return old
    data = transport.get('https://restapi.amap.com/v3/staticmap', {
        'location': f'{x},{y}', 'zoom': zoom, 'size': f'{width}*{height}', 'scale': scale,
        'traffic': 0, 'key': key_from(key_env)}, binary=True)
    cx, cy = mercator(x, y)
    units = 2 * math.pi * RADIUS / (256 * 2**zoom)
    return save_map(out, data, {'provider': 'amap', 'kind': 'map', 'size': [width*scale,height*scale],
        'coordinate_crs': 'GCJ02', 'extent_crs': 'GCJ02:WebMercator',
        'extent': [cx-width*units/2, cy-height*units/2, cx+width*units/2, cy+height*units/2],
        'extent_basis': 'standard_web_mercator_zoom; validate noncentral control points before use',
        'source': 'https://restapi.amap.com/v3/staticmap', 'attribution': '© 高德地图',
        'usage_note': usage_note}, request)


def arcgis_map(service, bbox, bbox_crs, width, height, kind, attribution, usage_note, token_env, out, transport):
    service = service_url(service)
    need(bbox_crs in ('WGS84', 'EPSG:3857'), 'ArcGIS input supports WGS84 or EPSG:3857; never relabel GCJ02.')
    size_check(width, height)
    need(kind in ('map', 'satellite') and bool(attribution.strip()) and bool(usage_note.strip()),
         'Specify kind, attribution and intended use/source permission basis.')
    xmin,ymin = coords(*bbox[:2], bbox_crs)
    xmax,ymax = coords(*bbox[2:], bbox_crs)
    need(xmax > xmin and ymax > ymin, 'Invalid bbox; antimeridian crossing requires a separate GIS workflow.')
    request = {'provider': 'arcgis', 'service': service, 'bbox': [xmin,ymin,xmax,ymax], 'bbox_crs': bbox_crs,
               'size': [width,height], 'kind':kind, 'attribution':attribution, 'usage_note':usage_note}
    old = cached(out, request)
    if old: return old
    auth = {'token':key_from(token_env)} if token_env else {}
    meta = transport.get(service, {'f':'json'} | auth)
    need('Map' in meta.get('capabilities', '').split(','), 'Service does not expose map export capability.')
    need(width <= meta.get('maxImageWidth',4096) and height <= meta.get('maxImageHeight',4096),
         'Requested image exceeds this service limit; reduce it, do not crawl tiles.')
    exported = transport.get(service+'/export', {'f':'json', 'bbox':','.join(map(str,bbox)),
        'bboxSR':4326 if bbox_crs == 'WGS84' else 3857, 'imageSR':3857, 'size':f'{width},{height}',
        'format':'png32', 'transparent':'false', 'dpi':96} | auth)
    need(isinstance(exported.get('width'), int) and isinstance(exported.get('height'), int)
         and exported['width'] > 0 and exported['height'] > 0 and exported.get('href'),
         'Service returned no usable map image; use one permitted fallback or a supplied map.')
    ext = exported.get('extent', {})
    wkid = ext.get('spatialReference', {}).get('latestWkid', ext.get('spatialReference', {}).get('wkid'))
    need(wkid in (3857,102100,102113), 'Unexpected export CRS; cannot align this map automatically.')
    try:
        extent = [float(ext[k]) for k in ('xmin','ymin','xmax','ymax')]
    except (KeyError, ValueError, TypeError):
        raise MapError('Missing/invalid returned extent.') from None
    need(all(math.isfinite(n) for n in extent) and extent[2] > extent[0] and extent[3] > extent[1],
         'Invalid returned extent.')
    href = exported.get('href','')
    parsed = urlsplit(href)
    need(parsed.scheme == 'https' and parsed.netloc == urlsplit(service).netloc
         and not parsed.username and not parsed.password and not parsed.fragment, 'Export image must remain on the service host.')
    data = transport.get(href, binary=True)
    return save_map(out, data, {'provider':'arcgis', 'kind':kind,
        'size':[exported.get('width'),exported.get('height')], 'extent':extent, 'extent_crs':'EPSG:3857',
        'coordinate_crs':'WGS84', 'extent_basis':'server_returned_extent', 'source':service,
        'attribution':attribution, 'service_copyright':meta.get('copyrightText'),
        'usage_note':usage_note}, request)


def project(record, points, box):
    """Map geographic points into an unrotated, uncropped final-canvas image box."""
    need(len(box) == 4 and all(math.isfinite(n) for n in box), 'Box must be x,y,width,height.')
    left,top,width,height = box
    need(min(left,top) >= 0 and min(width,height) > 0, 'Invalid placement box.')
    sourcew,sourceh = record['size']
    need(abs(width/height-sourcew/sourceh) <= (sourcew/sourceh)*0.001,
         'Placement aspect differs; do not stretch or silently crop a map.')
    xmin,ymin,xmax,ymax = record['extent']
    output = []
    for p in points:
        need(p['crs'] == record['coordinate_crs'], 'Point/map CRS mismatch; explicit conversion required.')
        x,y = coords(*p['coordinates'], p['crs'])
        x,y = mercator(x,y)
        u,v = (x-xmin)/(xmax-xmin), (ymax-y)/(ymax-ymin)
        need(-1e-8 <= u <= 1+1e-8 and -1e-8 <= v <= 1+1e-8, 'Point outside map extent; revise scope or omit with explanation.')
        output.append({'label':p['label'], 'xy':[left+u*width,top+v*height]})
    return {'schema_version':SCHEMA,'box':box,'points':output,
            'geometry_check':record['geometry_check'], 'note':'Pixel placement is not independent location verification.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    g = sub.add_parser('geocode', help='AMap address candidates; never auto-select')
    g.add_argument('--address', required=True); g.add_argument('--city', required=True)
    p = sub.add_parser('point', help='Record supplied or cross-checked point with evidence')
    p.add_argument('--lon', type=float, required=True); p.add_argument('--lat', type=float, required=True)
    p.add_argument('--crs', choices=['WGS84','GCJ02','BD09'], required=True)
    p.add_argument('--label', required=True); p.add_argument('--evidence', required=True)
    c = sub.add_parser('convert', help='Explicit WGS84/BD09 to GCJ02 via AMap')
    c.add_argument('--point', required=True)
    a = sub.add_parser('amap', help='AMap static street map, not a satellite endpoint')
    a.add_argument('--point', required=True); a.add_argument('--zoom', type=int, required=True)
    a.add_argument('--scale', type=int, default=1, choices=[1,2])
    r = sub.add_parser('arcgis', help='Export from an available, permitted map/satellite MapServer')
    r.add_argument('--service', required=True); r.add_argument('--bbox', nargs=4, type=float, required=True)
    r.add_argument('--bbox-crs', choices=['WGS84','EPSG:3857'], required=True)
    r.add_argument('--kind', choices=['map','satellite'], required=True)
    r.add_argument('--attribution', required=True); r.add_argument('--token-env')
    for cmd in [a,r]:
        cmd.add_argument('--width',type=int,required=True); cmd.add_argument('--height',type=int,required=True)
        cmd.add_argument('--usage-note',required=True)
    for cmd in [g,c,a]: cmd.add_argument('--key-env',default='AMAP_WEB_KEY')
    q = sub.add_parser('project', help='Shared geographic-to-canvas coordinates')
    q.add_argument('--map',required=True); q.add_argument('--points',required=True)
    q.add_argument('--box',nargs=4,type=float,required=True)
    for cmd in [g,p,c,a,r,q]: cmd.add_argument('--out',required=True)
    args = parser.parse_args(argv)
    transport = Transport()
    try:
        if args.command in ('geocode','point','convert','project'):
            need(not Path(args.out).exists(), 'Output exists; reuse it or choose a new version file.')
        if args.command == 'geocode': result = geocode(args.address,args.city,args.key_env,transport)
        elif args.command == 'point': result = point_record(args.lon,args.lat,args.crs,args.label,args.evidence)
        elif args.command == 'convert': result = convert_point(read(args.point),args.key_env,transport)
        elif args.command == 'amap':
            result = amap_map(read(args.point),args.zoom,args.width,args.height,args.scale,args.key_env,args.usage_note,args.out,transport)
        elif args.command == 'arcgis':
            result = arcgis_map(args.service,args.bbox,args.bbox_crs,args.width,args.height,args.kind,
                                args.attribution,args.usage_note,args.token_env,args.out,transport)
        else: result = project(read(args.map),read(args.points),args.box)
        if args.command not in ('amap','arcgis'): write(args.out,result)
        print(json.dumps({'status':'saved_or_reused','output':args.out,
                          'geometry_check':result.get('geometry_check'), 'cost':None},ensure_ascii=False))
        return 0
    except (MapError, KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
        # Only controlled messages may be emitted; other exceptions may include local paths/secrets.
        print(str(exc) if isinstance(exc, MapError) else 'Invalid input or local file error; inspect inputs.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
