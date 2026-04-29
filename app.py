from flask import Flask, request, jsonify, send_from_directory
import requests
from requests.auth import HTTPBasicAuth
import os

app = Flask(__name__, static_folder='static')

API_KEY = os.environ.get('CH_API_KEY', '')
BASE_URL = 'https://api.company-information.service.gov.uk'

CORPORATE_KINDS = {
    'corporate-entity-person-with-significant-control',
    'legal-person-person-with-significant-control',
    'super-secure-person-with-significant-control',
}
INDIVIDUAL_KINDS = {'individual-person-with-significant-control'}
MAX_DEPTH = 6  # prevent infinite loops


def ch_get(path):
    resp = requests.get(
        BASE_URL + path,
        auth=HTTPBasicAuth(API_KEY, ''),
        timeout=10
    )
    if not resp.ok:
        return None
    return resp.json()


def get_active_pscs(company_number):
    """Fetch PSCs for a company, filtering out ceased ones."""
    psc_data = ch_get(f'/company/{company_number}/persons-with-significant-control')
    if not psc_data:
        return []
    all_pscs = psc_data.get('items', [])
    # Strip ceased PSCs
    return [p for p in all_pscs if not p.get('ceased', False) and not p.get('ceased_on')]


def classify_pscs(pscs):
    if not pscs:
        return 'None'
    has_corp = any(p.get('kind') in CORPORATE_KINDS for p in pscs)
    has_ind = any(p.get('kind') in INDIVIDUAL_KINDS for p in pscs)
    if has_corp and has_ind:
        return 'Mixed'
    if has_corp:
        return 'Corporate'
    if has_ind:
        return 'Individual'
    return 'Unknown'


def get_ownership_chain(company_number, visited=None, depth=0):
    """
    Recursively walk up the ownership chain.
    Returns a list of layer labels e.g. ['Corporate', 'Corporate', 'Individual']
    """
    if visited is None:
        visited = set()
    if depth >= MAX_DEPTH or company_number in visited:
        return ['Max depth reached']

    visited.add(company_number)
    pscs = get_active_pscs(company_number)

    if not pscs:
        return ['None']

    chain = []
    for psc in pscs:
        kind = psc.get('kind', '')
        if kind in CORPORATE_KINDS:
            # Try to find the company number of the parent
            identification = psc.get('identification', {})
            parent_number = identification.get('registration_number', '')
            parent_country = identification.get('country_registered', '').lower()

            # Only follow chain for UK companies
            if parent_number and ('uk' in parent_country or 'england' in parent_country
                                  or 'wales' in parent_country or 'scotland' in parent_country
                                  or parent_country == ''):
                sub_chain = get_ownership_chain(parent_number, visited.copy(), depth + 1)
                chain.append({'layer': depth + 1, 'type': 'Corporate', 'chain': sub_chain})
            else:
                chain.append({'layer': depth + 1, 'type': 'Corporate', 'chain': ['Unknown — overseas or no reg number']})
        elif kind in INDIVIDUAL_KINDS:
            chain.append({'layer': depth + 1, 'type': 'Individual', 'chain': []})

    return chain


def flatten_chain(chain, depth=1):
    """Convert nested chain into a flat list of (depth, type) tuples."""
    result = []
    for node in chain:
        if isinstance(node, dict):
            result.append({'depth': depth, 'type': node['type']})
            if node.get('chain'):
                result.extend(flatten_chain(node['chain'], depth + 1))
        else:
            result.append({'depth': depth, 'type': node})
    return result


@app.route('/')
def index():
    return send_from_directory('static', 'index.html')


@app.route('/api/search')
def search():
    name = request.args.get('q', '').strip()
    if not name:
        return jsonify({'error': 'No query provided'}), 400

    data = ch_get(f'/search/companies?q={requests.utils.quote(name)}&items_per_page=5')
    if not data or not data.get('items'):
        return jsonify({'error': 'Not found'}), 404

    items = data['items']
    company = next((i for i in items if i.get('company_status') == 'active'), items[0])
    company_number = company['company_number']

    # Get active PSCs only (ceased stripped out)
    pscs = get_active_pscs(company_number)
    classification = classify_pscs(pscs)

    psc_list = []
    for p in pscs:
        psc_list.append({
            'name': p.get('name', p.get('identification', {}).get('legal_authority', 'Unknown')),
            'kind': p.get('kind', ''),
            'is_corporate': p.get('kind') in CORPORATE_KINDS,
            'nature_of_control': p.get('natures_of_control', []),
        })

    # Build ownership chain for corporate PSCs
    ownership_chain = []
    if any(p.get('kind') in CORPORATE_KINDS for p in pscs):
        raw_chain = get_ownership_chain(company_number)
        ownership_chain = flatten_chain(raw_chain)

    # Calculate layers of ownership:
    # 0 = direct PSC is a natural person
    # 1 = one corporate layer (company A owned by company B owned by person)
    # 2 = two corporate layers, etc.
    # Logic: count the maximum depth of corporate nodes in the chain, then subtract 1
    # because depth 1 is the direct PSC of the searched company itself
    if not ownership_chain:
        # No corporate PSCs - individual owned
        max_depth = 0
    else:
        corp_nodes = [n for n in ownership_chain if n.get('type') == 'Corporate']
        if not corp_nodes:
            max_depth = 0
        else:
            # max corporate depth minus 1 gives the number of intermediate layers
            max_corp_depth = max(n['depth'] for n in corp_nodes)
            max_depth = max_corp_depth - 1

    return jsonify({
        'input_name': name,
        'company': {
            'title': company.get('title', ''),
            'company_number': company_number,
            'company_status': company.get('company_status', ''),
            'company_type': company.get('company_type', ''),
            'address': company.get('address', {}),
        },
        'classification': classification,
        'psc_count': len(pscs),
        'pscs': psc_list,
        'ownership_chain': ownership_chain,
        'ownership_depth': max_depth,
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
