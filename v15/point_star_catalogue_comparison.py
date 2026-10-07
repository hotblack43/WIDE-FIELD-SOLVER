"""Same-image catalogue experiment with explicit, paired spatial subsampling."""
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
from point_star_barghini import BarghiniCamera, run
from point_star_epoch import Catalogue, fit_epoch


def spatial_samples(positions, shape, repeats=32, fraction=.8, seed=20260914):
    if repeats < 1 or not 0 < fraction < 1:
        raise ValueError('Need positive repetitions and a retained fraction strictly between zero and one')
    ids = np.array(sorted(positions))
    xy = np.array([positions[int(i)] for i in ids], dtype=float)
    if xy.shape != (len(ids),2) or not len(ids) or not np.isfinite(xy).all():
        raise ValueError('Need finite measured positions')
    centre = (np.array(shape[::-1])-1)/2
    offset = xy-centre
    radial = np.minimum((4*np.linalg.norm(offset,axis=1)/(np.linalg.norm(shape)/2)).astype(int),3)
    sector = np.floor((np.arctan2(offset[:,1],offset[:,0])%(2*np.pi))/(2*np.pi)*8).astype(int)
    blocks = radial*8+sector
    occupied = np.unique(blocks)
    if len(occupied)<2:
        raise ValueError('Need at least two occupied spatial blocks')
    nkeep = min(len(occupied)-1,max(1,int(np.ceil(fraction*len(occupied)))))
    rng = np.random.default_rng(seed)
    samples = []
    for i in range(repeats):
        chosen = np.sort(rng.choice(occupied,nkeep,replace=False))
        samples.append(dict(replicate=i,retained_blocks=chosen.tolist(),
                            detection_ids=ids[np.isin(blocks,chosen)].tolist()))
    return samples


def residual_comparison(tycho, gaia):
    shared = sorted(set(tycho)&set(gaia))
    if not shared:
        return dict(shared_count=0,tycho_shared_rms_px=None,gaia_shared_rms_px=None,
                    shared_rms_difference_px=None)
    a = float(np.sqrt(np.mean([tycho[i]**2 for i in shared])))
    b = float(np.sqrt(np.mean([gaia[i]**2 for i in shared])))
    return dict(shared_count=len(shared),tycho_shared_rms_px=a,gaia_shared_rms_px=b,
                shared_rms_difference_px=b-a)


def summarise_resamples(records):
    valid = [r for r in records if r['status']=='ok']
    def distribution(key):
        values = [r[key] for r in valid if r.get(key) is not None and np.isfinite(r[key])]
        if not values:
            return dict(count=0,median=None,p05=None,p95=None,calibrated_confidence_interval=False)
        p05,median,p95 = np.percentile(values,[5,50,95])
        return dict(count=len(values),median=float(median),p05=float(p05),p95=float(p95),
                    calibrated_confidence_interval=False)
    return dict(requested=len(records),completed=len(valid),failed=len(records)-len(valid),
        both_epochs_conditional=sum(r['tycho_status']==r['gaia_status']=='conditional_epoch' for r in valid),
        epoch_difference_years=distribution('epoch_difference_years'),
        shared_rms_difference_px=distribution('shared_rms_difference_px'),
        limitation='Paired spatial deletion sensitivity, conditional on full-solve associations. Percentiles are not calibrated confidence intervals or independent accuracy estimates.')


def load_solution(folder, catalog_path):
    folder=Path(folder)
    result=json.loads((folder/'result.json').read_text())
    saved=result['camera']
    camera=BarghiniCamera.from_serialised(saved)
    with (folder/'star_coordinates.csv').open() as handle:
        matches=list(csv.DictReader(handle))
    with Path(catalog_path).open() as handle:
        by_id={r['star_id']:r for r in csv.DictReader(handle)}
    ids=np.array([int(r['detection_id']) for r in matches])
    xy=np.array([[float(r['x_px']),float(r['y_px'])] for r in matches])
    catalogue=Catalogue.from_rows([by_id[r['star_id']] for r in matches])
    return dict(result=result,camera=camera,ids=ids,xy=xy,catalogue=catalogue)


def fitted_residuals(data,camera,epoch,indices):
    residual=np.linalg.norm(camera.project(data['catalogue'].subset(indices).at_year(epoch))-data['xy'][indices],axis=1)
    return {int(i):float(r) for i,r in zip(data['ids'][indices],residual)}


def compare(image, tycho_path, gaia_path, output, repeats=32, fraction=.8, seed=20260914):
    output=Path(output)
    if output.exists():
        raise FileExistsError(f'Use a new experiment directory: {output}')
    if repeats < 1 or not 0 < fraction < 1:
        raise ValueError('Invalid resampling configuration')
    output.mkdir(parents=True)
    paths=dict(tycho=Path(tycho_path),gaia=Path(gaia_path))
    datasets={}
    for name,path in paths.items():
        print(f'Independent blind full solve: {name}',flush=True)
        run(image,output/name,path,offline=True,epoch_mode='fit')
        datasets[name]=load_solution(output/name,path)
    a,b=datasets['tycho'],datasets['gaia']
    if a['camera'].shape != b['camera'].shape:
        raise ValueError('Image dimensions differ between solves')
    # Detection is catalog-independent. Assert pixel identity for shared IDs.
    positions={int(i):xy.tolist() for data in datasets.values() for i,xy in zip(data['ids'],data['xy'])}
    amap={int(i):xy for i,xy in zip(a['ids'],a['xy'])}
    for i,xy in zip(b['ids'],b['xy']):
        if int(i) in amap and not np.array_equal(amap[int(i)],xy):
            raise ValueError('Shared detection IDs have different measured centroids')
    summaries={}; residuals={}
    for name,data in datasets.items():
        epoch=data['result']['stellar_epoch']
        residuals[name]=fitted_residuals(data,data['camera'],epoch['applied_epoch_jyear'],np.arange(len(data['ids'])))
        native=sum(r['star_id'].startswith('Gaia DR3 ') for r in data['catalogue'].rows)
        summaries[name]=dict(associations=len(data['ids']),epoch=epoch,
                            fit=data['result']['fit'],camera=data['result']['camera'],
                            gaia_native_associations=native,non_gaia_associations=len(data['ids'])-native)
    full_comparison=residual_comparison(residuals['tycho'],residuals['gaia'])
    with (output/'shared_residuals.csv').open('w',newline='') as handle:
        writer=csv.writer(handle);writer.writerow(['detection_id','tycho_residual_px','gaia_residual_px'])
        writer.writerows((i,residuals['tycho'][i],residuals['gaia'][i]) for i in sorted(set(residuals['tycho'])&set(residuals['gaia'])))
    samples=spatial_samples(positions,a['camera'].shape,repeats,fraction,seed)
    (output/'resampling_membership.json').write_text(json.dumps(samples,indent=2)+'\n')
    records=[]
    for sample in samples:
        record=dict(replicate=sample['replicate'],status='ok',retained_blocks=sample['retained_blocks'])
        fits={}; errors={}
        try:
            for name,data in datasets.items():
                indices=np.flatnonzero(np.isin(data['ids'],sample['detection_ids']))
                camera,_,epoch=fit_epoch(data['camera'],data['xy'][indices],data['catalogue'].subset(indices))
                fits[name]=dict(epoch=epoch,camera=camera.serialise(),fitted_count=len(indices))
                errors[name]=fitted_residuals(data,camera,epoch['applied_epoch_jyear'],indices)
            record.update(fits= fits,tycho_status=fits['tycho']['epoch']['status'],
                          gaia_status=fits['gaia']['epoch']['status'],
                          epoch_difference_years=fits['gaia']['epoch']['applied_epoch_jyear']-fits['tycho']['epoch']['applied_epoch_jyear'],
                          **residual_comparison(errors['tycho'],errors['gaia']))
        except (ValueError,RuntimeError,np.linalg.LinAlgError) as error:
            record.update(status='failed',reason=str(error),fits=fits)
        records.append(record)
        (output/'resampling.json').write_text(json.dumps(records,indent=2)+'\n')
        print(f"Spatial resample {len(records)}/{repeats}: {record['status']}",flush=True)
    summary=dict(image=str(Path(image).resolve()),image_sha256=hashlib.sha256(Path(image).read_bytes()).hexdigest(),
                 catalogue_sha256={k:hashlib.sha256(v.read_bytes()).hexdigest() for k,v in paths.items()},
                 full=summaries,full_shared=full_comparison,resampling=summarise_resamples(records),
                 seed=seed,retained_block_fraction=fraction,
                 metadata_used=False,
                 comparison_scope='Independent full blind solves with the same tetra3 bootstrap database; replacement of refinement/epoch catalogue only.',
                 limitations=['Gaia G<=7.5 and Tycho VT<=7.5 select different populations.',
                              'Gaia includes an explicitly labelled local bright-star supplement.',
                              'Spatial resamples refit camera and epoch on conditional fixed associations; they do not repeat blind bootstrap.',
                              'Refraction, parallax, blending and lens systematics are not resolved by switching catalogue.'])
    (output/'comparison.json').write_text(json.dumps(summary,indent=2)+'\n')
    write_comparison_products(output,summary,records)
    return summary


def write_comparison_products(output,summary,records):
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator
    from point_star_plotting import save_png
    fig,axes=plt.subplots(1,3,figsize=(14,4))
    for name,colour in [('tycho','tab:orange'),('gaia','tab:blue')]:
        epoch=summary['full'][name]['epoch'];profile=epoch['profile']
        axes[0].plot([r['year'] for r in profile],[r['cost']-epoch['minimum_cost'] for r in profile],'.-',label=name,color=colour)
    axes[0].set(xlabel='Trial Julian year',ylabel='Increase in robust astrometric cost',title='Full independent epoch profiles');axes[0].legend()
    valid=[r for r in records if r['status']=='ok']
    for ax,key,title,units in [(axes[1],'epoch_difference_years','Numerical epoch difference','Gaia minus Tycho [years]'),
                               (axes[2],'shared_rms_difference_px','RMS difference on shared detections','Gaia minus Tycho [px]')]:
        values=[r[key] for r in valid if r.get(key) is not None]
        if values: ax.hist(values,bins=min(12,max(3,len(values)//3)),color='tab:blue',alpha=.7)
        ax.axvline(0,color='black',ls=':');ax.set(title=title,xlabel=units,ylabel='Spatial subsamples')
    axes[2].xaxis.set_major_locator(MaxNLocator(5))
    fig.suptitle('Same-image Gaia / Tycho comparison — conditional spatial sensitivity, not independent accuracy')
    fig.tight_layout();save_png(fig,Path(output)/'comparison.png',dpi=160);plt.close(fig)
    lines=['# Gaia / Tycho same-image comparison','',summary['comparison_scope'],'',
           '| Catalogue | Associations | RMS [px] | Epoch [Julian year] | Conditional 95% interval |',
           '|---|---:|---:|---:|---|']
    for name in ('tycho','gaia'):
        item=summary['full'][name];e=item['epoch']
        lines.append(f"| {name} | {item['associations']} | {item['fit']['rms_px']:.6f} | {e['applied_epoch_jyear']:.2f} ({e['status']}) | {e['conditional_interval_95_jyear']} |")
    lines+=['','Shared-detection fit residuals: `'+json.dumps(summary['full_shared'])+'`','',
            'Paired spatial sensitivity (5th–95th percentiles are not confidence intervals):','',
            '```json',json.dumps(summary['resampling'],indent=2),'```','',*['- '+s for s in summary['limitations']]]
    (Path(output)/'comparison.md').write_text('\n'.join(lines)+'\n')
