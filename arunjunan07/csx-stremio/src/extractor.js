function isPlayableUrl(url) {
  return typeof url === 'string' && /^(https?:)?\/\/|^magnet:/.test(url);
}

async function extractPlayableLinks(provider, args) {
  // Replace this with your sample extraction code.
  // Expected return shape:
  // [{ url: 'https://...', name: '1080p', description: 'optional' }]
  const candidateUrl = provider.streamUrl || provider.url || provider.link;

  if (isPlayableUrl(candidateUrl)) {
    return [
      {
        url: candidateUrl,
        name: provider.quality || provider.name,
      },
    ];
  }

  return [];
}

module.exports = {
  extractPlayableLinks,
};
