"""Display-only catalogue aliases; never inputs to the astrometric fit."""
import json
from pathlib import Path
import re


GREEK = {'alf': 'α', 'bet': 'β', 'gam': 'γ', 'del': 'δ', 'eps': 'ε', 'zet': 'ζ',
         'eta': 'η', 'tet': 'θ', 'the': 'θ', 'iot': 'ι', 'kap': 'κ', 'lam': 'λ',
         'mu': 'μ', 'nu': 'ν', 'ksi': 'ξ', 'xi': 'ξ', 'omi': 'ο', 'pi': 'π',
         'rho': 'ρ', 'sig': 'σ', 'tau': 'τ', 'ups': 'υ', 'phi': 'φ', 'khi': 'χ',
         'chi': 'χ', 'psi': 'ψ', 'ome': 'ω'}
SUPERSCRIPT = str.maketrans('0123456789', '⁰¹²³⁴⁵⁶⁷⁸⁹')


def choose_display_name(identifiers, fallback):
    aliases = [' '.join(item.split()) for item in identifiers.split('|')]
    for alias in aliases:
        match = re.fullmatch(r'\* ([a-z]{2,3})\.?([0-9]*) ([A-Z][A-Za-z]{2})(?: ([A-Z]+))?', alias)
        if match and match[1] in GREEK:
            number = str(int(match[2])).translate(SUPERSCRIPT) if match[2] else ''
            component = ' '+match[4] if match[4] else ''
            return f'{GREEK[match[1]]}{number} {match[3]}{component}'
    for alias in aliases:
        if alias.startswith('NAME '):
            return alias[5:]
    for alias in aliases:
        if re.fullmatch(r'\* \d+ [A-Z][A-Za-z]{2}(?: [A-Z]+)?', alias):
            return alias[2:]
    for alias in aliases:
        match = re.fullmatch(r'\* ([A-Za-z])([0-9]*) ([A-Z][A-Za-z]{2})(?: ([A-Z]+))?', alias)
        if match:
            number = str(int(match[2])).translate(SUPERSCRIPT) if match[2] else ''
            return match[1]+number+' '+match[3]+(' '+match[4] if match[4] else '')
    for prefix in ('V* ', 'HR ', 'HD ', 'HIP '):
        for alias in aliases:
            if alias.startswith(prefix):
                return alias[3:] if prefix == 'V* ' else alias
    return fallback


def resolve_names(star_ids, *, cache_path=None, offline=False):
    """Use cached aliases, optionally querying SIMBAD; names are display-only."""
    names = {star_id:dict(display_name=star_id, name_source='catalogue_identifier_fallback')
             for star_id in star_ids}
    if cache_path is None:
        bundled = Path(__file__).resolve().parent/'data/display_names.json'
        cache_path = bundled if bundled.is_file() else None
    cached = json.loads(Path(cache_path).read_text()) if cache_path else {}
    # SIMBAD aliases often contain the Gaia ID even when an older cache is keyed
    # by Tycho/Hipparcos. This lookup is used only after the astrometric solve.
    aliases, ambiguous = {}, set()
    for key, value in cached.items():
        for alias in [key, *value.get('aliases', '').split('|')]:
            alias = ' '.join(alias.split())
            if not alias:
                continue
            if alias in aliases and aliases[alias]['display_name'] != value['display_name']:
                ambiguous.add(alias)
            else:
                aliases[alias] = value
    for star_id in names:
        alias = ' '.join(star_id.split())
        if star_id in cached:
            names[star_id] = cached[star_id]
        elif alias in aliases and alias not in ambiguous:
            names[star_id] = aliases[alias]
    missing = [star_id for star_id in names if names[star_id]['display_name'] == star_id]
    if offline or not missing:
        return names
    try:
        from astroquery.simbad import Simbad
        simbad = Simbad()
        simbad.TIMEOUT = 30
        simbad.add_votable_fields('ids')
        result = simbad.query_objects(missing)
        if result is not None:
            for row in result:
                star_id = str(row['user_specified_id']).strip()
                if star_id not in names:
                    continue
                main_id, aliases = str(row['main_id']).strip(), str(row['ids'])
                display_name = choose_display_name(aliases+'|'+main_id, star_id)
                if display_name == star_id:
                    continue  # Unresolved/masked query rows are not named objects.
                names[star_id] = dict(display_name=display_name,
                    name_source='SIMBAD', main_id=main_id, aliases=aliases,
                    ra_deg=float(row['ra']), dec_deg=float(row['dec']))
    except Exception as error:
        print(f'SIMBAD name lookup unavailable; keeping catalogue IDs: {error}', flush=True)
    return names


def plot_label(row):
    """Show ordinary aliases; leave unnamed stars marked without a numeric label."""
    label = row.get('display_name')
    if not label or label == row.get('star_id') or label.startswith('Gaia DR3 '):
        return None
    return label
