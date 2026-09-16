"""Scientific PDF for a completed point-source Barghini analysis."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import re
import textwrap

import matplotlib
matplotlib.use('Agg')
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np

from point_star_plotting import save_png
from point_star_names import plot_label


OMR_FEEDS = {'murdoc', 'gtc1', 'gtc2', 'liverpool', 'magic', 'warwick'}
OMR_SITE = dict(latitude=28.7606, longitude=-17.8850, elevation_m=2326.,
                site_source='ORM reference location inferred from OMRcam feed')


def observation_metadata(result, *, reveal=False):
    """Recover metadata only for controls or explicitly revealed post-fit validation."""
    if result.get('blind') and not (reveal or result.get('metadata_revealed')):
        return {}
    saved = result.get('observation') or {}
    metadata = {}
    if saved.get('time_utc'):
        metadata.update(observation_time=saved['time_utc'],
                        epoch_source='saved solver argument')
    if saved.get('latitude_deg') is not None and saved.get('longitude_deg') is not None:
        metadata.update(latitude=float(saved['latitude_deg']),
                        longitude=float(saved['longitude_deg']),
                        elevation_m=float(saved.get('elevation_m') or 0.),
                        site_source='saved solver arguments')

    source = Path(result.get('source', ''))
    record = None
    manifest = source.parent/'manifest.jsonl'
    if source.name and manifest.is_file():
        for line in manifest.read_text().splitlines():
            try:
                candidate = json.loads(line)
            except json.JSONDecodeError:
                continue
            if candidate.get('filename') == source.name:
                record = candidate
                break
    feed = (record or {}).get('feed')
    if feed is None and source.name:
        feed = source.name.split('_', 1)[0].lower()
    if 'observation_time' not in metadata and record and record.get('captured_at'):
        metadata['observation_time'] = record['captured_at']
        metadata['epoch_source'] = ('camera-server Last-Modified via OMRcam manifest'
                                    if record.get('last_modified') else
                                    'retrieval time via OMRcam manifest')
    if 'observation_time' not in metadata and feed in OMR_FEEDS:
        match = re.search(r'_(\d{8}T\d{6}Z)(?:_|\.)', source.name)
        if match:
            metadata['observation_time'] = match.group(1)
            metadata['epoch_source'] = 'source-or-retrieval time encoded by OMRcam filename'
    if 'latitude' not in metadata and feed in OMR_FEEDS:
        metadata.update(OMR_SITE)
    if feed:
        metadata['camera'] = str(feed).lower()
    return metadata



def report_filename(result):
    """Use a fixed report name; the run directory identifies the input."""
    return 'report.pdf'


def _fmt(value, digits=3, missing='--'):
    try:
        number = float(value)
        return f'{number:.{digits}f}' if np.isfinite(number) else missing
    except (TypeError, ValueError):
        return missing


def _camera_from_result(result):
    from point_star_barghini import BarghiniCamera
    camera = result['camera']
    return BarghiniCamera(tuple(camera['shape']), np.asarray(camera['reference_rotation']),
                          np.asarray(camera['normalised_parameters']))


def _load_science(output, science):
    if science is not None:
        return science
    path = Path(output)/'science_summary.json'
    return json.loads(path.read_text()) if path.is_file() else {}


def report_sections(result, science=None, **legacy):
    """Return concise interpretation blocks for the report."""
    science = science or {}
    fit = result['fit']
    p = result['camera']['parameters']
    stellar = result.get('stellar_epoch') or science.get('stellar_epoch') or {}
    refraction = science.get('refraction') or {}
    photometry = science.get('photometry') or {}
    extinction = photometry.get('extinction') or {}
    extinction_by_channel = photometry.get('extinction_by_channel') or {}
    planets = science.get('planets') or {}

    lens = (
        f"Barghini O/Z FET fit using {fit['count']:,} catalogue stars. "
        f"The optical centre is O=({_fmt(p['x_o'], 1)}, {_fmt(p['y_o'], 1)}) px and "
        f"the fitted reference point is Z=({_fmt(p['x_z'], 1)}, {_fmt(p['y_z'], 1)}) px. "
        f"The radial law u(r)=Vr+S[exp(Dr)-1] has V={p['v']:.6g} rad px⁻¹, "
        f"S={p['s']:.6g} rad and D={p['d']:.6g} px⁻¹."
    )
    if stellar.get('status') == 'not_identifiable':
        epoch_text = (
            f"The stellar epoch is unresolved. The saved solution uses the provisional adopted "
            f"epoch J{_fmt(stellar.get('applied_epoch_jyear'), 1)}. "
            "The profile minimum is not an established observation date."
        )
    elif stellar.get('status') == 'supplied_epoch':
        epoch_text = (
            f"Proper motions were applied at supplied epoch J{_fmt(stellar.get('applied_epoch_jyear'), 1)}; "
            "this date was not inferred from the stars."
        )
    elif stellar.get('status') == 'conditional_epoch':
        interval = stellar.get('conditional_interval_95_jyear', [None, None])
        epoch_text = (
            f"The conditional stellar epoch is J{_fmt(stellar.get('epoch_jyear'), 2)}, "
            f"with approximate conditional 95% interval {_fmt(interval[0], 2)} to {_fmt(interval[1], 2)}. "
            f"All {stellar.get('fitted_count', 0)} associations enter the fit. "
            "This interval excludes catalogue and lens/atmospheric systematic errors."
        )
    else:
        epoch_text = 'The stellar proper-motion epoch analysis has not been run.'
    astrometry = (
        f"Detector residuals are RMS {_fmt(fit['rms_px'])} px, median "
        f"{_fmt(fit['median_px'])} px and 90th percentile {_fmt(fit['p90_px'])} px. "
        + epoch_text
    )

    photometric_zenith = photometry.get('photometric_zenith') or {}
    if refraction:
        status = refraction.get('status', 'unknown').replace('_', ' ')
        atmosphere = (
            f"The empirical refraction fit has status “{status}”. Its tangent coefficients are "
            f"A={_fmt(refraction.get('refraction_a_arcsec'), 2)} arcsec and "
            f"B={_fmt(refraction.get('refraction_b_arcsec'), 3)} arcsec, with ΔBIC "
            f"{_fmt(refraction.get('delta_bic'), 1)}. The baseline/fitted RMS values are "
            f"{_fmt(refraction.get('baseline_rms_arcmin'), 2)}/"
            f"{_fmt(refraction.get('fitted_rms_arcmin'), 2)} arcmin."
        )
    else:
        atmosphere = 'The empirical refraction fit has not been run.'
    if photometric_zenith:
        zenith_status = photometric_zenith.get('status', 'unknown').replace('_', ' ')
        if photometric_zenith.get('zenith_source') == 'centred_full_horizon_geometry':
            atmosphere += (f" Blind photometric zenith: {zenith_status}. The adopted image-centre geometric zenith "
                           'comes from the closed circular sky footprint; the extinction trial remains not '
                           'identifiable, so its airmasses are provisional.')
        else:
            atmosphere += (f" Blind photometric zenith: {zenith_status}. "
                           'Extinction is a constraint; unresolved zenith gives provisional airmasses.')
    if extinction_by_channel:
        channel_values = ', '.join(
            f"{channel}: {_fmt(values.get('coefficient_mag_per_airmass'))}±"
            f"{_fmt(values.get('coefficient_sigma_mag_per_airmass'))}"
            for channel, values in extinction_by_channel.items())
        representative = extinction_by_channel.get('G') or next(iter(extinction_by_channel.values()))
        image_kind = (photometry.get('image_colour') or {}).get('classification', 'unknown')
        atmosphere += (
            f" The {image_kind.replace('_', ' ')} image gives extinction slopes "
            f"k [mag per airmass] of {channel_values}, from "
            f"{representative.get('fitted_count', 0)} stars over X="
            f"{_fmt(representative.get('airmass_range', [None, None])[0], 2)}–"
            f"{_fmt(representative.get('airmass_range', [None, None])[1], 2)}."
        )
    elif extinction:
        atmosphere += (
            f" The extinction slope is k={_fmt(extinction.get('coefficient_mag_per_airmass'))}±"
            f"{_fmt(extinction.get('coefficient_sigma_mag_per_airmass'))} mag per airmass."
        )
    else:
        atmosphere += ' The image lacks a usable airmass-based extinction fit.'

    matches = planets.get('matches') or []
    if matches:
        descriptions = [
            f"{row['planet']} at source #{row['detection_id']} "
            f"({_fmt(row['separation_px'], 2)} px; source brightness rank "
            f"{row.get('unused_brightness_rank', '--')})"
            for row in matches
        ]
        if planets.get('status') in ('planet_epoch_ambiguous', 'conditional_planet_epoch'):
            planet_text = (
                f"Blind positional candidates: {'; '.join(descriptions)}. "
                + (f"Alternative identities: {', '.join(sorted({name for values in planets.get('source_identity_alternatives', {}).values() for name in values}))}. "
                   if planets.get('source_identity_alternatives') else '') +
                f"Best candidate: {planets.get('best_candidate_epoch_tdb', '--')}. "
                f"{planets.get('candidate_count', 0)} date/identity solutions retained. "
                f"Status: {planets['status'].replace('_', ' ')}. "
                "Local precision does not resolve alternative dates or model errors. "
                "See planet_candidates.csv and planet_source_candidates.csv.")
        else:
            planet_text = (
                f"{'; '.join(descriptions)}. The planet-derived epoch is "
                f"{planets.get('derived_epoch_utc', '--')} with {planets.get('confidence', 'unknown')} "
                f"confidence and conditional local σ={_fmt(planets.get('conditional_time_sigma_minutes'), 1)} min. "
                f"There are {planets.get('competing_daily_minima', 0)} competing daily minima in the search interval."
            )
    elif planets.get('status') == 'planet_epoch_not_identifiable':
        planet_text = (
            f"Planetary epoch not identifiable: {planets.get('single_planet_candidate_count', 0)} "
            "single-planet date/identity aliases retained; no multi-planet solution. "
            "See planet_candidates.csv and planet_source_candidates.csv.")
    elif planets.get('status') == 'no_planet_match':
        planet_text = 'No competitive planet match survived the measured-source and catalogue checks.'
    else:
        planet_text = planets.get('reason', 'A blind planetary epoch has not been established.')
    evidence = planets.get('negative_evidence') or {}
    if evidence.get('contradicted_candidates'):
        planet_text += (f" Bright-planet absence checks contradict {evidence['contradicted_candidates']} positional candidates; "
                        'details in planet_non_detections.json. This is a local consistency check, not calibrated odds.')
    return dict(lens=lens, astrometry=astrometry, atmosphere=atmosphere, planets=planet_text)


def catalogue_label(result):
    """Identify the fitted catalogue from its saved content checksum."""
    checksum = result.get('catalogue_sha256')
    if not checksum:
        return 'Unrecorded catalogue'
    references = [('stars_gaia_dr3_g75.csv', 'Gaia DR3 + bright Tycho-2/Hipparcos supplement'),
                  ('stars_tycho2_mag75.csv', 'Tycho-2 + bright Hipparcos supplement')]
    for filename, label in references:
        path = Path(__file__).parent/'data'/filename
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == checksum:
            return label
    return 'Unrecognized catalogue (see saved catalogue checksum)'


def table_rows(result, science):
    fit = result['fit']
    p = result['camera']['parameters']
    stellar = result.get('stellar_epoch') or science.get('stellar_epoch') or {}
    refraction = science.get('refraction') or {}
    photometry = science.get('photometry') or {}
    by_channel = photometry.get('extinction_by_channel') or {}
    extinction = photometry.get('extinction') or {}
    planets = science.get('planets') or {}
    stellar_value = (
        f"{_fmt(stellar.get('epoch_jyear'), 1)} ({stellar.get('status', 'unknown').replace('_', ' ')})"
        if stellar else '--')
    if stellar.get('status') == 'not_identifiable':
        stellar_value = f"Unresolved; adopted J{_fmt(stellar.get('applied_epoch_jyear'), 1)}"
    planet_value = (
        f"{planets.get('derived_epoch_utc')} ({planets.get('match_count')} planet(s), "
        f"{planets.get('confidence', 'unknown')})"
        if planets.get('matches') else
        ('No matched planet' if planets.get('status') == 'no_planet_match' else
         'Not run — blind planet search unavailable' if planets.get('status') == 'not_run' else
         planets.get('status', 'Not run').replace('_', ' ')))
    if planets.get('status') in ('planet_epoch_ambiguous', 'conditional_planet_epoch'):
        label = 'Ambiguous' if planets['status'] == 'planet_epoch_ambiguous' else 'Conditional candidate'
        planet_value = f"{label}; {planets.get('candidate_count', 0)} date/identity solutions; {planets.get('match_count', 0)} planet(s) in best candidate"
    if planets.get('status') == 'planet_epoch_inconsistent':
        planet_value = 'No supported epoch; all positional candidates contradicted'
    if planets.get('status') == 'planet_epoch_not_identifiable':
        planet_value = (f"Not identifiable; {planets.get('single_planet_candidate_count', 0)} "
                        "single-planet aliases; no multi-planet solution")
    if by_channel:
        extinction_value = '; '.join(
            f"k{channel}={_fmt(values.get('coefficient_mag_per_airmass'))} ± "
            f"{_fmt(values.get('coefficient_sigma_mag_per_airmass'))}"
            for channel, values in by_channel.items()) + ' mag/airmass'
    elif extinction:
        extinction_value = (
            f"k={_fmt(extinction.get('coefficient_mag_per_airmass'))} ± "
            f"{_fmt(extinction.get('coefficient_sigma_mag_per_airmass'))} mag/airmass")
    else:
        extinction_value = '--'
    image_kind = (photometry.get('image_colour') or {}).get('classification', '--')
    return [
        ('Catalogue', catalogue_label(result)),
        ('Astrometry', f"{fit['count']}/{result['detection_count']} associations/detections; "
                       f"RMS {_fmt(fit['rms_px'])} px"),
        ('Lens', f"O=({_fmt(p['x_o'],1)},{_fmt(p['y_o'],1)}) px; "
                 f"V={p['v']:.4g}, S={p['s']:.4g}, D={p['d']:.4g}"),
        ('Stellar epoch', stellar_value),
        ('Refraction', f"{refraction.get('status', '--').replace('_', ' ')}; "
                       f"A={_fmt(refraction.get('refraction_a_arcsec'),2)} arcsec, "
                       f"B={_fmt(refraction.get('refraction_b_arcsec'),3)} arcsec; "
                       f"ΔBIC={_fmt(refraction.get('delta_bic'),1)}"),
        ('Photometry', f"{image_kind.replace('_', ' ')}; "
                       f"{photometry.get('usable_photometric_stars', photometry.get('usable_unsaturated_compact_stars', '--'))} usable stars"),
        ('Extinction', extinction_value),
        ('Planet epoch', planet_value),
    ]


def _show_image(ax, path, title):
    # PDF supports native image embedding; default interpolation downsamples
    # to the figure's 100 dpi and destroys detail in existing high-res PNGs.
    ax.imshow(mpimg.imread(path), interpolation='none')
    ax.set_title(title, fontsize=9, pad=3)
    ax.axis('off')



def _draw_photometric_zenith(ax, result, science, *, native_image):
    """Project only the saved adopted zenith through the fitted camera."""
    zenith = (science.get('photometry') or {}).get('photometric_zenith') or {}
    if not zenith:
        return None
    vector = zenith.get('zenith_unit_vector')
    note = 'Extinction zenith: no candidate'
    if vector is not None:
        # A rendered fallback overlay has margins/scaling, not detector pixels.
        # Never project a detector coordinate onto that different image frame.
        if not native_image:
            note = 'Extinction zenith: original image unavailable'
        else:
            vector = np.asarray(vector, dtype=float)
            if vector.shape == (3,) and np.all(np.isfinite(vector)) and np.linalg.norm(vector) > 0:
                camera = _camera_from_result(result)
                x, y = camera.project([vector / np.linalg.norm(vector)])[0]
                height, width = camera.shape
                if np.isfinite(x) and np.isfinite(y) and -.5 <= x < width-.5 and -.5 <= y < height-.5:
                    provisional = zenith.get('status') != 'conditional_zenith' or zenith.get('provisional', False)
                    geometric = zenith.get('zenith_source') == 'centred_full_horizon_geometry'
                    label = ('Geometric zenith' if geometric else 'Extinction zenith')
                    label += ' — ' + ('provisional' if provisional else 'conditional')
                    marker, = ax.plot(x, y, marker='x', color='red', ms=13, mew=2.5,
                                      linestyle='none', label=label, zorder=6)
                    qualifier = 'geometric' if geometric else ('provisional' if provisional else 'conditional')
                    ax.annotate(f'Zenith ({qualifier})',
                                (x, y), xytext=(9 if x < .7*width else -9, 12),
                                textcoords='offset points',
                                ha='left' if x < .7*width else 'right', color='white', fontsize=8,
                                bbox=dict(boxstyle='round,pad=.2', fc='black', ec='red', alpha=.8))
                    return marker
                note = 'Extinction zenith: candidate outside image'
            else:
                note = 'Extinction zenith: invalid candidate'
    ax.text(.02, .98, note, transform=ax.transAxes, va='top', color='white', fontsize=8,
            bbox=dict(boxstyle='round,pad=.2', fc='black', ec='red', alpha=.8))
    return None


def _draw_predicted_planets(ax, predictions):
    """Draw expected positions without implying a measured planet identification."""
    if not predictions:
        return None
    for row in predictions:
        x, y = row['predicted_x_px'], row['predicted_y_px']
        ax.plot(x, y, marker='*', ms=15, mfc='none', mec='#ff3bd5', mew=.6)
        ax.annotate(row['planet'] + ' (predicted)', (x, y), xytext=(10, -12),
                    textcoords='offset points', va='top', fontsize=8, color='#ff3bd5',
                    bbox=dict(boxstyle='round,pad=.2', fc='black', ec='none', alpha=.7))
    from matplotlib.lines import Line2D
    return Line2D([], [], marker='*', linestyle='none', markersize=11,
                  markerfacecolor='none', markeredgecolor='#ff3bd5', markeredgewidth=.6,
                  label='predicted at candidate epoch (unmatched)')


def write_report_sky_overlay(output, result, science, maximum_labels=24):
    """Draw stars, matched planets and the saved photometric zenith candidate."""
    output = Path(output)
    source = Path(result.get('source', ''))
    fallback = output/'astrometry_overlay.png'
    if not source.is_file():
        # The rendered fallback has margins/scaling, not detector coordinates.
        target = output/'report_sky_overlay.png'
        target.write_bytes(fallback.read_bytes())
        return target
    image_path = source
    rgb = mpimg.imread(image_path)
    labelled_path = output/'labelled_stars.json'
    labelled = json.loads(labelled_path.read_text()).get('stars', []) if labelled_path.is_file() else []
    labelled = labelled[:maximum_labels]
    planets = (science.get('planets') or {}).get('matches') or []

    fig, ax = plt.subplots(figsize=(8, 8))
    ax.imshow(rgb)
    height, width = rgb.shape[:2]
    for index, row in enumerate(labelled):
        x, y = float(row['x_px']), float(row['y_px'])
        ax.plot(x, y, 'o', ms=6.5, mfc='none', mec='#ffe45e', mew=.9)
        label = plot_label(row)
        if label is None:
            continue
        right = x < .76*width
        above = y > .14*height
        dx = 7 if right else -7
        dy = -7 if above else 8
        ax.annotate(label, (x, y),
                    xytext=(dx, dy), textcoords='offset points',
                    ha='left' if right else 'right',
                    va='top' if above else 'bottom',
                    fontsize=7.0, color='#ffe45e',
                    bbox=dict(boxstyle='round,pad=.14', fc='black', ec='none', alpha=.58))
    for row in planets:
        x, y = float(row['measured_x_px']), float(row['measured_y_px'])
        ax.plot(x, y, marker='*', ms=15, mfc='none', mec='#ff3bd5', mew=1.4)
        ax.annotate(row['planet'], (x, y), xytext=(10, 9), textcoords='offset points',
                    fontsize=9, weight='bold', color='white',
                    bbox=dict(boxstyle='round,pad=.2', fc='#a00078', ec='white', alpha=.9),
                    arrowprops=dict(arrowstyle='-', color='white', lw=.7))
    from matplotlib.lines import Line2D
    handles = [Line2D([], [], marker='o', linestyle='none', markersize=6,
                      markerfacecolor='none', markeredgecolor='#ffe45e',
                      label='identified catalogue star')]
    if planets:
        handles.append(Line2D([], [], marker='*', linestyle='none', markersize=11,
                              markerfacecolor='none', markeredgecolor='#ff3bd5', markeredgewidth=1.4,
                              label='planet candidate' if (science.get('planets') or {}).get('status') in
                              ('planet_epoch_ambiguous', 'conditional_planet_epoch') else 'matched planet'))
    prediction_handle = _draw_predicted_planets(
        ax, (science.get('planets') or {}).get('predicted_planets', []))
    if prediction_handle is not None:
        handles.append(prediction_handle)
    zenith_marker = _draw_photometric_zenith(
        ax, result, science, native_image=source.is_file())
    if zenith_marker is not None:
        handles.append(zenith_marker)
    legend = ax.legend(handles=handles, loc='lower left', fontsize=7,
                       facecolor='black', edgecolor='white', framealpha=.72)
    for item in legend.get_texts():
        item.set_color('white')
    ax.set_xlim(-.5, width-.5)
    ax.set_ylim(height-.5, -.5)
    ax.axis('off')
    fig.tight_layout(pad=.05)
    target = output/'report_sky_overlay.png'
    save_png(fig, target, dpi=190, bbox_inches='tight', pad_inches=.02)
    plt.close(fig)
    return target



def formula_page():
    """Return the fixed, image-independent formula reverse page."""
    fig = plt.figure(figsize=(8.27, 11.69), facecolor='white')
    fig.text(.5, .955, 'Formulae used in the wide-field solution',
             ha='center', fontsize=18, weight='bold')
    fig.text(.5, .925,
             'Symbol definitions only; no image-specific fitted values are shown.',
             ha='center', fontsize=10, color='.35')

    left = fig.add_axes((.07, .09, .41, .80))
    right = fig.add_axes((.54, .09, .39, .80))
    for ax in (left, right):
        ax.axis('off')

    left.text(0, .98, 'Barghini O/Z fish-eye mapping', fontsize=13,
              weight='bold', va='top')
    left.text(0, .91, r'Detector point and optical centre $O=(x_O,y_O)$:',
              fontsize=9.3, va='top')
    left.text(.03, .855, r'$\Delta x=x-x_O,\quad \Delta y=y-y_O$',
              fontsize=12.5, va='top')
    left.text(.03, .795, r'$r=\sqrt{\Delta x^2+\Delta y^2}$',
              fontsize=12.5, va='top')

    left.text(0, .715, 'FET radial mapping:', fontsize=9.3, va='top')
    left.text(.03, .655, r'$u(r)=Vr+S\left[\exp(Dr)-1\right]$',
              fontsize=13.5, va='top')
    left.text(.03, .585, r'$\dfrac{du}{dr}=V+SD\exp(Dr)$',
              fontsize=13, va='top')

    left.text(0, .495, 'Independent reference point $Z$:', fontsize=9.3, va='top')
    left.text(.03, .435, r'$r_\epsilon=\sqrt{(x_O-x_Z)^2+(y_O-y_Z)^2}$',
              fontsize=11.5, va='top')
    left.text(.03, .370, r'$\epsilon=u(r_\epsilon)$', fontsize=12, va='top')
    left.text(.03, .310, r'$E=\operatorname{wrap}\!\left[a_0+'
              r'\operatorname{atan2}(y_O-y_Z,x_O-x_Z)\right]$',
              fontsize=10.3, va='top')

    left.text(0, .220, 'Angular coordinates for each detector point:',
              fontsize=9.3, va='top')
    left.text(.03, .165, r'$b=a_0-E+\operatorname{atan2}(\Delta y,\Delta x)$',
              fontsize=10.5, va='top')
    left.text(.03, .110,
              r'$N=\sin b\sin u,\quad M=\cos b\sin u\cos\epsilon+'
              r'\cos u\sin\epsilon$', fontsize=9.2, va='top')
    left.text(.03, .055, r'$a=E+\operatorname{atan2}(N,M),\quad '
              r'\cos z=\cos u\cos\epsilon-\cos b\sin u\sin\epsilon$',
              fontsize=8.8, va='top')

    right.text(0, .98, 'Atmospheric-refraction model', fontsize=13,
               weight='bold', va='top')
    right.text(0, .91, r'For fitted zenith $\boldsymbol{n}$,',
               fontsize=9.3, va='top')
    right.text(.04, .855, r'$z=\cos^{-1}\!\left('
               r'\boldsymbol{s}_{\rm vacuum}\!\cdot\!'
               r'\boldsymbol{n}\right)$', fontsize=12.5, va='top')
    right.text(0, .775, 'The displacement towards the zenith is',
               fontsize=9.3, va='top')
    right.text(.04, .715, r'$R(z)=A\tan z+B\tan^3 z$',
               fontsize=13.5, va='top')
    right.text(.04, .650, r'$z_{\rm apparent}=z-R(z)$',
               fontsize=13, va='top')
    right.text(0, .575,
               '$A$ gives the leading refraction term; $B$ gives the '
               'higher-order low-altitude curvature.',
               fontsize=9.0, va='top', wrap=True)

    right.text(0, .475, 'Direction and camera rotation', fontsize=12,
               weight='bold', va='top')
    right.text(.02, .410, r'$\boldsymbol{s}_{\rm local}='
               r'(\sin z\cos a,\sin z\sin a,\cos z)$',
               fontsize=10.2, va='top')
    right.text(.02, .350, r'$\boldsymbol{s}_{\rm ICRS}='
               r'\mathbf{Q}\boldsymbol{s}_{\rm local}$',
               fontsize=11, va='top')

    right.text(0, .265, 'Parameter roles', fontsize=12,
               weight='bold', va='top')
    roles = [
        ('$a_0$', 'detector angular zero point'),
        ('$x_O,y_O$', 'optical-centre coordinates'),
        ('$x_Z,y_Z$', 'reference-point coordinates'),
        ('$V,S,D$', 'radial FET coefficients'),
        (r'$E,\epsilon$', 'optical-axis direction'),
        (r'$\mathbf{Q}$', 'camera-to-ICRS rotation'),
        (r'$\boldsymbol{n}$', 'fitted zenith direction'),
        ('$A,B$', 'refraction coefficients'),
    ]
    y = .205
    for symbol, meaning in roles:
        right.text(.02, y, symbol, fontsize=9.2, va='top')
        right.text(.27, y, meaning, fontsize=8.4, va='top')
        y -= .027

    fig.text(.5, .04,
             'Lens mapping: Barghini et al. O/Z formulation. '
             'Refraction: tangent series directed towards the fitted zenith.',
             ha='center', fontsize=8.5, color='.35')
    return fig


def photometry_comparisons(output, *, catalogue_path=None):
    """Pair finite unsaturated camera RGB magnitudes with Gaia RP/G/BP."""
    output = Path(output)
    catalogue_path = (Path(catalogue_path) if catalogue_path is not None else
                      Path(__file__).parent/'data'/'stars_gaia_dr3_g75.gaia-source.csv')
    bands = {
        'R': ('phot_rp_mean_mag', 'Gaia RP'),
        'G': ('phot_g_mean_mag', 'Gaia G'),
        'B': ('phot_bp_mean_mag', 'Gaia BP'),
    }
    answer = {
        channel: dict(catalogue_band=label, catalogue_mag=[], machine_mag=[])
        for channel, (_, label) in bands.items()
    }
    measurements_path = output/'stellar_photometry.csv'
    if not measurements_path.is_file() or not catalogue_path.is_file():
        return {channel: {**values,
                          'catalogue_mag': np.asarray(values['catalogue_mag'], dtype=float),
                          'machine_mag': np.asarray(values['machine_mag'], dtype=float)}
                for channel, values in answer.items()}

    with catalogue_path.open(newline='') as handle:
        catalogue = {row['source_id']: row for row in csv.DictReader(handle)}
    with measurements_path.open(newline='') as handle:
        measurements = list(csv.DictReader(handle))
    for row in measurements:
        if str(row.get('saturated', '')).strip().lower() == 'true':
            continue
        star_id = str(row.get('star_id', ''))
        if not star_id.startswith('Gaia DR3 '):
            continue
        catalogue_row = catalogue.get(star_id.removeprefix('Gaia DR3 '))
        if catalogue_row is None:
            continue
        for channel, (catalogue_field, _) in bands.items():
            try:
                catalogue_mag = float(catalogue_row[catalogue_field])
                machine_mag = float(row[f'{channel}_mag'])
            except (KeyError, TypeError, ValueError):
                continue
            if not (np.isfinite(catalogue_mag) and np.isfinite(machine_mag)):
                continue
            answer[channel]['catalogue_mag'].append(catalogue_mag)
            answer[channel]['machine_mag'].append(machine_mag)
    for values in answer.values():
        values['catalogue_mag'] = np.asarray(values['catalogue_mag'], dtype=float)
        values['machine_mag'] = np.asarray(values['machine_mag'], dtype=float)
    return answer


def photometry_page(output):
    """Draw camera RGB instrumental magnitudes against the nearest Gaia bands."""
    comparisons = photometry_comparisons(output)
    fig, axes = plt.subplots(1, 3, figsize=(11.69, 8.27), facecolor='white')
    fig.subplots_adjust(left=.07, right=.975, top=.82, bottom=.18, wspace=.32)
    fig.suptitle('RGB instrumental photometry versus Gaia DR3',
                 y=.965, fontsize=17, weight='bold')
    fig.text(.5, .925,
             'Unsaturated sources with finite channel and catalogue magnitudes; '
             'instrumental zero points are arbitrary.',
             ha='center', fontsize=9.5, color='.3')
    colours = {'R': '#c53b37', 'G': '#238b45', 'B': '#2878b5'}
    for ax, channel in zip(axes, 'RGB'):
        values = comparisons[channel]
        x = values['catalogue_mag']
        y = values['machine_mag']
        band = values['catalogue_band']
        ax.set_title(f'Camera {channel} versus {band}', fontsize=11,
                     color=colours[channel], weight='bold')
        ax.set_xlabel(f'{band} catalogue magnitude [mag]\n(brighter →)', fontsize=9)
        ax.set_ylabel(f'Camera {channel} instrumental magnitude [mag]\n(brighter ↑)', fontsize=9)
        ax.grid(alpha=.2)
        ax.tick_params(labelsize=8)
        if len(x) == 0:
            ax.text(.5, .5, 'No matching finite Gaia photometry',
                    transform=ax.transAxes, ha='center', va='center', color='.4')
            ax.invert_xaxis()
            ax.invert_yaxis()
            continue
        ax.scatter(x, y, s=8, color=colours[channel], alpha=.42,
                   linewidths=0, rasterized=True)
        span = np.linspace(float(np.min(x)), float(np.max(x)), 100)
        annotation = f'N={len(x):,}'
        if len(x) >= 2 and float(np.ptp(x)) > 0:
            slope, intercept = np.polyfit(x, y, 1)
            fitted = intercept+slope*x
            rms = float(np.sqrt(np.mean((y-fitted)**2)))
            ax.plot(span, intercept+slope*span, color='black', linewidth=1.2,
                    label='ordinary least-squares line')
            annotation += (f'\nOLS: m(machine) = {intercept:.3f} + '
                           f'{slope:.3f} m({band})\nRMS={rms:.3f} mag')
        ax.text(.01, .98, annotation, transform=ax.transAxes, va='top', fontsize=8,
                bbox=dict(boxstyle='round,pad=.25', fc='white', ec='.75', alpha=.9))
        if ax.lines:
            ax.legend(loc='lower right', fontsize=7, framealpha=.9)
        ax.invert_xaxis()
        ax.invert_yaxis()
    fig.text(.5, .045,
             'Gaia BP/G/RP and camera JPEG B/G/R are different, broad passbands. '
             'These plots are diagnostics, not calibrated standard magnitudes; '
             'colour terms, extinction, vignetting, saturation and JPEG response can add scatter.',
             ha='center', va='center', fontsize=8.3, color='.3', wrap=True)
    return fig


def write_report(output, result, *, science=None, **unused):
    """Write a three-page portrait PDF: results, formulae and RGB photometry."""
    output = Path(output)
    science = _load_science(output, science)
    sections = report_sections(result, science)
    sky_overlay = write_report_sky_overlay(output, result, science)

    fig = plt.figure(figsize=(8.27, 11.69))
    grid = fig.add_gridspec(4, 1, height_ratios=(5.45, 1.55, 1.75, 1.08),
                           left=.045, right=.97, top=.935, bottom=.035,
                           hspace=.24)
    ax1 = fig.add_subplot(grid[0])
    _show_image(ax1, sky_overlay,
                'Figure 1. Stars (yellow), planets (magenta); extinction zenith (red X, status in legend)')
    ax2 = fig.add_subplot(grid[1])
    second = output/'extinction_fit.png'
    if second.is_file():
        _show_image(ax2, second,
                    'Figure 2. Instrumental minus catalogue magnitude versus airmass')
    else:
        _show_image(ax2, output/'astrometry_residuals.png',
                    'Figure 2. Astrometric residuals across the detector')

    ax_table = fig.add_subplot(grid[2])
    ax_table.axis('off')
    ax_table.text(0, 1.03, 'Table 1. Per-image astrometric, lens, atmosphere and epoch results',
                  transform=ax_table.transAxes, fontsize=8.5, weight='bold', va='bottom')
    rows = table_rows(result, science)
    table = ax_table.table(cellText=rows, colLabels=('Quantity', 'Result'),
                           colWidths=(.18, .82), loc='upper left',
                           cellLoc='left', colLoc='left', bbox=(0, 0, 1, .98))
    table.auto_set_font_size(False)
    table.set_fontsize(6.8)
    for (row, column), cell in table.get_celld().items():
        cell.set_edgecolor('.7')
        cell.set_linewidth(.4)
        if row == 0:
            cell.set_facecolor('.90')
            cell.set_text_props(weight='bold')
        elif row % 2 == 0:
            cell.set_facecolor('.97')

    bottom = grid[3].subgridspec(1, 3, wspace=.13)
    blocks = [
        ('Lens and astrometry', sections['lens']+' '+sections['astrometry']),
        ('Refraction and extinction', sections['atmosphere']),
        ('Planets', sections['planets']),
    ]
    for column, (heading, body) in enumerate(blocks):
        ax = fig.add_subplot(bottom[0, column])
        ax.axis('off')
        ax.text(0, 1, heading, va='top', fontsize=7.5, weight='bold')
        ax.text(0, .84, textwrap.fill(body, width=49),
                va='top', fontsize=5.45, linespacing=1.12)

    source = Path(result.get('source', 'image')).name
    fig.suptitle(f'Wide-field image solution: {source}', fontsize=11.5, weight='bold')
    path = output/report_filename(result)
    metadata_pdf = {
        'Title': f'Wide-field image solution: {source}',
        'Author': 'Peter Thejll and Chris Flynn',
        'Subject': 'Astrometry, Barghini lens, refraction, extinction and planet epoch',
    }
    reverse = formula_page()
    photometry = photometry_page(output)
    with PdfPages(path, metadata=metadata_pdf) as pdf:
        pdf.savefig(fig)
        pdf.savefig(reverse)
        pdf.savefig(photometry)
    plt.close(fig)
    plt.close(reverse)
    plt.close(photometry)
    return path
