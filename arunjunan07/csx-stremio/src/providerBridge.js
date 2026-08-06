const path = require('path');

const PROVIDER_DIST_ROOT = path.join(__dirname, '..', 'vega-providers-main', 'dist');

function loadProviderStreamModule(providerName) {
  if (!providerName || typeof providerName !== 'string') {
    throw new Error('Missing provider name in encoded request');
  }

  const modulePath = path.join(PROVIDER_DIST_ROOT, providerName, 'stream.js');
  try {
    return require(modulePath);
  } catch (error) {
    throw new Error(`Unable to load provider '${providerName}' at ${modulePath}: ${error.message}`);
  }
}

function decodeProviderRequest(encodedId) {
  if (!encodedId || typeof encodedId !== 'string') {
    throw new Error('Missing Stremio request id');
  }

  const encodedPayload = encodedId.startsWith('vp_')
    ? encodedId.slice(3)
    : encodedId.startsWith('vp:')
      ? encodedId.slice(3)
      : encodedId.startsWith('vp')
        ? encodedId.slice(2)
        : encodedId;

  const padded = encodedPayload.replace(/-/g, '+').replace(/_/g, '/');
  const base64 = padded + '='.repeat((4 - (padded.length % 4)) % 4);
  let parsed;

  try {
    parsed = JSON.parse(Buffer.from(base64, 'base64').toString('utf8'));
  } catch (error) {
    throw new Error(`Unable to decode encoded request '${encodedId}': ${error.message}`);
  }

  if (!parsed || typeof parsed !== 'object') {
    throw new Error('Decoded request must be an object');
  }

  if (!parsed.provider || !parsed.link) {
    throw new Error('Decoded request must include provider and link');
  }

  return {
    provider: parsed.provider,
    link: parsed.link,
    type: parsed.type || 'movie',
  };
}

function encodeProviderRequest({ provider, link, type }) {
  const payload = JSON.stringify({
    provider,
    link,
    type: type || 'movie',
  });

  return `vp_${Buffer.from(payload, 'utf8').toString('base64url')}`;
}

function stripTags(value) {
  return String(value || '').replace(/<script[\s\S]*?<\/script>/gi, '').replace(/<style[\s\S]*?<\/style>/gi, '').replace(/<[^>]+>/g, ' ');
}

class MiniCollection {
  constructor(elements, owner = null, childSelector = null) {
    this.elements = elements || [];
    this.owner = owner;
    this.childSelector = childSelector;
  }

  get length() {
    return this.elements.length;
  }

  first() {
    return new MiniCollection(this.elements.slice(0, 1), this.owner, this.childSelector);
  }

  map(callback) {
    return this.elements.map((element, index) => callback(index, element));
  }

  each(callback) {
    this.elements.forEach((element, index) => callback(index, element));
    return this;
  }

  find(selector) {
    const first = this.elements[0];
    if (!first) {
      return new MiniCollection([]);
    }

    const matches = findMatches(first.html, selector).map((match) => new MiniElement(match.tag, match.attributes, match.innerHtml, first));
    return new MiniCollection(matches, first, selector);
  }

  children() {
    const first = this.elements[0];
    if (!first) {
      return new MiniCollection([]);
    }

    const children = findTopLevelChildren(first.html).map((match) => new MiniElement(match.tag, match.attributes, match.innerHtml, first));
    return new MiniCollection(children, first, '*');
  }

  text() {
    const first = this.elements[0];
    return first ? stripTags(first.html).replace(/\s+/g, ' ').trim() : '';
  }

  attr(name) {
    const first = this.elements[0];
    return first ? first.attributes[name] : undefined;
  }

  parent() {
    const first = this.elements[0];
    if (!first || !first.parent) {
      return new MiniCollection([]);
    }

    return new MiniCollection([first.parent]);
  }

  remove() {
    if (!this.owner || !this.childSelector) {
      return this;
    }

    const selector = this.childSelector.trim();
    if (selector === 'span') {
      this.owner.html = this.owner.html.replace(/<span[\s\S]*?<\/span>/gi, '');
    }

    return this;
  }
}

class MiniElement {
  constructor(tag, attributes, innerHtml, parent = null) {
    this.tag = tag;
    this.attributes = attributes;
    this.innerHtml = innerHtml;
    this.parent = parent;
    this.html = `<${tag}${serializeAttributes(attributes)}>${innerHtml}</${tag}>`;
  }
}

function serializeAttributes(attributes) {
  return Object.entries(attributes || {})
    .map(([key, value]) => ` ${key}="${String(value).replace(/"/g, '&quot;')}"`)
    .join('');
}

function parseAttributes(source) {
  const attributes = {};
  source.replace(/([\w:-]+)\s*=\s*(["'])(.*?)\2/g, (_, key, __, value) => {
    attributes[key] = value;
    return '';
  });
  return attributes;
}

function findMatches(html, selector) {
  const selectors = selector.split(',').map((item) => item.trim()).filter(Boolean);
  const matches = [];

  for (const item of selectors) {
    const tagMatch = item.match(/^([a-z0-9_-]+)(:contains\((?:"([^"]*)"|'([^']*)')\))?$/i);
    const classMatch = item.match(/^\.([a-z0-9_-]+(?:\.[a-z0-9_-]+)*)$/i);
    if (tagMatch) {
      const tagName = tagMatch[1].toLowerCase();
      const containsText = tagMatch[3] || tagMatch[4] || '';
      const regex = new RegExp(`<${tagName}([^>]*)>([\\s\\S]*?)<\/${tagName}>`, 'gi');
      let match;
      while ((match = regex.exec(html))) {
        const attributes = parseAttributes(match[1]);
        const innerHtml = match[2];
        if (!containsText || stripTags(innerHtml).includes(containsText)) {
          matches.push({ tag: tagName, attributes, innerHtml });
        }
      }
      continue;
    }

    if (classMatch) {
      const classNames = classMatch[1].split('.');
      const regex = /<([a-z0-9_-]+)([^>]*)>([\s\S]*?)<\/\1>/gi;
      let match;
      while ((match = regex.exec(html))) {
        const attributes = parseAttributes(match[2]);
        const classList = String(attributes.class || '').split(/\s+/).filter(Boolean);
        const hasAllClasses = classNames.every((name) => classList.includes(name));
        if (hasAllClasses) {
          matches.push({ tag: match[1].toLowerCase(), attributes, innerHtml: match[3] });
        }
      }
      continue;
    }
  }

  return matches;
}

function findTopLevelChildren(html) {
  const children = [];
  const regex = /<([a-z0-9_-]+)([^>]*)>([\s\S]*?)<\/\1>/gi;
  let match;
  while ((match = regex.exec(html))) {
    children.push({ tag: match[1].toLowerCase(), attributes: parseAttributes(match[2]), innerHtml: match[3] });
  }
  return children;
}

function createMiniCheerio() {
  return {
    load(html) {
      const root = new MiniElement('root', {}, html, null);

      const $ = (selectorOrElement) => {
        if (selectorOrElement instanceof MiniElement) {
          return new MiniCollection([selectorOrElement]);
        }

        if (selectorOrElement instanceof MiniCollection) {
          return selectorOrElement;
        }

        if (typeof selectorOrElement === 'string') {
          const matches = findMatches(html, selectorOrElement).map((match) => new MiniElement(match.tag, match.attributes, match.innerHtml, root));
          return new MiniCollection(matches, root, selectorOrElement);
        }

        return new MiniCollection([]);
      };

      return $;
    },
  };
}

function normalizeHeaders(headers) {
  return Object.fromEntries(
    Object.entries(headers || {}).filter(([, value]) => value !== undefined && value !== null),
  );
}

function parseResponseData(responseText, contentType) {
  if (contentType && /json/i.test(contentType)) {
    try {
      return JSON.parse(responseText);
    } catch {
      return responseText;
    }
  }

  const trimmed = responseText.trim();
  if ((trimmed.startsWith('{') && trimmed.endsWith('}')) || (trimmed.startsWith('[') && trimmed.endsWith(']'))) {
    try {
      return JSON.parse(trimmed);
    } catch {
      return responseText;
    }
  }

  return responseText;
}

function createAxiosLike() {
  const request = async (method, url, options = {}) => {
    const response = await fetch(url, {
      method,
      headers: normalizeHeaders(options.headers),
      body: options.body,
      signal: options.signal,
      redirect: options.redirect || 'follow',
    });

    const text = method === 'HEAD' ? '' : await response.text();
    return {
      data: parseResponseData(text, response.headers.get('content-type') || ''),
      headers: Object.fromEntries(response.headers.entries()),
      status: response.status,
      request: {
        responseURL: response.url,
      },
    };
  };

  const axiosLike = async (url, options = {}) => request('GET', url, options);
  axiosLike.get = (url, options = {}) => request('GET', url, options);
  axiosLike.head = (url, options = {}) => request('HEAD', url, options);
  axiosLike.post = (url, body, options = {}) => {
    let requestBody = body;
    const headers = normalizeHeaders(options.headers);

    if (body && typeof body === 'object' && !(body instanceof FormData) && !(body instanceof URLSearchParams) && typeof body !== 'string' && !ArrayBuffer.isView(body)) {
      requestBody = JSON.stringify(body);
      if (!headers['content-type'] && !headers['Content-Type']) {
        headers['Content-Type'] = 'application/json';
      }
    }

    return request('POST', url, {
      ...options,
      headers,
      body: requestBody,
    });
  };

  return axiosLike;
}

function createProviderContext() {
  return {
    axios: createAxiosLike(),
    commonHeaders: {
      Accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
      'Accept-Language': 'en-US,en;q=0.9',
      'Cache-Control': 'no-cache',
      DNT: '1',
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    },
    Aes: {},
    cheerio: createMiniCheerio(),
    openWebView: async () => {
      throw new Error('openWebView is not available in this local runtime');
    },
  };
}

function normalizeProviderStream(stream) {
  if (!stream || typeof stream !== 'object') {
    return null;
  }

  const url = stream.url || stream.link;
  if (!url || typeof url !== 'string') {
    return null;
  }

  const nameParts = [stream.server, stream.quality].filter(Boolean);
  const name = nameParts.length > 0 ? nameParts.join(' • ') : 'Play';
  const normalized = {
    url,
    name,
  };

  if (stream.description) {
    normalized.description = stream.description;
  }

  if (stream.subtitles) {
    normalized.subtitles = stream.subtitles;
  }

  if (stream.headers && typeof stream.headers === 'object' && Object.keys(stream.headers).length > 0) {
    normalized.behaviorHints = {
      proxyHeaders: {
        request: stream.headers,
      },
      notWebReady: true,
    };
  }

  try {
    const urlObject = new URL(url);
    const filename = urlObject.pathname.split('/').filter(Boolean).pop();
    if (filename) {
      normalized.behaviorHints = {
        ...(normalized.behaviorHints || {}),
        filename: normalized.behaviorHints?.filename || filename,
      };
    }
  } catch {
    // Ignore non-standard URLs such as magnet links.
  }

  return normalized;
}

module.exports = {
  createProviderContext,
  decodeProviderRequest,
  encodeProviderRequest,
  loadProviderStreamModule,
  normalizeProviderStream,
};
