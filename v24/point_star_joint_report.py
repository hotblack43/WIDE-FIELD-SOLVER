"""Visible audit of what the common-camera planet fit actually changed."""
from pathlib import Path
import textwrap
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from astropy.time import Time
from point_star_image import load_recorded_image


def joint_figure(output, result, science):
    joint = science.get('joint_epoch') or result['joint_epoch']
    index = joint.get('best_index')
    best = joint['candidates'][index] if index is not None else None
    if best:
        from point_star_joint_epoch import interval_boundary_record
        boundary = interval_boundary_record(best['interval_95_jd_tdb'], best['search_limits_jd_tdb'],
                                             joint['supported_search_jd_tdb'])
    fig = plt.figure(figsize=(12, 12.8))
    grid = fig.add_gridspec(5, 4, height_ratios=[1.05, 1., 1., .15, .78],
                          left=.06, right=.97, top=.86, bottom=.025, hspace=.55, wspace=.45)
    fig.suptitle('V11: joint epoch fit — stars + planets', fontsize=17, weight='bold', y=.98)
    if best:
        fig.text(.5, .945, f"{best['star_count']} stars + {best['planet_count']} planets used in joint epoch fit",
                 ha='center', fontsize=13, weight='bold')
    fig.text(.5, .915, 'Joint fit adopted for saved coordinates.' if joint.get('adopted') else
             'Joint fit not adopted for saved coordinates; the stellar-only solution is retained.',
             ha='center', fontsize=10, color='#8b4b00' if not joint.get('adopted') else '#006020')
    zenith = (science.get('photometry') or {}).get('photometric_zenith') or {}
    if zenith.get('zenith_source') == 'image_centre_assumption':
        fig.text(.5, .892, 'Visibility and epoch acceptance conditional on assumed image-centre zenith; not extinction-derived.',
                 ha='center', fontsize=9)
    full = fig.add_subplot(grid[0, :2])
    candidates = joint.get('candidates', [])
    if candidates:
        years = Time([c['jd_tdb'] for c in candidates], format='jd', scale='tdb').jyear
        for i, c in enumerate(candidates):
            full.scatter(years[i], c['planet_rms_arcmin'],
                         c='#aa0077' if i == index else '#888888', s=20+14*c['planet_count'],
                         marker='o' if c['eligible'] else 'x')
        full.set_xlabel('Trial epoch (Julian year TDB)')
        full.set_ylabel('Planet RMS (arcmin)')
        full.set_title(f'{len(candidates)} joint profiles across the global search\nx = contradicted; size = number of planets', fontsize=10)
    else:
        full.text(.5, .5, 'No qualifying multi-body profile\n'+joint['reason'], ha='center', va='center', wrap=True)
        full.axis('off')
    local = fig.add_subplot(grid[0, 2:])
    if best:
        profile = best['profile']
        hours = [(r['jd_tdb']-best['jd_tdb'])*24 for r in profile]
        local.plot(hours, [r['cost']-best['cost'] for r in profile], '.-', lw=1, label='stars + planets; camera refitted')
        local.axhline(1.920729410347062, color='gray', ls='--', label='conditional 95% delta-cost')
        local.axvline(0, color='#aa0077', lw=1)
        local.set_ylim(bottom=-.1, top=min(12., max(3., max(r['cost']-best['cost'] for r in profile))))
        local.set_xlabel('Hours relative to joint-fit minimum')
        local.set_ylabel('Combined objective minus minimum')
        interval_label = ('Data-bounded conditional interval' if best['bounded'] else
                          'Upper uncertainty truncated at run start (now)' if boundary['upper_interval_boundary'] == 'causal_present_time' else
                          'Conditional interval truncated by search boundary')
        epoch_utc = Time(best['jd_tdb'], format='jd', scale='tdb').utc.isot
        local.set_title(f"Joint-fit minimum: {epoch_utc} UTC\n{interval_label}", fontsize=9)
        local.axvline((best['search_limits_jd_tdb'][1]-best['jd_tdb'])*24,
                      color='#c06000', ls=':', label='search end / causal ceiling')
        metadata = joint.get('metadata_comparison')
        if metadata:
            local.axvline(-metadata['candidate_minus_metadata_seconds']/3600., color='#00a0b0',
                          ls='--', label='FITS timestamp (validation)')
        local.set_xlim(max(-12., min(hours)), max(hours)+.2)
        local.legend(fontsize=7)
    else:
        local.axis('off')
    matches = best['matches'] if best else []
    source = Path(result.get('source', ''))
    rgb = load_recorded_image(source, output).display_rgb if source.is_file() else None
    comparison = {str(r['detection_id']): r for r in (joint.get('metadata_comparison') or {}).get('rows', [])}
    for i, m in enumerate(matches[:4]):
        raw = fig.add_subplot(grid[1, i])
        ax = fig.add_subplot(grid[2, i])
        x, y = m['measured_x_px'], m['measured_y_px']
        for crop in (raw, ax):
            if rgb is not None:
                crop.imshow(rgb, interpolation='nearest')
            else:
                crop.text(.5, .5, 'Source image unavailable', transform=crop.transAxes,
                          ha='center', va='center', fontsize=8)
            crop.set_xlim(x-14, x+14); crop.set_ylim(y+14, y-14)
            crop.tick_params(labelsize=7)
        raw.set_title(f"{m['planet']} — source {m['detection_id']}\nPixels only · used in epoch fit", fontsize=9)
        ax.plot(x, y, 'o', mfc='none', mec='lime', ms=14, mew=1., label='measured centroid')
        ax.plot(m['predicted_x_px'], m['predicted_y_px'], 's', mfc='none',
                mec='#ff40c8', ms=10, mew=1., label='joint fit prediction')
        reference = comparison.get(str(m['detection_id']))
        title = f"Joint-fit residual: {m['separation_arcmin']:.2f} arcmin"
        if reference:
            ax.plot(reference['metadata_predicted_x_px'], reference['metadata_predicted_y_px'], 'D',
                    mfc='none', mec='cyan', ms=18, mew=.8, label='metadata-time prediction')
            title += f"\nMetadata-time residual: {reference['metadata_residual_arcmin']:.2f} arcmin"
        ax.set_title(title, fontsize=9)
        ax.set_xlabel('Detector x (pixels)', fontsize=8)
        if i == 0:
            raw.set_ylabel('Unmarked pixels\nDetector y (pixels)', fontsize=9)
            ax.set_ylabel('Same pixels + fit overlay\nDetector y (pixels)', fontsize=9)
    key = fig.add_subplot(grid[3, :]); key.axis('off')
    if matches:
        handles = [Line2D([], [], marker=marker, linestyle='none', mfc='none', mec=color,
                          ms=size, mew=1., label=label) for marker, color, size, label in
                   [('o', 'lime', 10, 'Measured source centroid'),
                    ('s', '#ff40c8', 8, 'Joint-fit prediction')]]
        if comparison:
            handles.append(Line2D([], [], marker='D', linestyle='none', mfc='none', mec='cyan',
                                  ms=11, mew=1., label='Metadata-time prediction — validation only'))
        key.legend(handles=handles, loc='center', ncol=len(handles), fontsize=9, frameon=False)
    footer = fig.add_subplot(grid[4, :]); footer.axis('off')
    notes = [joint['reason'],
             'Fit participation is not identity confirmation: the named planets enter the common-camera/epoch fit as hypotheses.',
             'Upper crops have NO overlays. Lower crops show the SAME pixels and scale. All symbols are at actual positions; no residual magnification.']
    if best:
        brightness = best['brightness']
        bounds_utc = Time(boundary['allowed_interval_95_jd_tdb'], format='jd', scale='tdb').utc.isot
        notes.append(f"Conditional allowed interval: {bounds_utc[0]} to {bounds_utc[1]} UTC. "
                     f"Upper end: {boundary['upper_interval_boundary'].replace('_', ' ')}; not infinite uncertainty.")
        notes.append(f"Common fit: {best['star_count']} stars + {best['planet_count']} bodies. Stellar RMS "
                     f"{joint['initial_fit']['rms_arcmin']:.3f} → {best['stellar_rms_arcmin']:.3f} arcmin. "
                     f"Brightness: {brightness['status']}, channel {brightness['channel']}, "
                     f"soft cost {brightness['cost']:.2f}; saturated channels neutral.")
        if joint.get('metadata_comparison'):
            offset = joint['metadata_comparison']['candidate_minus_metadata_seconds']
            notes.append(f'After-fit comparison: joint-fit epoch minus metadata = {offset/3600:+.3f} hours. Metadata did not bound or select the fit.')
    audit = joint.get('fits_clock_audit') or {}
    if audit.get('possible_clock_offset_hours') is not None:
        notes.append(f"HEADER CLOCK CONFLICT: DATE-OBS {audit['observation_header_time']}; file creation DATE "
                     f"{audit['creation_header_time']}; exposure {audit['exposure_seconds']:g} s. "
                     f"Possible {audit['possible_clock_offset_hours']:+d}-hour clock offset; NOT automatically corrected.")
    notes.append('No high-precision dating claim: atmosphere, topocentric parallax, frame and ephemeris systematics remain. '
                 'Brightness cannot by itself resolve positional aliases. The initial-camera global proposal search is not exhaustive over all cameras.')
    footer.text(0, 1, '\n'.join(textwrap.fill(n, 155) for n in notes), va='top', fontsize=8, linespacing=1.4)
    return fig
