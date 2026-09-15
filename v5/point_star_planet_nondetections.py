"""Conservative, image-based negative evidence for bright-planet epoch candidates.

This is an explicit consistency screen, not a calibrated likelihood. Only
well-supported blank locations can contradict a candidate; unknown detectability
is neutral. Coordinates and positional fits are never adjusted here.
"""
from __future__ import annotations
import copy
import json
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree
from PIL import Image
from point_star_planet_brightness import BRIGHT_PLANETS, SOURCE, planet_brightness


def _true(value):
    return str(value).lower() == 'true'


class LocalDetectability:
    """Use fainter surrounding catalogue stars as empirical sensitivity witnesses."""
    def __init__(self, pixels, detections, stars, *, gate_px=3., valid_mask=None):
        self.pixels=np.asarray(pixels,dtype=float)
        if self.pixels.ndim==3:
            self.pixels=self.pixels[:,:,:3]@np.array([.2126,.7152,.0722])
        if self.pixels.ndim!=2:
            raise ValueError('Detectability requires monochrome or RGB pixels')
        self.mask=np.isfinite(self.pixels) if valid_mask is None else np.asarray(valid_mask,bool)&np.isfinite(self.pixels)
        if self.mask.shape!=self.pixels.shape:
            raise ValueError('Visibility mask shape differs from image')
        self.gate=float(gate_px)
        self.xy=np.array([[float(r['x_px']),float(r['y_px'])] for r in detections]).reshape(-1,2)
        self.tree=cKDTree(self.xy) if len(self.xy) else None
        lookup={str(r['detection_id']):r for r in detections}
        self.references=[]
        for star in stars:
            detection=lookup.get(str(star['detection_id']))
            if detection is None or _true(detection.get('saturated',False)) or detection.get('source_class')!='compact':
                continue
            try:
                magnitude=float(star['magnitude']); residual=float(star['residual_px'])
                peak=float(detection['peak_above_background']); snr=float(detection['peak_snr'])
                sigma=float(detection['major_sigma_px'])
                point=np.array([float(star['x_px']),float(star['y_px'])])
            except (KeyError,TypeError,ValueError):
                continue
            if not np.isfinite([magnitude,residual,peak,snr,sigma,*point]).all() or residual>1 or snr<8 or peak<=0 or sigma<=0:
                continue
            self.references.append(dict(xy=point,magnitude=magnitude,peak=peak,sigma=sigma,id=int(star['detection_id'])))
        self.radius=max(40.,.05*np.linalg.norm(self.pixels.shape))
        self.sigma=float(np.median([s['sigma'] for s in self.references])) if self.references else 1.
        self.probe_radius=max(2*self.gate,3*self.sigma)
        self.refxy=np.array([s['xy'] for s in self.references]).reshape(-1,2)

    def patch(self,point):
        """Summarise a native-pixel core and surrounding sky; incomplete is unknown."""
        x,y=map(float,point)
        radius=self.probe_radius
        half=int(np.ceil(3*radius))
        ix,iy=int(round(x)),int(round(y))
        h,w=self.pixels.shape
        if ix-half<0 or iy-half<0 or ix+half>=w or iy+half>=h:
            return None
        cut=self.pixels[iy-half:iy+half+1,ix-half:ix+half+1]
        valid=self.mask[iy-half:iy+half+1,ix-half:ix+half+1]
        yy,xx=np.mgrid[-half:half+1,-half:half+1]
        rr=np.hypot(xx+ix-x,yy+iy-y)
        area=rr<=3*radius
        if not valid[area].all():
            return None
        core=rr<=radius
        annulus=(rr>=2*radius)&area
        background=float(np.median(cut[annulus]))
        noise=max(.5,float(1.4826*np.median(abs(cut[annulus]-background))))
        medians=[np.median(cut[annulus&(xx*sx>=0)&(yy*sy>=0)]) for sx,sy in [(1,1),(1,-1),(-1,1),(-1,-1)]]
        return dict(background=background,noise=noise,peak=float(np.max(cut[core])-background),
                    dark_fraction=float(np.mean(cut[area]<=0)),gradient=float(np.ptp(medians)),
                    core_deficit=background-float(np.median(cut[core])))

    def assess(self,name,point,magnitude):
        name=name.lower()
        point=np.asarray(point,float)
        record=dict(planet=name.title(),predicted_x_px=float(point[0]),predicted_y_px=float(point[1]),
                    predicted_v_mag=float(magnitude) if np.isfinite(magnitude) else None,
                    supporting_stars=0,absence_penalty=0)
        def finish(status):
            record['status']=status
            if status=='missing_bright_planet': record['absence_penalty']=1
            return record
        if name not in BRIGHT_PLANETS:
            return finish('not_tested_faint_planet')
        if not np.isfinite(point).all() or not np.isfinite(magnitude):
            return finish('inconclusive_projection_or_brightness')
        distance=float(self.tree.query(point)[0]) if self.tree is not None else None
        record['nearest_detection_px']=distance
        record['probe_radius_px']=self.probe_radius
        if distance is not None and distance<=self.probe_radius:
            return finish('source_present')
        stats=self.patch(point)
        if stats is None:
            return finish('inconclusive_mask_or_edge')
        record.update(local_background_adu=stats['background'],local_noise_adu=stats['noise'],
                      local_peak_above_background_adu=stats['peak'],local_core_deficit_adu=stats['core_deficit'])
        if stats['dark_fraction']>.02 or stats['background']<=0 or stats['gradient']>4*stats['noise'] or stats['core_deficit']>3*stats['noise']:
            return finish('inconclusive_background_or_obstruction')
        if stats['peak']>4*stats['noise']:
            return finish('pixel_signal_present')
        indices=np.flatnonzero(np.linalg.norm(self.refxy-point,axis=1)<=self.radius)
        indices=sorted(indices,key=lambda i:np.linalg.norm(self.refxy[i]-point))[:24]
        witnesses=[]
        for i in indices:
            star=self.references[i]
            # Two magnitude guard for V vs catalogue/camera band and model errors.
            if star['magnitude']<magnitude+2.:
                continue
            refstats=self.patch(star['xy'])
            if refstats is not None and refstats['dark_fraction']<=.02:
                witnesses.append((star,refstats))
        record['supporting_stars']=len(witnesses)
        record['support_radius_px']=self.radius
        record['witness_magnitude_guard']=2.
        if len(witnesses)<5:
            return finish('inconclusive_local_depth')
        delta=np.array([s['xy']-point for s,_ in witnesses])
        angles=np.sort(np.arctan2(delta[:,1],delta[:,0]))
        if np.max(np.diff(np.r_[angles,angles[0]+2*np.pi]))>=np.pi:
            return finish('inconclusive_surrounding_sky')
        backgrounds=np.array([v['background'] for _,v in witnesses])
        refbg=float(np.median(backgrounds))
        refnoise=float(np.median([v['noise'] for _,v in witnesses]))
        spread=float(1.4826*np.median(abs(backgrounds-refbg)))
        if abs(stats['background']-refbg)>max(3*spread,3*refnoise) or stats['background']<.2*refbg:
            return finish('inconclusive_background_or_obstruction')
        reference_peak=float(np.quantile([s['peak'] for s,_ in witnesses],.25))
        required=6*stats['noise']
        record.update(reference_peak_lower_adu=reference_peak,required_peak_adu=required,
                      supporting_detection_ids=[s['id'] for s,_ in witnesses],
                      supporting_catalogue_magnitudes=[s['magnitude'] for s,_ in witnesses])
        if reference_peak<required or stats['peak']>3*stats['noise']:
            return finish('inconclusive_local_depth')
        return finish('missing_bright_planet')


def apply_evidence(answer,evidence_rows):
    """Rank inconsistent candidates below the others, retaining every original fit."""
    out=copy.deepcopy(answer)
    out['predicted_planets']=[]  # Reproject only after selecting the new best epoch.
    candidates=out.get('candidates') or []
    if len(evidence_rows)!=len(candidates):
        raise ValueError('Evidence must cover every positional candidate')
    original_status=out.get('status')
    for rank,(candidate,rows) in enumerate(zip(candidates,evidence_rows),1):
        candidate['positional_rank']=rank
        candidate['non_detection_evidence']=rows
        candidate['missing_bright_planets']=[r['planet'] for r in rows if r['status']=='missing_bright_planet']
        candidate['absence_penalty']=len(candidate['missing_bright_planets'])
    candidates.sort(key=lambda c:(bool(c['absence_penalty']),c['absence_penalty'],-c['match_count'],c['cost_px2'],c['jd_tdb']))
    out['negative_evidence']=dict(method='conservative bright-planet consistency screen',
        brightness_model=SOURCE,assessed_planets=list(BRIGHT_PLANETS),
        faint_planets_not_penalised=['uranus','neptune'],
        contradicted_candidates=sum(c['absence_penalty']>0 for c in candidates),
        ranking='uncontradicted first, missing bright count, matched count descending, positional cost',
        limitation='Heuristic, not calibrated odds; local star/background support is not a complete cloud or obstruction mask.')
    if not candidates:
        return out
    best=candidates[0]
    if best['absence_penalty']:
        out.update(status='planet_epoch_inconsistent',confidence='all_candidates_contradicted',matches=[],match_count=0,
            best_candidate_jd_tdb=None,best_candidate_epoch_tdb=None,rms_px=None,conditional_time_sigma_minutes=None,
            competing_candidates=0,reason='All positional candidates predict an absent bright planet in locally supported sky')
        return out
    sigma=out.get('positional_sigma_px',.5)
    peers=[c for c in candidates if not c['absence_penalty'] and c['match_count']==best['match_count']
           and c['cost_px2']<=best['cost_px2']+9*sigma*sigma]
    # Negative evidence must not turn an already ambiguous search into a claimed date.
    ambiguous=(original_status=='planet_epoch_ambiguous' or best['match_count']<2 or len(peers)>1
               or best.get('boundary_limited',False)
               or min((m.get('predicted_altitude_deg',90.) for m in best['matches']),default=0.)<.01
               or (out.get('visibility') or {}).get('zenith_status')!='conditional_zenith')
    out.update(status='planet_epoch_ambiguous' if ambiguous else 'conditional_planet_epoch',
        confidence='ambiguous_candidates_with_absence_checks' if ambiguous else 'conditional_multiple_planets',
        matches=best['matches'],match_count=best['match_count'],best_candidate_jd_tdb=best['jd_tdb'],
        best_candidate_epoch_tdb=best['epoch_tdb'],rms_px=best['rms_px'],
        conditional_time_sigma_minutes=best.get('conditional_time_sigma_minutes'),competing_candidates=len(peers)-1,
        reason='Candidates ranked with bright-planet absence checks; remaining dates and identities are conditional')
    return out


def check_candidate_absences(image_path,answer,camera,detections,stars,vector_function,*,magnitude_function=planet_brightness,valid_mask=None):
    """Evaluate all saved positional trials at their own epoch before final selection."""
    from point_star_planets import _visible_projection
    candidates=answer.get('candidates') or []
    if not candidates:
        return apply_evidence(answer,[])
    with Image.open(image_path) as image:
        pixels=np.asarray(image.convert('RGB'),dtype=float)
    if tuple(pixels.shape[:2])!=tuple(camera.shape):
        raise ValueError('Image shape differs from the fixed camera')
    local=LocalDetectability(pixels,detections,stars,gate_px=answer.get('gate_px',3.),valid_mask=valid_mask)
    dates=np.array([c['jd_tdb'] for c in candidates])
    zenith=np.asarray(answer['visibility']['zenith_unit_vector'],float)
    zenith/=np.linalg.norm(zenith)
    evidence=[[] for _ in candidates]
    for name in answer.get('searched_planets',[]):
        name=name.lower()
        if name not in BRIGHT_PLANETS:
            for rows in evidence:
                rows.append(dict(planet=name.title(),status='not_tested_faint_planet',absence_penalty=0))
            continue
        points=_visible_projection(camera,vector_function(name,dates),zenith)
        magnitudes=magnitude_function(name,dates)
        for i,candidate in enumerate(candidates):
            if name in {m['planet'].lower() for m in candidate['matches']}:
                row=dict(planet=name.title(),status='matched',absence_penalty=0)
            elif not np.isfinite(points[i]).all():
                row=dict(planet=name.title(),status='outside_visible_image',absence_penalty=0)
            else:
                row=local.assess(name,points[i],magnitudes[i])
            evidence[i].append(row)
    return apply_evidence(answer,evidence)


def write_evidence(output,answer):
    record=dict(summary=answer.get('negative_evidence'),candidates=[dict(
        rank=i,positional_rank=c['positional_rank'],epoch_tdb=c['epoch_tdb'],
        missing_bright_planets=c['missing_bright_planets'],evidence=c['non_detection_evidence'])
        for i,c in enumerate(answer.get('candidates',[]),1)])
    (Path(output)/'planet_non_detections.json').write_text(json.dumps(record,indent=2,allow_nan=False)+'\n')
