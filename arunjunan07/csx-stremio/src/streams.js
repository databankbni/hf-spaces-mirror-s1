const path = require('path');

const { loadProviderStreamModule, decodeProviderRequest, normalizeProviderStream, createProviderContext } = require('./providerBridge');

const PROVIDER_ROOT = path.join(__dirname, '..', 'vega-providers-main');
const PROVIDER_MANIFEST_PATH = path.join(PROVIDER_ROOT, 'manifest.json');

async function resolveStreamsForRequest(args) {
  if (looksLikeEncodedProviderRequest(args.id)) {
    return resolveEncodedProviderRequest(args);
  }

  return resolveStremioRequest(args);
}

function looksLikeEncodedProviderRequest(id) {
  return typeof id === 'string' && (id.startsWith('vp_') || id.startsWith('vp:') || id.startsWith('vp'));
}

async function resolveEncodedProviderRequest(args) {
  const request = decodeProviderRequest(args.id);
  const providerModule = loadProviderStreamModule(request.provider);
  const getStream = providerModule.getStream || providerModule.default?.getStream || providerModule.default;

  if (typeof getStream !== 'function') {
    throw new Error(`Provider module '${request.provider}' does not export getStream`);
  }

  const providerContext = createProviderContext();
  const abortController = new AbortController();

  const providerStreams = await getStream({
    link: request.link,
    type: request.type || args.type,
    signal: abortController.signal,
    providerContext,
  });

  return (providerStreams || []).map(normalizeProviderStream).filter(Boolean);
}

async function resolveStremioRequest(args) {
  const { imdbId, season, episode, queryTitle, queryText } = await resolveCinemetaQuery(args);
  const providerManifest = loadProviderManifest();
  const providerContext = createProviderContext();
  const streams = [];
  const seen = new Set();

  for (const provider of providerManifest) {
    if (provider.disabled) {
      continue;
    }

    const providerModule = loadProviderModule(provider.value);
    if (!providerModule) {
      continue;
    }

    const providerStreams = await tryResolveProviderStreams({
      provider,
      providerModule,
      providerContext,
      queryTitle,
      queryText,
      imdbId,
      season,
      episode,
      type: args.type,
    });

    for (const stream of providerStreams) {
      const key = `${stream.url}|${stream.name || ''}`;
      if (!seen.has(key)) {
        seen.add(key);
        streams.push(stream);
      }
    }

    if (streams.length >= 10) {
      break;
    }
  }

  return streams;
}

function loadProviderManifest() {
  try {
    return require(PROVIDER_MANIFEST_PATH).filter(Boolean);
  } catch (error) {
    throw new Error(`Unable to read provider manifest: ${error.message}`);
  }
}

function loadProviderModule(providerValue) {
  try {
    return require(path.join(PROVIDER_ROOT, 'dist', providerValue));
  } catch {
    return null;
  }
}

async function resolveCinemetaQuery(args) {
  const [imdbId, seasonPart, episodePart] = String(args.id || '').split(':');
  const requestType = args.type === 'series' || seasonPart ? 'series' : 'movie';
  const url = `https://v3-cinemeta.strem.io/meta/${requestType}/${imdbId}.json`;
  const response = await fetch(url);
  if (!response.ok) {
    return {
      imdbId,
      season: seasonPart ? Number(seasonPart) : null,
      episode: episodePart ? Number(episodePart) : null,
      queryTitle: imdbId,
      queryText: imdbId,
    };
  }

  const data = await response.json();
  const meta = data.meta || {};
  const queryTitle = meta.name || imdbId;
  const queryText = meta.year ? `${queryTitle} ${meta.year}` : queryTitle;

  return {
    imdbId,
    season: seasonPart ? Number(seasonPart) : null,
    episode: episodePart ? Number(episodePart) : null,
    queryTitle,
    queryText,
  };
}

async function tryResolveProviderStreams({
  provider,
  providerModule,
  providerContext,
  queryTitle,
  queryText,
  imdbId,
  season,
  episode,
  type,
}) {
  const searchFn = providerModule.getSearchPosts || providerModule.getPosts;
  const metaFn = providerModule.getMeta;
  const episodesFn = providerModule.getEpisodes;
  const streamFn = providerModule.getStream;
  const abortController = new AbortController();
  const candidates = [];

  if (typeof searchFn === 'function') {
    try {
      const searchResults = await searchFn({
        searchQuery: queryText,
        page: 1,
        providerValue: provider.value,
        signal: abortController.signal,
        providerContext,
      });
      candidates.push(...(searchResults || []).slice(0, 2));
    } catch (error) {
      console.log(`search failed for ${provider.value}:`, error?.message || error);
    }
  }

  if (!candidates.length && typeof metaFn === 'function') {
    candidates.push({ link: imdbId, title: queryTitle });
  }

  const results = [];

  for (const candidate of candidates) {
    if (!candidate?.link) {
      continue;
    }

    let meta = null;
    if (typeof metaFn === 'function') {
      try {
        meta = await metaFn({
          link: candidate.link,
          provider: provider.value,
          providerContext,
        });
      } catch (error) {
        console.log(`meta failed for ${provider.value}:`, error?.message || error);
      }
    }

    const links = Array.isArray(meta?.linkList) ? meta.linkList : [];
    if (type === 'series' && season && episode) {
      const episodeLink = await resolveSeriesEpisodeLink({ links, season, episode, episodesFn, providerContext, candidateLink: candidate.link });
      if (episodeLink && typeof streamFn === 'function') {
        try {
          const providerStreams = await streamFn({
            link: episodeLink,
            type: 'series',
            signal: abortController.signal,
            providerContext,
          });
          results.push(...(providerStreams || []).map(normalizeProviderStream).filter(Boolean));
          if (results.length) {
            return results;
          }
        } catch (error) {
          console.log(`stream failed for ${provider.value}:`, error?.message || error);
        }
      }
    } else {
      for (const item of links) {
        const directLinks = Array.isArray(item?.directLinks) ? item.directLinks : [];
        for (const directLink of directLinks) {
          if (!directLink?.link || typeof streamFn !== 'function') {
            continue;
          }

          try {
            const providerStreams = await streamFn({
              link: directLink.link,
              type: 'movie',
              signal: abortController.signal,
              providerContext,
            });
            results.push(...(providerStreams || []).map(normalizeProviderStream).filter(Boolean));
          } catch (error) {
            console.log(`stream failed for ${provider.value}:`, error?.message || error);
          }
        }
      }

      if (results.length) {
        return results;
      }
    }
  }

  return results;
}

async function resolveSeriesEpisodeLink({ links, season, episode, episodesFn, providerContext, candidateLink }) {
  const seasonText = `Season ${season}`.toLowerCase();
  const episodeText = `Episode ${episode}`.toLowerCase();

  for (const linkGroup of links) {
    const title = String(linkGroup?.title || '').toLowerCase();
    if (title.includes(seasonText) || title.includes(`s${season}`)) {
      const directLinks = Array.isArray(linkGroup.directLinks) ? linkGroup.directLinks : [];
      for (const directLink of directLinks) {
        const directTitle = String(directLink?.title || '').toLowerCase();
        if (directTitle.includes(episodeText) || directTitle.includes(`e${episode}`) || directTitle.includes(`s${season}e${episode}`)) {
          return directLink.link;
        }
      }

      if (linkGroup.episodesLink && typeof episodesFn === 'function') {
        try {
          const episodes = await episodesFn({
            url: linkGroup.episodesLink,
            providerContext,
          });
          const match = (episodes || []).find((item) => {
            const normalized = String(item.title || '').toLowerCase();
            return normalized.includes(episodeText) || normalized.includes(`e${episode}`) || normalized.includes(`s${season}e${episode}`);
          });
          if (match?.link) {
            return match.link;
          }
          if (episodes?.[0]?.link) {
            return episodes[0].link;
          }
        } catch (error) {
          console.log(`episodes failed for ${candidateLink}:`, error?.message || error);
        }
      }
    }
  }

  return null;
}

module.exports = {
  resolveStreamsForRequest,
};
