const esbuild = require('esbuild');

esbuild.build({
  entryPoints: ['src/client/index.tsx'],
  bundle: true,
  outfile: 'public/bundle.js',
  platform: 'browser',
  format: 'iife',
  jsx: 'automatic',
  minify: false,
  sourcemap: true,
  define: {
    'process.env.NODE_ENV': '"production"'
  },
  loader: {
    '.tsx': 'tsx',
    '.ts': 'ts',
    '.css': 'css',
    '.woff': 'file',
    '.woff2': 'file',
    '.ttf': 'file',
    '.eot': 'file',
    '.svg': 'file',
    '.png': 'file'
  }
}).then(() => {
  console.log('Client bundle built successfully');
}).catch((err) => {
  console.error('Build failed:', err);
  process.exit(1);
});
