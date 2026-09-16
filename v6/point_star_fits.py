"""Validated ZPN export and DS9 overlays for a fixed v4 Barghini solution.

The FITS is self-contained. Native REGION gives basic geometry; DS9TEXT retains
UTF-8 labels and styling that DS9's FITS-region importer cannot represent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

import numpy as np
from numpy.polynomial import Chebyshev, Polynomial
from astropy.io import fits
from astropy.wcs import WCS
from PIL import Image

from barghini_model import radial_u, radial_du_dr
from point_star_barghini import BarghiniCamera, vectors
from point_star_names import plot_label

LIMIT_PX = .05
VIEWPORT_PX = 700


def sky_degrees(rays):
    return np.c_[np.rad2deg(np.arctan2(rays[:, 1], rays[:, 0])) % 360,
                 np.rad2deg(np.arctan2(rays[:, 2], np.hypot(rays[:, 0], rays[:, 1])))]


def validated_header(camera):
    """Fit only the inverse radial mapping; independently verify the whole detector."""
    q = camera.physical
    h, w = camera.shape
    corners = np.array([[0, 0], [w-1, 0], [0, h-1], [w-1, h-1]])
    rmax = np.linalg.norm(corners - [q.x_o, q.y_o], axis=1).max()
    radii = np.linspace(0., rmax, 1025)
    angles = radial_u(radii, q.v, q.s, q.d)
    if not (np.isfinite(angles).all() and np.all(radial_du_dr(radii, q.v, q.s, q.d) > 0)
            and 0 < angles[-1] < np.pi):
        raise ValueError('Whole-detector radial domain is not invertible within 180 degrees')
    scale = q.v + q.s*q.d
    g = np.empty_like(angles)
    g[0] = -q.s*q.d*q.d/(2*scale*scale)
    g[1:] = (scale*radii[1:] - angles[1:])/angles[1:]**2
    rays = camera.to_sky([[q.x_o, q.y_o], [q.x_o+1, q.y_o], [q.x_o, q.y_o+1]])
    axis = rays[0]/np.linalg.norm(rays[0])
    tangent = rays[1:] - (rays[1:] @ axis)[:, None]*axis
    tangent /= np.linalg.norm(tangent, axis=1)[:, None]
    centre = sky_degrees(axis[None, :])[0]
    ra, dec = np.deg2rad(centre)
    east = [-np.sin(ra), np.cos(ra), 0.]
    north = [-np.sin(dec)*np.cos(ra), -np.sin(dec)*np.sin(ra), np.cos(dec)]
    cd = np.rad2deg(scale)*np.array([east, north]) @ tangent.T
    gx, gy = np.meshgrid(np.linspace(0, w-1, 137), np.linspace(0, h-1, 131))
    edge_x, edge_y = np.linspace(0, w-1, 1027), np.linspace(0, h-1, 1027)
    xy = np.vstack([np.c_[gx.ravel(), gy.ravel()], np.c_[edge_x, edge_x*0],
                    np.c_[edge_x, edge_x*0+h-1], np.c_[edge_y*0, edge_y],
                    np.c_[edge_y*0+w-1, edge_y], [[q.x_o, q.y_o], [q.x_z, q.y_z]]])
    truth = sky_degrees(camera.to_sky(xy))
    check_r = np.linspace(0, rmax, 100003)
    check_u = radial_u(check_r, q.v, q.s, q.d)
    attempts = []
    for order in (3, 5, 7, 9, 11, 13, 15, 17):
        coeff = np.r_[0., 1., Chebyshev.fit(angles, g, order-2).convert(kind=Polynomial).coef]
        poly = Polynomial(coeff)
        roots = poly.deriv(2).roots()
        roots = roots[np.isreal(roots)].real
        critical = np.r_[0., roots[(roots > 0) & (roots < angles[-1])], angles[-1]]
        if np.min(poly.deriv()(critical)) <= 0:
            attempts.append({'order': order, 'reason': 'nonmonotonic approximation'})
            continue
        wcs = WCS(naxis=2)
        wcs.wcs.ctype = ['RA---ZPN', 'DEC--ZPN']
        wcs.wcs.cunit = ['deg', 'deg']
        wcs.wcs.crpix = [q.x_o+1, q.y_o+1]
        wcs.wcs.crval = centre
        wcs.wcs.cd = cd
        wcs.wcs.radesys = 'ICRS'
        wcs.wcs.lonpole = 180.
        wcs.wcs.set_pv([(2, i, float(c)) for i, c in enumerate(coeff)])
        # Verify the serialized header, not merely the polynomial.
        header = fits.Header.fromstring(wcs.to_header(relax=True).tostring())
        exported = WCS(header)
        world = exported.all_pix2world(xy, 0)
        if not np.isfinite(world).all():
            attempts.append({'order': order, 'maximum_error_px': None,
                             'reason': 'nonfinite pixel-to-world validation result'})
            continue
        truth_pixels = exported.all_world2pix(truth, 0)
        roundtrip_pixels = exported.all_world2pix(world, 0)
        if not (np.isfinite(truth_pixels).all() and np.isfinite(roundtrip_pixels).all()):
            attempts.append({'order': order, 'maximum_error_px': None,
                             'reason': 'nonfinite world-to-pixel validation result'})
            continue
        errors = np.r_[np.linalg.norm(camera.project(vectors(world[:, 0], world[:, 1]))-xy, axis=1),
                       np.linalg.norm(truth_pixels-xy, axis=1),
                       np.linalg.norm(roundtrip_pixels-xy, axis=1),
                       np.abs(poly(check_u)/scale-check_r)]
        maximum = float(np.max(errors)) if np.isfinite(errors).all() else None
        attempts.append({'order': order, 'maximum_error_px': maximum})
        if maximum is not None and maximum < LIMIT_PX:
            header['WCSNAME'] = 'Fixed Barghini solution approximated by ZPN'
            header['ZPNORDER'] = order
            header['ZPNERR'] = (maximum, 'Maximum added error on validation samples, px')
            header['ZPNLIM'] = (LIMIT_PX, 'Required maximum added error, px')
            header['ZPNRMAX'] = float(rmax)
            header['HISTORY'] = 'Original decoded pixels; no resampling or astrometric refit.'
            return header, dict(order=order, maximum_error_px=maximum, threshold_px=LIMIT_PX,
                validation_positions=len(xy), radial_checks=len(check_r), attempts=attempts,
                domain='whole detector rectangle including edges',
                limitation='Dense finite validation, not a continuum proof or total astrometric error')
    raise ValueError('No ZPN order through 17 passed the 0.05-pixel export error limit')


def collect_overlays(output, camera, science):
    path = output/'labelled_stars.json'
    stars = json.loads(path.read_text()).get('stars', [])[:24] if path.is_file() else []
    rows = [dict(x=float(s['x_px']), y=float(s['y_px']), label=plot_label(s) or '', kind='star') for s in stars]
    planets = science.get('planets') or {}
    for kind, group, xkey, ykey in [
        ('matched_planet', 'matches', 'measured_x_px', 'measured_y_px'),
        ('predicted_planet', 'predicted_planets', 'predicted_x_px', 'predicted_y_px')]:
        for p in planets.get(group) or []:
            label = p['planet'] + (' (predicted)' if kind == 'predicted_planet' else
                    (' (candidate)' if planets.get('status') in ('planet_epoch_ambiguous', 'conditional_planet_epoch') else ''))
            rows.append(dict(x=float(p[xkey]), y=float(p[ykey]), label=label, kind=kind))
    zenith = (science.get('photometry') or {}).get('photometric_zenith') or {}
    vector = zenith.get('zenith_unit_vector')
    if vector is not None:
        ray = np.asarray(vector, dtype=float)
        if ray.shape == (3,) and np.isfinite(ray).all() and np.linalg.norm(ray) > 0:
            x, y = camera.project([ray/np.linalg.norm(ray)])[0]
            provisional = zenith.get('status') != 'conditional_zenith' or zenith.get('provisional', False)
            rows.append(dict(x=float(x), y=float(y), kind='zenith',
                             label='Zenith ('+('provisional' if provisional else 'conditional')+')'))
    h, w = camera.shape
    return [r for r in rows if np.isfinite([r['x'],r['y']]).all()
            and -.5 <= r['x'] < w-.5 and -.5 <= r['y'] < h-.5]


def layout_labels(rows, shape):
    """Deterministic box avoidance at a 700-pixel display size; anchors never move.

    DS9 does not reflow labels after zooming. Saved offsets target the initial
    fit-to-window view; each label also has a leader to its exact source.
    """
    from matplotlib.backends.backend_agg import RendererAgg
    from matplotlib.font_manager import FontProperties
    renderer = RendererAgg(VIEWPORT_PX, VIEWPORT_PX, 72)
    font = FontProperties(family='Liberation Sans', size=13)
    h, w = shape
    unit = max(shape)/VIEWPORT_PX
    occupied = []
    placed = []
    for row in rows:
        if not row['label']:
            continue
        tw, th, _ = renderer.get_text_width_height_descent(row['label'], font, False)
        bw, bh = (tw+10)*unit, max(18, th+8)*unit
        x, y = row['x'], row['y']
        candidates = []
        for distance in (18, 35, 55, 80, 115, 165, 230, 320, 440, 600):
            for angle in (-np.pi/4, np.pi/4, -3*np.pi/4, 3*np.pi/4, 0., np.pi, -np.pi/2, np.pi/2):
                cx = np.clip(x+np.cos(angle)*(distance*unit+bw/2), bw/2, w-1-bw/2)
                cy = np.clip(y+np.sin(angle)*distance*unit, bh/2, h-1-bh/2)
                box = [cx-bw/2, cy-bh/2, cx+bw/2, cy+bh/2]
                overlap = sum(max(0,min(box[2],b[2])-max(box[0],b[0]))*
                              max(0,min(box[3],b[3])-max(box[1],b[1])) for b in occupied)
                covers = sum(box[0]-8*unit < r['x'] < box[2]+8*unit and
                             box[1]-8*unit < r['y'] < box[3]+8*unit for r in rows)
                candidates.append((overlap+1000*unit*unit*covers, np.hypot(cx-x,cy-y), box, cx, cy))
        score, _, box, cx, cy = min(candidates, key=lambda c:(c[0],c[1]))
        occupied.append(box)
        placed.append(dict(row, label_x=float(cx), label_y=float(cy), bbox=list(map(float,box)),
                           layout_clear=bool(score == 0)))
    return placed


def safe_text(value):
    # Region syntax uses braces; labels are data, never commands.
    return str(value).replace('{','(').replace('}',')').replace('\\','/').replace('\n',' ').replace('\r',' ')


def overlay_products(rows, shape):
    unit = max(shape)/VIEWPORT_PX
    lines = ['# Region file format: DS9 version 4.1',
             'global color=yellow font="helvetica -13 normal roman" select=1 edit=0 move=0 rotate=0 delete=1', 'image']
    native_x, native_y, native_shape, native_r = [], [], [], []
    for row in rows:
        x,y = row['x']+1, row['y']+1
        kind = row['kind']
        colour = 'yellow' if kind == 'star' else ('red' if kind == 'zenith' else 'magenta')
        width = 2 if kind in ('matched_planet','zenith') else 1
        props = f'color={colour} width={width} fill=0 tag={{{kind}}}'
        if kind == 'star':
            radius = 6*unit
            lines.append(f'circle({x:.10f},{y:.10f},{radius:.10f}) # {props}')
            native_x.append([x]*11); native_y.append([y]*11); native_shape.append('CIRCLE'); native_r.append(radius)
        else:
            # An unfilled star polygon is portable in both FITS REGION and DS9 text.
            n=10 if kind != 'zenith' else 12
            if kind == 'zenith':
                vertices = np.array([[-1,-.7],[-.7,-1],[0,-.3],[.7,-1],[1,-.7],[.3,0],
                                     [1,.7],[.7,1],[0,.3],[-.7,1],[-1,.7],[-.3,0]])*9*unit
            else:
                angles = -np.pi/2+np.arange(n)*np.pi/5
                radius = np.where(np.arange(n)%2,5.,12.)*unit
                vertices = np.c_[np.cos(angles)*radius,np.sin(angles)*radius]
            vertices += [x,y]
            lines.append('polygon('+','.join(f'{v:.10f}' for v in vertices.ravel())+f') # {props}')
            native_x.append(vertices[:,0].tolist()); native_y.append(vertices[:,1].tolist())
            native_shape.append('POLYGON'); native_r.append(0.)
    layout = layout_labels(rows,shape)
    for row in layout:
        x,y = row['x']+1,row['y']+1
        lx,ly = row['label_x']+1,row['label_y']+1
        colour = 'yellow' if row['kind']=='star' else ('red' if row['kind']=='zenith' else 'magenta')
        delta = np.array([lx-x,ly-y]); length=np.linalg.norm(delta)
        start = np.array([x,y])+delta/max(length,1e-12)*min(13*unit,length)
        # End at the nearest edge of the text box, not through the letters.
        bw,bh = (row['bbox'][2]-row['bbox'][0])/2,(row['bbox'][3]-row['bbox'][1])/2
        fraction=min(bw/max(abs(delta[0]),1e-12),bh/max(abs(delta[1]),1e-12),1.)
        end=np.array([lx,ly])-delta*fraction
        tag=row['kind']
        lines.append(f'line({start[0]:.10f},{start[1]:.10f},{end[0]:.10f},{end[1]:.10f}) # color={colour} line=0 0 tag={{{tag}}}')
        lines.append(f'text({lx:.10f},{ly:.10f}) # color={colour} text={{{safe_text(row["label"])}}} tag={{{tag}}}')
    size=max([len(v) for v in native_x]+[13])
    def pad(values):
        return np.array([v+[v[0]]*(size-len(v)) for v in values],dtype=float).reshape(-1,size)
    region=fits.BinTableHDU.from_columns([
        fits.Column(name='X',format=f'{size}D',array=pad(native_x)),
        fits.Column(name='Y',format=f'{size}D',array=pad(native_y)),
        fits.Column(name='SHAPE',format='16A',array=native_shape),
        fits.Column(name='R',format='D',array=native_r),
    ],name='REGION')
    region.header['HDUCLASS']='ASC'
    region.header['HDUCLAS1']='REGION'
    return region,'\n'.join(lines)+'\n',layout


def bytes_hdu(text,name):
    return fits.ImageHDU(np.frombuffer(text.encode('utf8'),dtype=np.uint8),name=name)


def archive_previous(target):
    """Preserve older exports without presenting them as the current result."""
    if not target.exists():
        return None
    index = 1
    while True:
        previous = target.with_name(f'{target.stem}.previous-{index}{target.suffix}')
        if not previous.exists():
            target.rename(previous)
            return previous.name
        index += 1


def plain_pixels(pixels):
    """Return a two-dimensional solve-field input without changing geometry."""
    if pixels.ndim == 2:
        return pixels
    values = pixels.astype(float) @ np.array([.2126, .7152, .0722])
    if np.issubdtype(pixels.dtype, np.integer):
        limits = np.iinfo(pixels.dtype)
        values = np.clip(np.rint(values), limits.min, limits.max)
    return values.astype(pixels.dtype)


def write_fits(image_path, output, result, science):
    """Export without modifying the solution or using observation metadata."""
    output=Path(output)
    output.mkdir(parents=True,exist_ok=True)
    target=output/'solution.fits'
    annotated_target=output/'solution_annotated.fits'
    try:
        if not Path(image_path).is_file():
            raise ValueError('Original image unavailable; a rendered overlay is not a substitute')
        source_hash = hashlib.sha256(Path(image_path).read_bytes()).hexdigest()
        if result.get('source_sha256') and source_hash != result['source_sha256']:
            raise ValueError('Original image checksum differs from the saved astrometric input')
        c=result['camera']
        camera=BarghiniCamera(tuple(c['shape']),np.array(c['reference_rotation']),np.array(c['normalised_parameters']))
        with Image.open(image_path) as image:
            if image.mode in ('P','RGBA','LA'):
                raise ValueError('Palette/alpha images require an explicit lossless export policy')
            pixels=np.asarray(image).copy()
            if pixels.dtype == np.bool_:
                pixels = pixels.astype(np.uint8)  # FITS has no Boolean image BITPIX; preserve 0/1 samples.
        if pixels.shape[:2]!=camera.shape or pixels.ndim not in (2,3) or (pixels.ndim==3 and pixels.shape[2]!=3):
            raise ValueError('Original image dimensions or channels do not match the saved camera')
        header,validation=validated_header(camera)
        rows=collect_overlays(output,camera,science)
        region,text,layout=overlay_products(rows,camera.shape)
        rgb=pixels.ndim==3
        compatible=fits.PrimaryHDU(plain_pixels(pixels),header)
        compatible.header['WFSORIG']='RGB' if rgb else 'MONO'
        compatible.header['WFSMODE']='LUMINANCE' if rgb else 'ORIGINAL'
        compatible.header['COMMENT']='2-D primary image for solve-field; overlays are in solution_annotated.fits'
        primary=fits.PrimaryHDU() if rgb else fits.PrimaryHDU(pixels,header)
        primary.header['WFSRGB']=rgb
        primary.header['WFSREG']='DS9TEXT'
        primary.header['COMMENT']='For full labels/styles: v5/view_fits.sh solution_annotated.fits'
        annotated_hdus=[primary]
        if rgb:
            annotated_hdus.extend(fits.ImageHDU(pixels[:,:,i],header,name=n) for i,n in enumerate(('RED','GREEN','BLUE')))
        info=dict(camera=c,source_sha256=source_hash,
                  exporter_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  wcs_validation=validation,overlays=rows,label_layout=layout,
                  plain_file=target.name,plain_pixel_mode='luminance' if rgb else 'original_mono',
                  annotated_file=annotated_target.name,
                  planet_status=(science.get('planets') or {}).get('status'),
                  planet_epoch_tdb=(science.get('planets') or {}).get('best_candidate_epoch_tdb'),
                  pixel_convention='Stored arrays retain input row order; overlay records zero-based; REGION/DS9TEXT one-based',
                  label_layout_viewport_px=VIEWPORT_PX)
        annotated_hdus.extend([region,bytes_hdu(text,'DS9TEXT'),bytes_hdu(json.dumps(info,ensure_ascii=False,sort_keys=True),'WFSINFO')])
        # Atomic publication; a failure never leaves a partially written FITS.
        with tempfile.NamedTemporaryFile(dir=output,suffix='.fits',delete=False) as temp_plain, \
             tempfile.NamedTemporaryFile(dir=output,suffix='.fits',delete=False) as temp_annotated:
            temporary=Path(temp_plain.name)
            annotated_temporary=Path(temp_annotated.name)
        try:
            fits.HDUList([compatible]).writeto(temporary,overwrite=True,checksum=True)
            fits.HDUList(annotated_hdus).writeto(annotated_temporary,overwrite=True,checksum=True)
            previous = archive_previous(target)
            previous_annotated = archive_previous(annotated_target)
            os.replace(annotated_temporary,annotated_target)
            os.replace(temporary,target)
        finally:
            temporary.unlink(missing_ok=True)
            annotated_temporary.unlink(missing_ok=True)
        record=dict(status='exported',file=target.name,annotated_file=annotated_target.name,
                    rgb=rgb,plain_pixel_mode='luminance' if rgb else 'original_mono',
                    overlays=len(rows),**validation)
        if previous: record['previous_file'] = previous
        if previous_annotated: record['previous_annotated_file'] = previous_annotated
    except ValueError as error:
        record=dict(status='unavailable',reason=str(error))
        previous = archive_previous(target)
        previous_annotated = archive_previous(annotated_target)
        if previous: record['previous_file'] = previous
        if previous_annotated: record['previous_annotated_file'] = previous_annotated
    (output/'fits_export.json').write_text(json.dumps(record,indent=2)+'\n')
    return record


def view_fits(path, *, ds9='ds9', extra_args=()):
    """Load the embedded UTF-8 regions; temporary extraction lasts with the viewer."""
    path=Path(path).expanduser().resolve()
    with fits.open(path) as hdus:
        rgb=bool(hdus[0].header.get('WFSRGB',False))
        text=bytes(hdus['DS9TEXT'].data).decode('utf8')
        info=json.loads(bytes(hdus['WFSINFO'].data).decode('utf8'))
        zoom=info['label_layout_viewport_px']/max(info['camera']['shape'])
        title='Wide-field solution'
        if info.get('planet_status'):
            title+=' | Planet epoch: '+info['planet_status'].replace('_',' ')
        if info.get('planet_epoch_tdb'):
            title+=' | '+info['planet_epoch_tdb']+' TDB'
    with tempfile.TemporaryDirectory(prefix='wide-field-ds9-') as folder:
        regions=Path(folder)/'overlay.reg'
        regions.write_text(text,encoding='utf8')
        args=[ds9,'-title',title,'-geometry','1000x950']
        if rgb: args+=['-rgbimage']
        args += [str(path),'-single','-orient','y','-zoom',str(zoom),
                 '-regions','delete','all','-regions','load',str(regions),
                 '-regions','show','yes','-regions','showtext','yes']
        if rgb: args += ['-rgb','close']
        return subprocess.run(args+list(extra_args),check=True).returncode


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    view=sub.add_parser('view',help='Open self-contained FITS with toggleable styled overlays')
    view.add_argument('fits',type=Path)
    export=sub.add_parser('export',help='Export an existing fixed analysis; no refitting')
    export.add_argument('analysis',type=Path)
    export.add_argument('--image',type=Path,help='Original image if its saved path has moved')
    export.add_argument('--output',type=Path,help='Export directory; defaults to the existing analysis')
    args=parser.parse_args()
    if args.command=='view':
        view_fits(args.fits)
    else:
        result=json.loads((args.analysis/'result.json').read_text())
        science=json.loads((args.analysis/'science_summary.json').read_text())
        out=args.output or args.analysis
        if out!=args.analysis:
            out.mkdir(parents=True,exist_ok=True)
            labels=args.analysis/'labelled_stars.json'
            if labels.is_file(): (out/labels.name).write_bytes(labels.read_bytes())
        record=write_fits(args.image or result['source'],out,result,science)
        print(json.dumps(record,indent=2))
        if record['status']!='exported': raise SystemExit(1)


if __name__=='__main__': main()
