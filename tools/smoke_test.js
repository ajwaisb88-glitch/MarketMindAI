const http = require('http');

const url = 'http://127.0.0.1:8000/predict?asset=gold';
const maxAttempts = 20;
const delayMs = 1000;

function wait(ms) { return new Promise(r => setTimeout(r, ms)); }

async function tryFetch() {
  for (let i = 1; i <= maxAttempts; i++) {
    try {
      const data = await new Promise((resolve, reject) => {
        const req = http.get(url, (res) => {
          if (res.statusCode !== 200) return reject(new Error('Status ' + res.statusCode));
          let raw = '';
          res.on('data', chunk => raw += chunk);
          res.on('end', () => resolve(raw));
        });
        req.on('error', reject);
        req.setTimeout(2000, () => { req.destroy(new Error('timeout')); });
      });
      const json = JSON.parse(data);
      if (json && json.asset === 'gold') {
        console.log('SMOKE TEST OK:', json);
        process.exit(0);
      } else {
        console.error('Unexpected response:', json);
        process.exit(2);
      }
    } catch (err) {
      console.log(`Attempt ${i}/${maxAttempts} failed: ${err.message}`);
      if (i < maxAttempts) await wait(delayMs);
    }
  }
  console.error('SMOKE TEST FAILED: backend did not respond correctly in time');
  process.exit(1);
}

tryFetch();
