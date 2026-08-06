const { addonBuilder, serveHTTP } = require('stremio-addon-sdk');
const { resolveStreamsForRequest } = require('./src/streams');

const manifest = {
  id: 'org.local.provider-bridge',
  version: '1.1.0',
  name: 'Provider Bridge',
  description: 'Resolves Stremio streams from upstream provider modules.',
  resources: ['stream'],
  types: ['movie', 'series'],
  catalogs: [],
  idPrefixes: ['tt', 'vp'],
};

const builder = new addonBuilder(manifest);

builder.defineStreamHandler(async (args) => {
  try {
    const streams = await resolveStreamsForRequest(args);
    return { streams };
  } catch (error) {
    console.error('stream handler failed:', error);
    return { streams: [] };
  }
});

const port = Number(process.env.PORT || process.env.APP_PORT || 7860);

serveHTTP(builder.getInterface(), { port });

console.log(`Provider Bridge running on http://0.0.0.0:${port}/manifest.json`);
