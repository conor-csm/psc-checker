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
MAX_DEPTH = 6


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
    """Fetch PSCs, stripping out any that have ceased."""
    data = ch_get(f'/company/{company_number}/persons-with-significant-control')
    if not data:
        return []
    all_pscs = data.get('items', [])
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


def count_layers(company_number, visited=None, current_depth=0):
    """
    Recursively count corporate layers between the searched company and a natural person.
    - 0 = PSC is a natural person (no corporate layers)
    - 1 = PSC is a company whose PSC is a natural person
    - 2 = two companies deep, etc.
    """
    if visited is None:
        visited = set()
    if company_number in visited or current_depth >= MAX_DEPTH:
        return current_depth

    visited.add(company_number)
    pscs = get_active_pscs(company_number)

    if not pscs:
        return current_depth

    # If any PSC is an individual, we've reached the end of the chain
    has_individual = any(p.get('kind') in INDIVIDUAL_KINDS for p in pscs)
    has_corporate = any(p.get('kind') in CORPORATE_KINDS for p in pscs)

    if has_individual and not has_corporate:
        # Owned by a person - return current depth
        return current_depth

    if has_corporate:
        # Follow each corporate PSC and take the maximum depth found
        max_found = current_depth
        for p in pscs:
            if p.get('kind') in CORPORATE_KINDS:
                reg_number = p.get('identification', {}).get('registration_number', '').strip()
                if reg_number:
                    depth = count_layers(reg_number, visited.copy(), current_depth + 1)
                    max_found = max(max_found, depth)
                else:
                    # Can't follow further (overseas or no reg number) - count this as a layer
                    max_found = max(max_found, current_depth + 1)
        return max_found

    return current_depth


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

    # Count layers of ownership
    layers = count_layers(company_number)

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
        'layers': layers,
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
