// Cache completed writing calls by exact prompt. A changed prompt never reuses old work.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

async function writingCall(dir, prompt, request, accept, report = () => {}) {
    const key = crypto.createHash('sha256').update(prompt).digest('hex');
    const folder = path.join(dir, 'writing_progress');
    const file = path.join(folder, key + '.json');
    if (fs.existsSync(file)) {
        try {
            const saved = JSON.parse(fs.readFileSync(file, 'utf8'));
            if (saved.promptHash === key && accept(saved.answer)) {
                report('restored completed writing call from disk');
                return saved.answer;
            }
        } catch { /* Corrupt/incompatible progress is not a usable answer. */ }
    }
    const answer = await request();
    if (accept(answer)) {
        fs.mkdirSync(folder, { recursive: true });
        const temp = file + '.' + process.pid + '.tmp';
        fs.writeFileSync(temp, JSON.stringify({ promptHash: key, savedAt: new Date().toISOString(), answer }, null, 2) + '\n');
        fs.renameSync(temp, file);
    }
    return answer;
}
module.exports = { writingCall };
