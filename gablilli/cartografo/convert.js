const fontnik = require('@mapbox/fontnik');
const fs = require('fs');
const path = require('path');

const ttfPath = process.argv[2];
const outDir = process.argv[3];

const font = fs.readFileSync(ttfPath);
let pending = 0;
const total = Math.ceil(65536 / 256);

for (let i = 0; i < 65536; i += 256) {
    const end = Math.min(i + 255, 65535);
    pending++;
    fontnik.range({ font, start: i, end }, (err, data) => {
        if (!err && data) {
            fs.writeFileSync(path.join(outDir, `${i}-${end}.pbf`), data);
        }
        if (--pending === 0) {
            console.log('done: ' + path.basename(outDir));
            process.exit(0);
        }
    });
}
