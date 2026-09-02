"""Server-side i18n for LilyScript's static UI text.

Language is fixed at startup by an environment variable (`zh` or `en`, default
`en`). Unlike gr.I18n (which switches on the browser locale in the frontend),
this resolves once on the server, so every visitor sees the language the
deployment was configured with. Only static UI strings are covered — generated
scores, logs, and JS-driven status text are not translated.

Which env var: `LANG_UI` takes precedence over the standard POSIX `LANG`. Use
`LANG_UI` to set the UI language explicitly without being affected by the
system locale (e.g. on a zh_CN host where `LANG=zh_CN.UTF-8` would otherwise
flip the UI to Chinese). `LANG` is honored as a fallback for convenience.

Usage:
    from lilyscript.lang import T
    gr.Markdown(T('compose'))      # -> '## Compose' or '## 编排'

Missing keys fall back to English, then to the key itself (and log a warning),
so a typo is visible rather than silently blank.
"""

import os
import logging

LOG = logging.getLogger('lilyscript')

# Supported languages; the first is the default when LANG is unset/unknown.
SUPPORTED = ('en', 'zh')


def _resolve_lang ():
	raw = (os.environ.get('LANG_UI') or os.environ.get('LANG') or '').strip().lower()
	# LANG often looks like "en_US.UTF-8" / "zh_CN.UTF-8"; take the language subtag.
	code = raw.split('.')[0].split('_')[0]
	if code in SUPPORTED:
		return code
	return SUPPORTED[0]


LANG = _resolve_lang()


# Translation tables. Keys are stable identifiers; values are the rendered text
# (Markdown prefixes like '## ' / '- ' are part of the value so call sites stay
# identical to the original literals).
_STRINGS = {
	'en': {
		'app_title': '## 🎼 LilyScript — symbolic music generation with Lilylet\n\nBy [K.L. Λ](https://k-l-lambda.github.io/), about [Lilylet](https://github.com/k-l-lambda/lilylet)',
		'compose': '## Compose',
		'style_options': '- Style Options',
		'composer': 'composer',
		'period': 'period',
		'genre': 'genre',
		'metadata_prompt': 'Metadata prompt',
		'metadata_placeholder': 'extra metadata lines, e.g.\n[key "C major"]\n(optional)',
		'length': '- Length',
		'measures': 'Measures (0 = let model decide)',
		'max_patches': 'max patches',
		'sampler': '- Sampler',
		'temperature': 'temperature',
		'seed': 'seed',
		'generate': 'Generate',
		'generating': 'Generating… %d/%d',
		'stop': 'Stop',
		'logs': 'Logs',
		'score_list': '## Score List',
		'lilylet_editor': '## Lilylet editor',
		'share_link': '🔗 Share link',
		'open_in_live_editor': '🎹 Open in live-editor',
		'sheet_music': '## Sheet music',
		'loading_renderer': 'Loading score renderer…',
		'empty_score': 'Generate a score, or click one from the Score List to view and play it here.',
		'renderer_failed': 'Failed to load the score renderer. Click to retry.',
	},
	'zh': {
		'app_title': '## 🎼 LilyScript — 基于 Lilylet 的符号音乐生成\n\n作者 [K.L. Λ](https://k-l-lambda.github.io/), 关于 [Lilylet](https://github.com/k-l-lambda/lilylet)',
		'compose': '## 创作',
		'style_options': '- 风格选项',
		'composer': '作曲家',
		'period': '时代',
		'genre': '体裁',
		'metadata_prompt': '元数据提示',
		'metadata_placeholder': '额外的元数据行，例如\n[staves "{-}"]\n（可选）',
		'length': '- 长度',
		'measures': '小节数（0 = 由模型决定）',
		'max_patches': '最大 patch 数',
		'sampler': '- 采样器',
		'temperature': '温度',
		'seed': '随机种子',
		'generate': '生成',
		'generating': '生成中… %d/%d',
		'stop': '停止',
		'logs': '日志',
		'score_list': '## 乐谱列表',
		'lilylet_editor': '## Lilylet 编辑器',
		'share_link': '🔗 分享链接',
		'open_in_live_editor': '🎹 在 live-editor 中打开',
		'sheet_music': '## 乐谱',
		'loading_renderer': '正在加载乐谱渲染器…',
		'empty_score': '生成一段乐谱，或从乐谱列表中点击一个，即可在此查看并播放。',
		'renderer_failed': '乐谱渲染器加载失败，点击重试。',
	},
}


def T (key):
	"""Translate a UI string key into the configured language."""
	table = _STRINGS.get(LANG, _STRINGS['en'])
	if key in table:
		return table[key]
	# fall back to English, then to the raw key (visible, so typos surface)
	if key in _STRINGS['en']:
		return _STRINGS['en'][key]
	LOG.warning('i18n: missing key %r (lang=%s)', key, LANG)
	return key
