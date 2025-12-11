#!/usr/bin/env python3
"""
Twilio SIP Trunk Setup for LiveKit Voice Agent
Run this script to configure Twilio to route calls to LiveKit
"""

import os
import json
import base64
import urllib.request
import urllib.parse
import urllib.error
import ssl

ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
LIVEKIT_SIP_URI = 'sip.livekit.cloud'

def make_request(method, path, data=None):
    """Make authenticated request to Twilio API"""
    auth = base64.b64encode(f"{ACCOUNT_SID}:{AUTH_TOKEN}".encode()).decode()

    if 'trunking' in path or path.startswith('/v1/'):
        base_url = 'https://trunking.twilio.com'
    else:
        base_url = 'https://api.twilio.com'

    url = f"{base_url}{path}"
    headers = {
        'Authorization': f'Basic {auth}',
        'Content-Type': 'application/x-www-form-urlencoded',
    }

    if data:
        data = urllib.parse.urlencode(data).encode()

    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    # Create SSL context
    ctx = ssl.create_default_context()

    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as response:
            body = response.read().decode()
            try:
                return {'status': response.status, 'data': json.loads(body)}
            except json.JSONDecodeError:
                return {'status': response.status, 'data': body}
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return {'status': e.code, 'data': json.loads(body)}
        except:
            return {'status': e.code, 'data': body}
    except Exception as e:
        return {'status': 0, 'data': str(e)}


def main():
    if not ACCOUNT_SID or not AUTH_TOKEN:
        print('Missing TWILIO_ACCOUNT_SID or TWILIO_AUTH_TOKEN environment variables')
        return 1

    print('Setting up Twilio SIP Trunk for EMA Voice Agent\n')

    # Step 1: Verify account
    print('1. Verifying Twilio account...')
    account = make_request('GET', f'/2010-04-01/Accounts/{ACCOUNT_SID}.json')
    if account['status'] != 200:
        print(f'   Failed to verify account: {account["data"]}')
        return 1
    print(f'   Account: {account["data"].get("friendly_name")} ({account["data"].get("status")})\n')

    # Step 2: Check for existing trunks
    print('2. Checking existing SIP trunks...')
    trunks = make_request('GET', '/v1/Trunks')
    trunk_sid = None

    if trunks['status'] == 200 and trunks['data'].get('trunks'):
        for trunk in trunks['data']['trunks']:
            if 'EMA' in trunk.get('friendly_name', '') or 'LiveKit' in trunk.get('friendly_name', ''):
                trunk_sid = trunk['sid']
                print(f'   Found existing trunk: {trunk["friendly_name"]} ({trunk_sid})\n')
                break

    # Step 3: Create SIP Trunk if needed
    if not trunk_sid:
        print('3. Creating Elastic SIP Trunk...')
        trunk = make_request('POST', '/v1/Trunks', {
            'FriendlyName': 'EMA-LiveKit-Production',
            'Secure': 'true'
        })

        if trunk['status'] in [200, 201]:
            trunk_sid = trunk['data']['sid']
            print(f'   Trunk created: {trunk_sid}\n')
        else:
            print(f'   Failed to create trunk: {trunk["data"]}')
            return 1

    # Step 4: Add Origination URI (LiveKit SIP)
    print('4. Configuring LiveKit SIP endpoint...')

    # Check existing origination URIs
    existing_uris = make_request('GET', f'/v1/Trunks/{trunk_sid}/OriginationUrls')
    has_livekit = False
    if existing_uris['status'] == 200:
        for uri in existing_uris['data'].get('origination_urls', []):
            if LIVEKIT_SIP_URI in uri.get('sip_url', ''):
                has_livekit = True
                print(f'   LiveKit URI already configured: {uri["sip_url"]}\n')
                break

    if not has_livekit:
        origination = make_request('POST', f'/v1/Trunks/{trunk_sid}/OriginationUrls', {
            'FriendlyName': 'LiveKit-Cloud-SIP',
            'SipUrl': f'sip:{LIVEKIT_SIP_URI}:5060',
            'Priority': '1',
            'Weight': '1',
            'Enabled': 'true'
        })

        if origination['status'] in [200, 201]:
            print(f'   Origination URI configured: sip:{LIVEKIT_SIP_URI}:5060\n')
        else:
            print(f'   Failed to configure origination: {origination["data"]}')

    # Step 5: Search for NYC phone numbers
    print('5. Searching for NYC phone numbers...')
    search = make_request('GET',
        f'/2010-04-01/Accounts/{ACCOUNT_SID}/AvailablePhoneNumbers/US/Local.json?AreaCode=212&VoiceEnabled=true&Limit=5')

    available_numbers = []
    if search['status'] == 200:
        available_numbers = search['data'].get('available_phone_numbers', [])

    if not available_numbers:
        # Try 646
        search = make_request('GET',
            f'/2010-04-01/Accounts/{ACCOUNT_SID}/AvailablePhoneNumbers/US/Local.json?AreaCode=646&VoiceEnabled=true&Limit=5')
        if search['status'] == 200:
            available_numbers = search['data'].get('available_phone_numbers', [])

    if not available_numbers:
        # Try 917
        search = make_request('GET',
            f'/2010-04-01/Accounts/{ACCOUNT_SID}/AvailablePhoneNumbers/US/Local.json?AreaCode=917&VoiceEnabled=true&Limit=5')
        if search['status'] == 200:
            available_numbers = search['data'].get('available_phone_numbers', [])

    if available_numbers:
        print('   Available NYC numbers:')
        for i, n in enumerate(available_numbers[:5]):
            print(f'   {i+1}. {n["phone_number"]} ({n.get("locality", "NYC")})')

        # Purchase first number
        print('\n6. Purchasing phone number...')
        purchase = make_request('POST',
            f'/2010-04-01/Accounts/{ACCOUNT_SID}/IncomingPhoneNumbers.json',
            {
                'PhoneNumber': available_numbers[0]['phone_number'],
                'FriendlyName': 'EMA-Production-NYC',
                'TrunkSid': trunk_sid
            })

        if purchase['status'] in [200, 201]:
            print(f'   Purchased: {purchase["data"]["phone_number"]}')
            print(f'   Phone SID: {purchase["data"]["sid"]}\n')
        else:
            error_msg = purchase['data']
            if isinstance(error_msg, dict):
                error_msg = error_msg.get('message', str(error_msg))
            print(f'   Could not auto-purchase: {error_msg}')
            print(f'   Available numbers: {[n["phone_number"] for n in available_numbers]}')
    else:
        print('   No NYC numbers available')

    # Summary
    print('\n' + '='*50)
    print('SETUP SUMMARY')
    print('='*50)
    print(f'SIP Trunk SID: {trunk_sid}')
    print(f'LiveKit SIP: sip:{LIVEKIT_SIP_URI}:5060')
    print('\nNEXT STEPS:')
    print('1. Configure LiveKit SIP dispatch rules')
    print('2. Set trunk SID in LiveKit Cloud dashboard')
    print('3. Test inbound call')

    return 0


if __name__ == '__main__':
    exit(main())
