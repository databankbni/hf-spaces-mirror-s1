const assert = require('assert');
const { encodeProviderRequest, createProviderContext } = require('./src/providerBridge');
const { resolveStreamsForRequest } = require('./src/streams');

async function testTokyoInsider() {
  const originalFetch = global.fetch;
  global.fetch = async () => ({
    text: async () => `
      <div class="c_h1">
        <a href="https://cdn.example/media/file1.mp4"><span>ignore</span>Server A</a>
      </div>
      <div class="c_h2">
        <a href="https://cdn.example/media/file2.mkv">Server B</a>
      </div>
      <div class="c_h2">
        <a href="https://cdn.example/skip">Skip</a>
      </div>
    `,
    headers: new Headers({ 'content-type': 'text/html' }),
    status: 200,
    url: 'https://example.test/page',
  });

  try {
    const id = encodeProviderRequest({
      provider: 'tokyoInsider',
      link: 'https://example.test/page',
      type: 'movie',
    });

    const streams = await resolveStreamsForRequest({ id, type: 'movie' });
    assert.strictEqual(streams.length, 2);
    assert.strictEqual(streams[0].url, 'https://cdn.example/media/file1.mp4');
    assert.strictEqual(streams[0].name, 'Server A');
    assert.strictEqual(streams[1].url, 'https://cdn.example/media/file2.mkv');
    assert.strictEqual(streams[1].name, 'Server B');
  } finally {
    global.fetch = originalFetch;
  }
}

async function testVadapavPassThrough() {
  const id = encodeProviderRequest({
    provider: 'vadapav',
    link: 'https://media.example/video/sample.mkv',
    type: 'movie',
  });

  const streams = await resolveStreamsForRequest({ id, type: 'movie' });
  assert.strictEqual(streams.length, 1);
  assert.strictEqual(streams[0].url, 'https://media.example/video/sample.mkv');
  assert.strictEqual(streams[0].name, 'vadapav');
}

async function main() {
  await testTokyoInsider();
  await testVadapavPassThrough();
  console.log('Verification passed: provider extraction and normalization work.');
  console.log(`Mini provider context ready: ${Boolean(createProviderContext())}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
