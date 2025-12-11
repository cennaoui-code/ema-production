#!/usr/bin/env node
/**
 * Twilio SIP Trunk Setup for LiveKit Voice Agent
 * Run this script to configure Twilio to route calls to LiveKit
 */

const https = require('https');

const ACCOUNT_SID = process.env.TWILIO_ACCOUNT_SID;
const AUTH_TOKEN = process.env.TWILIO_AUTH_TOKEN;

if (!ACCOUNT_SID || !AUTH_TOKEN) {
  console.error('Missing TWILIO_ACCOUNT_SID or TWILIO_AUTH_TOKEN environment variables');
  console.error('Usage: TWILIO_ACCOUNT_SID=ACxxx TWILIO_AUTH_TOKEN=xxx node setup-twilio-sip.js');
  process.exit(1);
}
const LIVEKIT_SIP_URI = 'sip.livekit.cloud';

function makeRequest(method, path, data = null) {
  return new Promise((resolve, reject) => {
    const auth = Buffer.from(`${ACCOUNT_SID}:${AUTH_TOKEN}`).toString('base64');
    const isJson = path.endsWith('.json');

    const options = {
      hostname: path.includes('trunking') ? 'trunking.twilio.com' : 'api.twilio.com',
      path: path,
      method: method,
      headers: {
        'Authorization': `Basic ${auth}`,
        'Content-Type': 'application/x-www-form-urlencoded',
      }
    };

    const req = https.request(options, (res) => {
      let body = '';
      res.on('data', chunk => body += chunk);
      res.on('end', () => {
        try {
          resolve({ status: res.statusCode, data: JSON.parse(body) });
        } catch {
          resolve({ status: res.statusCode, data: body });
        }
      });
    });

    req.on('error', reject);
    req.setTimeout(30000, () => { req.destroy(); reject(new Error('Timeout')); });

    if (data) {
      const formData = new URLSearchParams(data).toString();
      req.write(formData);
    }
    req.end();
  });
}

async function main() {
  console.log('🚀 Setting up Twilio SIP Trunk for EMA Voice Agent\n');

  // Step 1: Verify account
  console.log('1️⃣ Verifying Twilio account...');
  try {
    const account = await makeRequest('GET', `/2010-04-01/Accounts/${ACCOUNT_SID}.json`);
    if (account.status !== 200) {
      console.error('❌ Failed to verify account:', account.data);
      process.exit(1);
    }
    console.log(`   ✅ Account: ${account.data.friendly_name} (${account.data.status})\n`);
  } catch (err) {
    console.error('❌ Error:', err.message);
    process.exit(1);
  }

  // Step 2: Create SIP Trunk
  console.log('2️⃣ Creating Elastic SIP Trunk...');
  let trunkSid;
  try {
    const trunk = await makeRequest('POST', '/v1/Trunks', {
      FriendlyName: 'EMA-LiveKit-Production',
      Secure: 'true'
    });

    if (trunk.status === 201 || trunk.status === 200) {
      trunkSid = trunk.data.sid;
      console.log(`   ✅ Trunk created: ${trunkSid}\n`);
    } else {
      console.error('❌ Failed to create trunk:', trunk.data);
      process.exit(1);
    }
  } catch (err) {
    console.error('❌ Error:', err.message);
    process.exit(1);
  }

  // Step 3: Add Origination URI (LiveKit SIP)
  console.log('3️⃣ Configuring LiveKit SIP endpoint...');
  try {
    const origination = await makeRequest('POST', `/v1/Trunks/${trunkSid}/OriginationUrls`, {
      FriendlyName: 'LiveKit-Cloud-SIP',
      SipUrl: `sip:${LIVEKIT_SIP_URI}:5060`,
      Priority: '1',
      Weight: '1',
      Enabled: 'true'
    });

    if (origination.status === 201 || origination.status === 200) {
      console.log(`   ✅ Origination URI configured: sip:${LIVEKIT_SIP_URI}:5060\n`);
    } else {
      console.error('❌ Failed to configure origination:', origination.data);
    }
  } catch (err) {
    console.error('❌ Error:', err.message);
  }

  // Step 4: Search for NYC phone numbers
  console.log('4️⃣ Searching for NYC phone numbers...');
  try {
    const search = await makeRequest('GET',
      `/2010-04-01/Accounts/${ACCOUNT_SID}/AvailablePhoneNumbers/US/Local.json?AreaCode=212&VoiceEnabled=true&SmsEnabled=true&Limit=5`
    );

    if (search.status === 200 && search.data.available_phone_numbers?.length > 0) {
      const numbers = search.data.available_phone_numbers;
      console.log('   Available NYC numbers:');
      numbers.forEach((n, i) => console.log(`   ${i + 1}. ${n.phone_number} (${n.locality})`));

      // Purchase first number
      console.log('\n5️⃣ Purchasing phone number...');
      const purchase = await makeRequest('POST',
        `/2010-04-01/Accounts/${ACCOUNT_SID}/IncomingPhoneNumbers.json`,
        {
          PhoneNumber: numbers[0].phone_number,
          FriendlyName: 'EMA-Production-NYC',
          VoiceUrl: '', // Will configure via trunk
          TrunkSid: trunkSid
        }
      );

      if (purchase.status === 201 || purchase.status === 200) {
        console.log(`   ✅ Purchased: ${purchase.data.phone_number}`);
        console.log(`   ✅ Phone SID: ${purchase.data.sid}\n`);
      } else {
        console.log('   ⚠️ Could not auto-purchase. Manual purchase required.');
        console.log('   Available numbers:', numbers.map(n => n.phone_number).join(', '));
      }
    } else {
      // Try 646 area code
      const search646 = await makeRequest('GET',
        `/2010-04-01/Accounts/${ACCOUNT_SID}/AvailablePhoneNumbers/US/Local.json?AreaCode=646&VoiceEnabled=true&Limit=5`
      );
      if (search646.data.available_phone_numbers?.length > 0) {
        console.log('   No 212 available. Found 646 numbers:');
        search646.data.available_phone_numbers.forEach((n, i) =>
          console.log(`   ${i + 1}. ${n.phone_number}`)
        );
      }
    }
  } catch (err) {
    console.error('❌ Error searching numbers:', err.message);
  }

  // Summary
  console.log('\n' + '='.repeat(50));
  console.log('📋 SETUP SUMMARY');
  console.log('='.repeat(50));
  console.log(`SIP Trunk SID: ${trunkSid}`);
  console.log(`LiveKit SIP: sip:${LIVEKIT_SIP_URI}:5060`);
  console.log('\n🔧 NEXT STEPS:');
  console.log('1. Configure LiveKit SIP dispatch rules');
  console.log('2. Set trunk SID in LiveKit Cloud dashboard');
  console.log('3. Test inbound call');
}

main().catch(console.error);
