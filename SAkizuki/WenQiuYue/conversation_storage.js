(() => {
  'use strict';

  const STORAGE_VERSION = 3;
  const ASSET_REF_PREFIX = 'asset:sha256:';
  const MAX_IMAGES_PER_MESSAGE = 4;
  const MAX_IMAGE_ASSET_BYTES = 2 * 1024 * 1024;
  const MAX_CONVERSATION_BYTES = 64 * 1024 * 1024;
  const MAX_IMPORT_FILE_BYTES = 200 * 1024 * 1024;
  const MAX_EXPORT_BYTES = 200 * 1024 * 1024;

  function isDataImageUrl(value) {
    return typeof value === 'string' && /^data:image\//i.test(value);
  }

  function isAssetRef(value) {
    return typeof value === 'string' && value.startsWith(ASSET_REF_PREFIX);
  }

  function assetIdFromRef(value) {
    return isAssetRef(value) ? value.slice(ASSET_REF_PREFIX.length) : '';
  }

  function assetRef(id) {
    return `${ASSET_REF_PREFIX}${id}`;
  }

  function dataUrlToBlob(dataUrl) {
    const match = String(dataUrl || '').match(/^data:([^;,]+)?(?:;charset=[^;,]+)?;base64,([\s\S]+)$/i);
    if (!match) throw new Error('图片不是有效的 Base64 Data URL');
    const binary = atob(match[2]);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
    return new Blob([bytes], { type: match[1] || 'application/octet-stream' });
  }

  function blobToDataUrl(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ''));
      reader.onerror = () => reject(reader.error || new Error('无法读取图片资产'));
      reader.readAsDataURL(blob);
    });
  }

  async function sha256Blob(blob) {
    const digest = await crypto.subtle.digest('SHA-256', await blob.arrayBuffer());
    return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, '0')).join('');
  }

  function mapMessageImages(message, replaceUrl) {
    const copy = { ...message };
    if (!Array.isArray(message?.content)) return copy;
    copy.content = message.content.map(part => {
      if (part?.type !== 'image_url' || !part.image_url) return part && typeof part === 'object' ? { ...part } : part;
      return {
        ...part,
        image_url: { ...part.image_url, url: replaceUrl(part.image_url.url) },
      };
    });
    return copy;
  }

  function mapTreeImages(tree, replaceUrl) {
    return {
      version: tree?.version || 2,
      activeNodeId: tree?.activeNodeId || null,
      nodes: (tree?.nodes || []).map(node => ({
        ...node,
        userImages: (node.userImages || []).map(image => ({
          ...image,
          dataUrl: replaceUrl(image?.dataUrl || ''),
        })),
        messages: (node.messages || []).map(message => mapMessageImages(message, replaceUrl)),
      })),
    };
  }

  function collectTreeImageUrls(tree, predicate) {
    const values = new Set();
    const collect = value => { if (predicate(value)) values.add(value); };
    for (const node of tree?.nodes || []) {
      for (const image of node.userImages || []) collect(image?.dataUrl);
      for (const message of node.messages || []) {
        if (!Array.isArray(message?.content)) continue;
        for (const part of message.content) {
          if (part?.type === 'image_url') collect(part.image_url?.url);
        }
      }
    }
    return [...values];
  }

  async function externalizeTreeImages(tree) {
    const dataUrls = collectTreeImageUrls(tree, isDataImageUrl);
    const entries = await Promise.all(dataUrls.map(async dataUrl => {
      const blob = dataUrlToBlob(dataUrl);
      if (blob.size > MAX_IMAGE_ASSET_BYTES) {
        throw new Error(`单张图片压缩后仍超过 ${Math.round(MAX_IMAGE_ASSET_BYTES / 1024 / 1024)} MB`);
      }
      const id = await sha256Blob(blob);
      return { dataUrl, asset: { id, blob, size: blob.size, type: blob.type } };
    }));
    const refs = new Map(entries.map(entry => [entry.dataUrl, assetRef(entry.asset.id)]));
    return {
      tree: mapTreeImages(tree, value => refs.get(value) || value),
      assets: [...new Map(entries.map(entry => [entry.asset.id, entry.asset])).values()],
    };
  }

  function collectAssetIds(tree) {
    return collectTreeImageUrls(tree, isAssetRef).map(assetIdFromRef);
  }

  async function hydrateTreeImages(tree, assetRecords) {
    const records = assetRecords instanceof Map
      ? assetRecords
      : new Map((assetRecords || []).map(record => [record.id, record]));
    const dataUrls = new Map();
    await Promise.all([...records].map(async ([id, record]) => {
      if (record?.blob instanceof Blob) dataUrls.set(id, await blobToDataUrl(record.blob));
      else if (isDataImageUrl(record?.dataUrl)) dataUrls.set(id, record.dataUrl);
    }));
    return mapTreeImages(tree, value => {
      if (!isAssetRef(value)) return value;
      return dataUrls.get(assetIdFromRef(value)) || '';
    });
  }

  function hydratePortableTree(tree, portableAssets = []) {
    const dataUrls = new Map(portableAssets
      .filter(asset => asset && typeof asset.id === 'string' && isDataImageUrl(asset.dataUrl))
      .map(asset => [asset.id, asset.dataUrl]));
    return mapTreeImages(tree, value => {
      if (!isAssetRef(value)) return value;
      return dataUrls.get(assetIdFromRef(value)) || '';
    });
  }

  async function assetsToPortable(assetRecords) {
    return Promise.all((assetRecords || []).map(async record => ({
      id: record.id,
      dataUrl: record.dataUrl || await blobToDataUrl(record.blob),
    })));
  }

  async function portableToAssets(portableAssets = []) {
    const assets = [];
    for (const item of portableAssets) {
      if (!item || typeof item.id !== 'string' || !isDataImageUrl(item.dataUrl)) continue;
      const blob = dataUrlToBlob(item.dataUrl);
      if (blob.size > MAX_IMAGE_ASSET_BYTES) throw new Error('导入文件包含超过单图限制的图片');
      const actualId = await sha256Blob(blob);
      if (actualId !== item.id) throw new Error('导入文件中的图片校验失败');
      assets.push({ id: actualId, blob, size: blob.size, type: blob.type });
    }
    return assets;
  }

  function getTreeHistory(tree, nodeId = tree?.activeNodeId) {
    const byId = new Map((tree?.nodes || []).map(node => [node.id, node]));
    const path = [];
    const seen = new Set();
    let node = byId.get(nodeId);
    while (node && !seen.has(node.id)) {
      seen.add(node.id);
      path.unshift(node);
      node = byId.get(node.parentId);
    }
    return path.flatMap(item => item.messages || []);
  }

  function normalizeTraceState(record, fallbackNodeId = null) {
    const state = record?.traceState;
    if (state && typeof state === 'object') {
      return {
        nodeId: typeof state.nodeId === 'string' ? state.nodeId : fallbackNodeId,
        systemMessage: state.systemMessage?.role === 'system' ? state.systemMessage : null,
      };
    }
    const oldTrace = Array.isArray(record?.traceMessages) ? record.traceMessages : [];
    return {
      nodeId: fallbackNodeId,
      systemMessage: oldTrace.find(message => message?.role === 'system') || null,
    };
  }

  function jsonBytes(value) {
    return new Blob([JSON.stringify(value)]).size;
  }

  function assertConversationSize(record, assets = []) {
    const total = jsonBytes(record) + assets.reduce((sum, asset) => sum + (asset.size || asset.blob?.size || 0), 0);
    if (total > MAX_CONVERSATION_BYTES) {
      throw new Error(`当前对话约 ${(total / 1024 / 1024).toFixed(1)} MB，超过 ${MAX_CONVERSATION_BYTES / 1024 / 1024} MB 本地保存上限`);
    }
    return total;
  }

  function assertImportFileSize(file) {
    if (file?.size > MAX_IMPORT_FILE_BYTES) {
      throw new Error(`导入文件超过 ${MAX_IMPORT_FILE_BYTES / 1024 / 1024} MB 上限`);
    }
  }

  function assertExportSize(payload) {
    const size = jsonBytes(payload);
    if (size > MAX_EXPORT_BYTES) {
      throw new Error(`导出文件约 ${(size / 1024 / 1024).toFixed(1)} MB，超过 ${MAX_EXPORT_BYTES / 1024 / 1024} MB 上限`);
    }
    return size;
  }

  window.WQYConversationStorage = {
    STORAGE_VERSION,
    ASSET_REF_PREFIX,
    MAX_IMAGES_PER_MESSAGE,
    MAX_IMAGE_ASSET_BYTES,
    MAX_CONVERSATION_BYTES,
    MAX_IMPORT_FILE_BYTES,
    MAX_EXPORT_BYTES,
    isDataImageUrl,
    isAssetRef,
    assetIdFromRef,
    dataUrlToBlob,
    externalizeTreeImages,
    collectAssetIds,
    hydrateTreeImages,
    hydratePortableTree,
    assetsToPortable,
    portableToAssets,
    getTreeHistory,
    normalizeTraceState,
    jsonBytes,
    assertConversationSize,
    assertImportFileSize,
    assertExportSize,
  };
})();
